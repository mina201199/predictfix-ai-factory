import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from . import store, auth

PEOPLE=[
 {'name':'Amy Chen','specialty':'主軸／軸承','skills':['主軸','軸承'],'cases':18,'success':16,'shift':'早班','capacity':3,'demo_tasks':['CNC-03 主軸振動巡檢']},
 {'name':'Alex Lin','specialty':'冷卻／液壓','skills':['冷卻','液壓','泵'],'cases':12,'success':10,'shift':'早班','capacity':3,'demo_tasks':['CNC-06 冷卻流量確認']},
 {'name':'Bob Wang','specialty':'綜合設備','skills':['巡檢','螺桿'],'cases':4,'success':3,'shift':'早班','capacity':2,'demo_tasks':[]},
 {'name':'Grace Huang','specialty':'刀具／加工品質','skills':['刀具','刀片'],'cases':24,'success':21,'shift':'早班','capacity':3,'demo_tasks':['CNC-05 刀片磨耗檢查','CNC-12 換刀後試切']},
 {'name':'David Wu','specialty':'伺服／進給螺桿','skills':['螺桿','伺服','定位'],'cases':16,'success':14,'shift':'中班','capacity':2,'demo_tasks':['CNC-09 定位誤差量測']},
 {'name':'Ivy Liu','specialty':'電控／PLC','skills':['電控','PLC','警報'],'cases':20,'success':17,'shift':'中班','capacity':3,'demo_tasks':['CNC-14 電控警報查核']},
 {'name':'Eric Tsai','specialty':'潤滑／預防保養','skills':['潤滑','巡檢','保養'],'cases':15,'success':13,'shift':'晚班','capacity':3,'demo_tasks':['CNC-08 例行潤滑']},
 {'name':'Nina Chang','specialty':'五軸／幾何精度','skills':['五軸','對心','定位'],'cases':11,'success':9,'shift':'早班','capacity':2,'demo_tasks':[]}
]

def seed():
    with store.Session() as s:
        for m in json.loads((Path(__file__).resolve().parents[1]/'artifacts/demo-machines.json').read_text(encoding='utf-8')):
            if s.get(store.Machine,m['id']) is None:
                s.add(store.Machine(id=m['id'],payload=json.dumps(m,ensure_ascii=False)))
        s.flush()
        first_asset_seed=s.scalar(select(store.Audit).where(store.Audit.kind=='asset_demo_seed_v1')) is None
        for i,m in enumerate(s.scalars(select(store.Machine).order_by(store.Machine.id)).all()):
            if not first_asset_seed and m.id not in {f'CNC-{n:02}' for n in range(1,19)}:continue
            data=json.loads(m.payload);asset=data.get('asset',{});today=datetime.now().date()
            asset.setdefault('installed_on',(today-timedelta(days=730+i*97)).isoformat())
            asset.setdefault('responsible',PEOPLE[i%8]['name'])
            dates=asset.setdefault('part_dates',{})
            for j in range(len(data['parts'])):dates.setdefault(str(j),(today-timedelta(days=120+(i*43+j*71)%600)).isoformat())
            asset.setdefault('next_inspection',(today+timedelta(days=7+i%14)).isoformat())
            if not asset.get('inspections'):asset['inspections']=[{'date':(today-timedelta(days=60-n*25+i%7)).isoformat(),'inspector':PEOPLE[(i+n)%8]['name'],'note':['潤滑油位與漏油巡檢，補充潤滑並清潔濾網。','量測主軸溫升與軸向間隙，已保存巡檢數據。','冷卻流量、刀具磨耗與定位精度確認；異常零件列入追蹤。'][n],'source':'demo_seed'} for n in range(3)]
            asset.setdefault('source','demo_seed');data['asset']=asset;m.payload=json.dumps(data,ensure_ascii=False)
        if first_asset_seed:s.add(store.Audit(kind='asset_demo_seed_v1',request_id=__import__('uuid').uuid4().hex,payload=json.dumps({'source':'demo_seed','scope':'existing catalog lifecycle backfill'})))
        s.commit()

def active_machine(mid):
    with store.Session() as s:
        m=s.get(store.Machine,mid)
        if not m or not m.active:raise HTTPException(422,'設備不存在或已停用')

def people():
    with store.Session() as s:
        tasks=[store.ticket_dict(t) for t in s.scalars(select(store.Ticket).where(store.Ticket.status!='已完成')).all()]
    return [{**p,'tasks':[t for t in tasks if t['engineer']==p['name']],
             'workload':sum(t['engineer']==p['name'] for t in tasks),'source':'履歷與示例任務為 DEMO；正式任務讀取工單資料庫'} for p in PEOPLE]

class NewMachine(BaseModel):
    id:str=Field(pattern=r'^CNC-\d{2,4}$')
    name:str=Field(min_length=2,max_length=50)
    kind:str=Field(pattern=r'^(mill|lathe)$')

class Assignment(BaseModel):
    engineer:str
    reason:str=''

class ReviewInput(BaseModel):
    reviewer:str=Field(default='',max_length=50)
    decision:str=Field(pattern=r'^(approve|reject)$')
    note:str=Field(min_length=3,max_length=1000)

class AssetInput(BaseModel):
    installed_on:str|None=None
    part_dates:dict[str,str|None]=Field(default_factory=dict)
    responsible:str=Field(default='',max_length=50)
    next_inspection:str|None=None
    inspection_date:str|None=None
    inspector:str=Field(default='',max_length=50)
    inspection_note:str=Field(default='',max_length=1000)

def register(app):
    @app.patch('/api/tickets/{tid}/assign')
    def assign(tid:str,body:Assignment,request:Request):
        auth.supervisor(request)
        if body.engineer not in ['待指派']+[p['name'] for p in PEOPLE]:raise HTTPException(422,'維修人員不存在')
        with store.Session() as s:
            t=s.get(store.Ticket,tid)
            if not t:raise HTTPException(404,'工單不存在')
            if t.status in ['已完成','待主管審核']:raise HTTPException(409,'已結案或待審核工單不可重新派工')
            if t.engineer==body.engineer:return store.ticket_dict(t)
            if t.engineer!='待指派' and len(body.reason.strip())<3:raise HTTPException(422,'重新派工需要原因')
            active_machine(t.machine)
            old=t.engineer;t.engineer=body.engineer;t.status='待指派' if body.engineer=='待指派' else '已指派'
            s.add(store.Audit(kind='ticket_reassigned',request_id=__import__('uuid').uuid4().hex,payload=json.dumps({'id':tid,'from':old,'to':body.engineer,'reason':body.reason,'actor':request.state.user['name']},ensure_ascii=False)));s.commit()
            return store.ticket_dict(t)
    @app.post('/api/tickets/{tid}/start')
    def start(tid:str,request:Request):
        with store.Session() as s:
            t=s.get(store.Ticket,tid)
            if not t:raise HTTPException(404,'工單不存在')
            auth.assigned(request,t)
            if t.status not in ['已指派','退回重修']:raise HTTPException(409,'此狀態不能開始維修')
            t.status='維修中';s.commit();return store.ticket_dict(t)
    @app.post('/api/tickets/{tid}/review')
    def review(tid:str,body:ReviewInput,request:Request):
        auth.supervisor(request)
        if len(body.note.strip())<3:raise HTTPException(422,'請填主管與審核說明')
        with store.Session() as s:
            t=s.get(store.Ticket,tid)
            if not t:raise HTTPException(404,'工單不存在')
            if t.status!='待主管審核':raise HTTPException(409,'工單尚未提交審核')
            t.status='已完成' if body.decision=='approve' else '退回重修'
            meta=s.get(store.Workflow,tid);data=json.loads(meta.payload) if meta else {}
            if meta is None:meta=store.Workflow(id=tid,payload='{}');s.add(meta)
            review={'reviewer':request.state.user['name'],'decision':body.decision,'note':body.note.strip(),'at':datetime.now(timezone.utc).isoformat()}
            data.setdefault('reviews',[]).append(review);meta.payload=json.dumps(data,ensure_ascii=False)
            s.add(store.Audit(kind='ticket_completed' if body.decision=='approve' else 'ticket_rejected',request_id=__import__('uuid').uuid4().hex,payload=json.dumps({'id':tid,**review},ensure_ascii=False)));s.commit();return store.ticket_dict(t)
    @app.patch('/api/machines/{mid}/asset')
    def asset(mid:str,body:AssetInput,request:Request):
        auth.supervisor(request)
        values=body.model_dump()
        dates=[body.installed_on,body.inspection_date,*body.part_dates.values()]
        if body.next_inspection:
            try:datetime.strptime(body.next_inspection,'%Y-%m-%d')
            except ValueError:raise HTTPException(422,'下次檢核日期格式不符')
        try:
            for date in dates:
                if date:
                    parsed=datetime.strptime(date,'%Y-%m-%d')
                    if parsed.date()>datetime.now().date():raise ValueError('Future date')
        except ValueError:raise HTTPException(422,'日期格式不符或紀錄日期晚於今日')
        if body.inspection_date and (len(body.inspection_note.strip())<3):raise HTTPException(422,'檢核需填人員與結果')
        with store.Session() as s:
            m=s.get(store.Machine,mid)
            if not m or not m.active:raise HTTPException(404,'設備不存在')
            data=json.loads(m.payload);old=data.get('asset',{})
            for key in ['installed_on','part_dates','responsible','next_inspection']:old[key]=values[key]
            if body.inspection_date:old.setdefault('inspections',[]).append({'date':body.inspection_date,'inspector':request.state.user['name'],'note':body.inspection_note})
            data['asset']=old;m.payload=json.dumps(data,ensure_ascii=False);s.commit();return data
    @app.get('/api/machines')
    def machines(include_inactive:bool=False):
        with store.Session() as s:
            return [{**json.loads(m.payload),'active':bool(m.active)} for m in s.scalars(select(store.Machine).order_by(store.Machine.id)).all() if m.active or include_inactive]
    @app.post('/api/machines',status_code=201)
    def create(body:NewMachine,request:Request):
        auth.supervisor(request)
        if not body.name.strip():raise HTTPException(422,'名稱不可空白')
        with store.Session() as s:
            if s.get(store.Machine,body.id):raise HTTPException(409,'設備編號已存在（含停用設備）')
            template=json.loads(s.scalar(select(store.Machine)).payload)
            template.pop('asset',None)
            template.update(id=body.id,name=body.name.strip(),kind=body.kind,util=0,hours=0,status='待建檔',risk=0)
            template['parts']=[[p[0],None,0,p[3],None,'新設備尚未取得量測資料，健康度未知。'] for p in template['parts']]
            if body.kind=='lathe':template['parts'][1][0]='車削刀片';template['parts'][2][0]='液壓泵'
            s.add(store.Machine(id=body.id,payload=json.dumps(template,ensure_ascii=False)));s.commit()
        return template
    @app.delete('/api/machines/{mid}')
    def remove(mid:str,request:Request):
        auth.supervisor(request)
        with store.Session() as s:
            m=s.get(store.Machine,mid)
            if not m:raise HTTPException(404,'設備不存在')
            if s.scalar(select(store.Ticket).where(store.Ticket.machine==mid,store.Ticket.status!='已完成')):raise HTTPException(409,'設備仍有未結案工單，請先結案')
            m.active=0;s.commit()
        return {'id':mid,'active':False,'message':'已停用；歷史工單保留，可復原'}
    @app.post('/api/machines/{mid}/restore')
    def restore(mid:str,request:Request):
        auth.supervisor(request)
        with store.Session() as s:
            m=s.get(store.Machine,mid)
            if not m:raise HTTPException(404,'設備不存在')
            m.active=1;s.commit()
        return {'id':mid,'active':True}
    @app.get('/api/personnel')
    def personnel():return people()
    @app.get('/api/analytics')
    def analytics():
        with store.Session() as s:
            tickets=[store.ticket_dict(t) for t in s.scalars(select(store.Ticket)).all()]
            completed={json.loads(a.payload)['id']:a.created_at for a in s.scalars(select(store.Audit).where(store.Audit.kind=='ticket_completed')).all()}
        durations=[]
        for t in tickets:
            if t['id'] in completed:durations.append(max(0,(completed[t['id']].replace(tzinfo=None)-datetime.fromisoformat(t['created_at']).replace(tzinfo=None)).total_seconds()/3600))
        counts={m:sum(t['machine']==m for t in tickets) for m in sorted({t['machine'] for t in tickets})}
        return {'total':len(tickets),'open':sum(t['status']!='已完成' for t in tickets),'unassigned':sum(t['status']!='已完成' and t['engineer']=='待指派' for t in tickets),'completed':sum(t['status']=='已完成' for t in tickets),'mean_closure_hours':round(sum(durations)/len(durations),2) if durations else None,'closure_samples':len(durations),'machine_counts':counts,'repeat_reports':{m:n for m,n in counts.items() if n>1},'scope':'全部已保存工單；建立至結案耗時不等同實際修復工時，重複報修不等同重複故障'}
