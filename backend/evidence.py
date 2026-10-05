import hashlib, io, json, re, uuid, warnings, csv
from datetime import datetime, timezone
from typing import Literal
from fastapi import Request, HTTPException
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select,func
from . import store,auth
MAX_BYTES=6*1024*1024
UNITS={'temperature':'°C','vibration':'mm/s','current':'A','pressure':'bar','speed':'rpm','deviation':'μm'}
class Measurement(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    metric:Literal['temperature','vibration','current','pressure','speed','deviation']
    before:float|None=None
    after:float
    conditions:str=Field(default='',max_length=200)
def metadata(row):
    return {'id':row.id,'filename':row.filename,'media_type':row.media_type,'sha256':row.sha256,'bytes':len(row.content),'uploaded_by':row.uploader,'uploaded_at':row.created_at.isoformat(),'url':'/api/evidence/'+row.id}
def submission(db,ticket,body,user):
    if len(set(body.photo_ids))!=len(body.photo_ids):raise HTTPException(422,'照片編號重複')
    photos=[]
    for eid in body.photo_ids:
        row=db.get(store.Evidence,eid)
        if not row or row.ticket_id!=ticket.id or row.uploader!=user['username']:raise HTTPException(422,'照片不屬於此工單或登入人員')
        photos.append(metadata(row))
    return {'note':body.note,'measurements':[{**m.model_dump(),'unit':UNITS[m.metric]} for m in body.measurements],'photos':photos,'submitted_by':user['name'],'submitted_at':datetime.now(timezone.utc).isoformat(),'image_ai_used':False}
def register(app):
    @app.post('/api/tickets/{tid}/photos',status_code=201)
    async def upload(tid:str,request:Request):
        with store.Session() as db:
            ticket=db.get(store.Ticket,tid)
            if not ticket:raise HTTPException(404,'工單不存在')
            auth.assigned(request,ticket)
            if ticket.status not in ['已指派','維修中','退回重修']:raise HTTPException(409,'此狀態不可新增照片')
        content=bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content)>MAX_BYTES:raise HTTPException(413,'每張照片上限 6 MB')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    if image.format not in ['JPEG','PNG','WEBP']:raise ValueError('format')
                    if image.width*image.height>20_000_000:raise ValueError('size')
                    media=Image.MIME[image.format];image.verify()
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):raise HTTPException(422,'請上傳有效的 JPG、PNG 或 WebP 照片（最多 2,000 萬畫素）')
        filename=request.query_params.get('filename','維修照片')
        filename=re.sub(r'[\\/\x00-\x1f]','_',filename)[:120]
        with store.Session() as db:
            ticket=db.get(store.Ticket,tid);auth.assigned(request,ticket)
            if ticket.status not in ['已指派','維修中','退回重修']:raise HTTPException(409,'工單狀態已變更')
            if db.scalar(select(func.count()).select_from(store.Evidence).where(store.Evidence.ticket_id==tid))>=30:raise HTTPException(422,'此工單照片總數已達 30 張')
            row=store.Evidence(id='PHOTO-'+uuid.uuid4().hex,ticket_id=tid,uploader=request.state.user['username'],filename=filename,media_type=media,sha256=hashlib.sha256(content).hexdigest(),content=bytes(content));db.add(row)
            db.add(store.Audit(kind='evidence_uploaded',request_id=uuid.uuid4().hex,payload=json.dumps({'ticket':tid,'photo':row.id,'actor':request.state.user['name'],'sha256':row.sha256},ensure_ascii=False)));db.commit();return metadata(row)
    @app.post('/api/tickets/{tid}/measurements/import')
    async def import_values(tid:str,request:Request):
        with store.Session() as db:
            ticket=db.get(store.Ticket,tid)
            if not ticket:raise HTTPException(404,'工單不存在')
            auth.assigned(request,ticket)
            if ticket.status not in ['已指派','維修中','退回重修']:raise HTTPException(409,'此狀態不能匯入量測')
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>65536:raise HTTPException(413,'CSV 上限 64 KB')
        try:
            rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            if not rows or len(rows)>6:raise ValueError('rows')
            result=[Measurement(metric=r['metric'],before=float(r['before']) if r.get('before') else None,after=float(r['after']),conditions=r.get('conditions','')).model_dump() for r in rows]
            if len({r['metric'] for r in result})!=len(result):raise ValueError('duplicates')
        except (UnicodeError,KeyError,ValueError,csv.Error):raise HTTPException(422,'CSV 需為 UTF-8，欄位 metric,before,after,conditions；最多 6 筆且指標不重複')
        return {'measurements':result,'source':'csv_import','sha256':hashlib.sha256(raw).hexdigest()}
    @app.get('/api/tickets/{tid}/photos')
    def list_photos(tid:str,request:Request):
        with store.Session() as db:
            ticket=db.get(store.Ticket,tid)
            if not ticket:raise HTTPException(404,'工單不存在')
            rows=db.scalars(select(store.Evidence).where(store.Evidence.ticket_id==tid).order_by(store.Evidence.created_at)).all()
            if ticket.engineer!=request.state.user['name'] and request.state.user['role']!='supervisor':
                wf=db.get(store.Workflow,tid);data=json.loads(wf.payload) if wf else {}
                visible={p['id'] for sub in data.get('submissions',[]) for p in sub.get('photos',[])}
                rows=[r for r in rows if r.id in visible]
            return [metadata(r) for r in rows]
    @app.get('/api/evidence/{eid}')
    def image(eid:str,request:Request):
        with store.Session() as db:
            row=db.get(store.Evidence,eid)
            if not row:raise HTTPException(404,'照片不存在')
            if row.uploader!=request.state.user['username'] and request.state.user['role']!='supervisor':
                wf=db.get(store.Workflow,row.ticket_id);data=json.loads(wf.payload) if wf else {}
                if not any(row.id==p['id'] for sub in data.get('submissions',[]) for p in sub.get('photos',[])):raise HTTPException(403,'照片尚未提交')
            return Response(row.content,media_type=row.media_type,headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, no-store','Content-Disposition':'inline'})
