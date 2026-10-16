"""Nameplate scan, machine overview and AI summary routes."""
import io
import json
import re
import time
import warnings
from collections import defaultdict
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select

from . import config, machine_metrics, nameplate, repair_flow, store, workforce

ROOT=Path(__file__).resolve().parents[1]
SAMPLES=ROOT/'artifacts'/'demo-nameplates'
SAMPLE_NAME=re.compile(r'^[A-Z]{2,5}-\d{2}\.png$')
MAX_BYTES=6*1024*1024
MAX_PIXELS=20_000_000
# 手機原圖動輒 4000 像素寬，縮小後辨識率不變但速度快數倍
OCR_EDGE=1600


def prepared_image(content):
  try:
    with warnings.catch_warnings():
      warnings.simplefilter('error',Image.DecompressionBombWarning)
      with Image.open(io.BytesIO(content)) as image:
        if image.format not in ['JPEG','PNG','WEBP']:raise ValueError('format')
        if image.width*image.height>MAX_PIXELS:raise ValueError('size')
        image.load()
        # 手機直拍的照片靠 EXIF 記錄方向，不轉正 OCR 會讀到橫躺的字
        upright=ImageOps.exif_transpose(image).convert('RGB')
  except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
    raise HTTPException(422,'請上傳有效的 JPG、PNG 或 WebP 照片（最多 2,000 萬畫素）')
  upright.thumbnail((OCR_EDGE,OCR_EDGE))
  buffer=io.BytesIO()
  upright.save(buffer,'PNG')
  return buffer.getvalue()


def active_machine_ids():
  with store.Session() as db:
    return [m.id for m in db.scalars(select(store.Machine).where(store.Machine.active==1).order_by(store.Machine.id)).all()]


def iso(value):
  return machine_metrics.utc(value).isoformat() if value else None


def people_section(asset,tickets):
  responsible=asset.get('responsible') or None
  person=None
  if responsible:
    entry=next((p for p in workforce.roster() if p['name']==responsible),None)
    if entry:
      person={'name':responsible,'on_duty':entry['on_duty'],'attendance':entry['attendance'],'shift':entry['shift'],'open_tickets':entry['workload']}
    else:
      # 負責人可能是主管或已停用帳號，不在工程師名冊裡；仍顯示姓名與手上工單
      person={'name':responsible,'on_duty':None,'attendance':None,'shift':None,
              'open_tickets':sum(t.engineer==responsible and t.status!='已完成' for t in tickets)}
  inspections=sorted(asset.get('inspections') or [],key=lambda i:i.get('date') or '')
  last=inspections[-1] if inspections else None
  if not last and asset.get('inspection_date'):
    last={'date':asset['inspection_date'],'inspector':asset.get('inspector'),'note':asset.get('inspection_note')}
  return {'responsible':person,'last_inspection':{'date':last.get('date'),'inspector':last.get('inspector'),'note':last.get('note')} if last else None}


def build_overview(db,mid):
  row=db.get(store.Machine,mid)
  if not row or not row.active:return None
  data=json.loads(row.payload)
  asset=data.get('asset') or {}
  tickets=db.scalars(select(store.Ticket).where(store.Ticket.machine==mid)).all()
  ids=[t.id for t in tickets]
  # 一次批次取出所有關聯資料，避免每張工單各查一次
  workflows={w.id:json.loads(w.payload) for w in db.scalars(select(store.Workflow).where(store.Workflow.id.in_(ids))).all()} if ids else {}
  logs=defaultdict(list)
  for log in (db.scalars(select(store.WorkLog).where(store.WorkLog.ticket_id.in_(ids)).order_by(store.WorkLog.created_at)).all() if ids else []):
    logs[log.ticket_id].append(log)
  photos=dict(db.execute(select(store.Evidence.ticket_id,func.count()).where(store.Evidence.ticket_id.in_(ids)).group_by(store.Evidence.ticket_id)).all()) if ids else {}
  cases={c.ticket_id:c.id for c in db.scalars(select(store.RepairCase).where(store.RepairCase.ticket_id.in_(ids),store.RepairCase.status=='published')).all()} if ids else {}
  parts=[]
  for index,part in enumerate(data.get('parts') or []):
    name,health,used,life,remaining,note=(list(part)+[None]*6)[:6]
    parts.append({'name':name,'health':health,'used':used,'life':life,'remaining':remaining,'note':note,
                  'replaced_on':(asset.get('part_dates') or {}).get(str(index))})
  inProgress=[]
  for t in sorted((t for t in tickets if t.status!='已完成'),key=lambda t:machine_metrics.utc(t.created_at),reverse=True):
    latest=logs[t.id][-1] if logs[t.id] else None
    inProgress.append({'id':t.id,'issue':t.issue,'engineer':t.engineer,'status':t.status,'created_at':iso(t.created_at),
                       'logged_minutes':sum(l.minutes for l in logs[t.id]),
                       'latest_log':{'note':latest.note,'minutes':latest.minutes,'at':iso(latest.created_at),'username':latest.username} if latest else None})
  history=[]
  for t in (t for t in tickets if t.status=='已完成'):
    closed=machine_metrics.closed_at(workflows.get(t.id))
    history.append({'id':t.id,'issue':t.issue,'engineer':t.engineer,'created_at':iso(t.created_at),'closed_at':closed.isoformat() if closed else None,
                    'completion_note':t.completion_note,'photo_count':photos.get(t.id,0),'case_id':cases.get(t.id)})
  history.sort(key=lambda h:h['closed_at'] or h['created_at'],reverse=True)
  plans=[]
  for plan in db.scalars(select(store.MaintenancePlan)).all():
    payload=json.loads(plan.payload)
    if payload.get('machine')==mid and payload.get('active',True):
      p=repair_flow.plan_dict(plan)
      plans.append({k:p.get(k) for k in ['id','title','next_due','days_until_due','reminder']})
  stock=[]
  items=db.scalars(select(store.StockItem)).all()
  for part in parts:
    for item in items:
      # 零件與庫存沒有正式對應欄位，用名稱互相包含比對；比不到就不列，不猜
      if part['name'] and (part['name'] in item.name or item.name in part['name']):
        stock.append({'part':part['name'],'item_id':item.id,'name':item.name,'quantity':item.quantity,'minimum':item.minimum,'low':item.quantity<item.minimum})
  return {'data_mode':'demo' if config.demo() else 'production',
          'machine':{'id':mid,'name':data.get('name'),'kind':data.get('kind'),'machine_model':data.get('machine_model'),
                     'installed_on':asset.get('installed_on'),'hours':data.get('hours')},
          'live':{k:data.get(k) for k in ['status','risk','temp','vib','util']},
          'parts':parts,
          'people':people_section(asset,tickets),
          'in_progress':inProgress,
          'history':history[:20],
          'maintenance':{'next_inspection':asset.get('next_inspection'),'plans':sorted(plans,key=lambda p:p['next_due'] or '')},
          'stock':stock,
          'reliability':machine_metrics.reliability([{'created_at':t.created_at,'closed_at':machine_metrics.closed_at(workflows.get(t.id)),
                                                      'preventive':bool(workflows.get(t.id,{}).get('maintenance_plan_id'))} for t in tickets])}


def register(app):
  @app.post('/api/scan/nameplate')
  async def scan_nameplate(request:Request):
    content=bytearray()
    async for chunk in request.stream():
      content.extend(chunk)
      if len(content)>MAX_BYTES:raise HTTPException(413,'照片上限 6 MB')
    image=prepared_image(bytes(content))
    started=time.perf_counter()
    lines=await run_in_threadpool(nameplate.recognize,image)
    candidates=nameplate.match_machine_ids(lines,active_machine_ids())
    info=nameplate.engine_info()
    return {'candidates':candidates,'decision':nameplate.decide(candidates),'text':[text for text,_ in lines],
            'elapsed_ms':round((time.perf_counter()-started)*1000),'engine':info['engine']+' '+info['version']}

  @app.get('/api/machines/{mid}/overview')
  def machine_overview(mid:str):
    with store.Session() as db:
      overview=build_overview(db,mid)
    if overview is None:raise HTTPException(404,'設備不存在或已停用')
    return overview

  @app.get('/api/scan/samples')
  def scan_samples():
    if not config.demo():raise HTTPException(404)
    return [{'machine_id':path.stem,'url':'/api/scan/samples/'+path.name}
            for path in sorted(SAMPLES.glob('*.png')) if SAMPLE_NAME.match(path.name)]

  @app.get('/api/scan/samples/{name}')
  def scan_sample(name:str):
    # 檔名先過白名單再組路徑，避免 ../ 之類的路徑穿越
    if not config.demo() or not SAMPLE_NAME.match(name) or not (SAMPLES/name).is_file():raise HTTPException(404)
    return FileResponse(SAMPLES/name,media_type='image/png')
