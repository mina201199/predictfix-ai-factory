"""Account administration, dated attendance and explainable dispatch."""
import json
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from . import store, auth

def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def log(db, kind, request, data):
    db.add(store.Audit(kind=kind,request_id=uuid.uuid4().hex,payload=json.dumps({'actor':request.state.user['username'],**data},ensure_ascii=False)))

def revoke(db, username):
    db.execute(delete(store.LoginSession).where(store.LoginSession.username==username))

def lock_dispatch(db,name=None):
    """Serialize check + write for assignments and roster changes."""
    if store.engine.dialect.name=='sqlite':
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
    elif name is not None:
        db.scalar(select(store.User).where(store.User.name==name).with_for_update())

class ProfileInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    specialty: str = Field(default='',max_length=100)
    skills: list[str] = Field(default_factory=list,max_length=30)
    qualifications: list[str] = Field(default_factory=list,max_length=30)
    @field_validator('skills','qualifications')
    @classmethod
    def tags(cls, values):
        if any(not v.strip() or len(v)>60 for v in values):raise ValueError('技能或資格每項需為 1–60 字')
        return sorted(set(v.strip() for v in values))

class UserInput(ProfileInput):
    username: str = Field(pattern=r'^[a-z][a-z0-9_.-]{2,49}$')
    name: str = Field(min_length=2,max_length=50)
    role: str = Field(pattern=r'^(supervisor|engineer)$')
    password: str = Field(min_length=16,max_length=200)

class ActiveInput(BaseModel):
    active: bool

class PasswordInput(BaseModel):
    password: str = Field(min_length=16,max_length=200)

class ChangePassword(PasswordInput):
    current_password: str = Field(min_length=1,max_length=200)

class DutyInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username: str
    starts_at: datetime
    ends_at: datetime
    attendance: str = Field(pattern=r'^(present|scheduled|leave|absent)$')
    capacity_minutes: int = Field(ge=0,le=1440)
    note: str = Field(default='',max_length=500)

class EstimateInput(BaseModel):
    remaining_minutes: int = Field(ge=0,le=100000)
    required_qualifications: list[str] = Field(default_factory=list,max_length=30)
    note: str = Field(min_length=3,max_length=500)

class WorkLogInput(BaseModel):
    minutes: int = Field(gt=0,le=1440)
    note: str = Field(min_length=3,max_length=1000)

def roster(at=None):
    at=utc(at or datetime.now(timezone.utc))
    with store.Session() as db:
        users=db.scalars(select(store.User).where(store.User.active==1,store.User.role=='engineer')).all()
        tickets=db.scalars(select(store.Ticket).where(store.Ticket.status!='已完成')).all()
        profiles={p.username:json.loads(p.payload) for p in db.scalars(select(store.EngineerProfile)).all()}
        workflows={w.id:json.loads(w.payload) for w in db.scalars(select(store.Workflow)).all()}
        duties=db.scalars(select(store.Duty)).all()
        result=[]
        for user in users:
            current=next((d for d in duties if d.username==user.username and utc(d.starts_at)<=at<utc(d.ends_at)),None)
            tasks=[t for t in tickets if t.engineer==user.name]
            # Pending approval consumes no repair minutes but remains visible as an open case.
            repair_tasks=[t for t in tasks if t.status!='待主管審核']
            estimates=[workflows.get(t.id,{}).get('remaining_minutes') for t in repair_tasks]
            missing=sum(v is None for v in estimates)
            remaining=sum(v for v in estimates if v is not None)
            budget=min(current.capacity_minutes,int((utc(current.ends_at)-at).total_seconds()/60)) if current else 0
            present=current is not None and current.attendance=='present'
            result.append({'username':user.username,'name':user.name,**profiles.get(user.username,{'skills':[],'specialty':'','qualifications':[]}),
                'tasks':[store.ticket_dict(t) for t in tasks],'workload':len(tasks),'remaining_minutes':remaining,
                'unestimated_cases':missing,'capacity_minutes':budget,'available_minutes':max(0,budget-remaining),
                'attendance':current.attendance if current else 'no_schedule','on_duty':present,
                'shift':current.note or '出勤已確認' if present else '未在班／未確認出勤',
                'capacity':max(1,len(tasks)),'source':'帳號、出勤及工單資料庫'})
        return result

def recommendations(part, at=None, required=None, minutes=60):
    result=[]
    for p in roster(at):
        match=any(s.lower() in part.lower() for s in p['skills'])
        missing=set(required or [])-set(p['qualifications'])
        eligible=p['on_duty'] and not missing and not p['unestimated_cases'] and p['available_minutes']>=minutes
        skill=60 if match else 0
        availability=round(40*p['available_minutes']/max(1,p['capacity_minutes']))
        reasons=[f"出勤：{p['attendance']}",f"未結案 {p['workload']} 件；已估剩餘 {p['remaining_minutes']} 分鐘；未估 {p['unestimated_cases']} 件",
                 f"本班剩餘可用 {p['available_minutes']} 分鐘；新案需求 {minutes} 分鐘",
                 '技能符合' if match else '技能未符合：需要主管確認', '資格缺少：'+ '、'.join(sorted(missing)) if missing else '已滿足指定資格']
        result.append({**p,'score':skill+availability if eligible else 0,'eligible':eligible,
                       'breakdown':{'skill':skill,'availability':availability},'reasons':reasons,'method':'attendance_capacity_rules'})
    return sorted(result,key=lambda p:(p['eligible'],p['score'],-p['workload']),reverse=True)

def check_assignment(name, ticket_id=None):
    if name=='待指派':return
    with store.Session() as db:
        user=db.scalar(select(store.User).where(store.User.name==name,store.User.active==1,store.User.role=='engineer'))
        if not user:raise HTTPException(422,'工程師帳號不存在或已停用')
        meta=db.get(store.Workflow,ticket_id) if ticket_id else None
        data=json.loads(meta.payload) if meta else {}
    p=next((p for p in recommendations('',required=data.get('required_qualifications',[]),minutes=data.get('remaining_minutes',60)) if p['name']==name),None)
    if not p or not p['eligible']:raise HTTPException(409,'工程師未確認當班出勤、資格不符、負荷未估或剩餘工時不足，請先更新排班與工單估時')

def register(app):
    @app.get('/api/admin/users')
    def users(request:Request):
        auth.supervisor(request)
        with store.Session() as db:
            return [{'username':u.username,'name':u.name,'role':u.role,'active':bool(u.active)} for u in db.scalars(select(store.User).order_by(store.User.username)).all()]

    @app.post('/api/admin/users',status_code=201)
    def create_user(body:UserInput,request:Request):
        auth.supervisor(request)
        if not body.name.strip():raise HTTPException(422,'名稱不可空白')
        with store.Session() as db:
            lock_dispatch(db)
            if db.get(store.User,body.username) or db.scalar(select(store.User).where(store.User.name==body.name.strip())):raise HTTPException(409,'帳號或顯示名稱已存在')
            db.add(store.User(username=body.username,name=body.name.strip(),role=body.role,password_hash=auth.password_hash(body.password)))
            db.add(store.EngineerProfile(username=body.username,payload=json.dumps(body.model_dump(include={'specialty','skills','qualifications'}),ensure_ascii=False)))
            log(db,'user_created',request,{'username':body.username,'role':body.role})
            try:db.commit()
            except IntegrityError:raise HTTPException(409,'帳號已存在')
        return {'username':body.username,'name':body.name.strip(),'role':body.role}

    @app.put('/api/admin/users/{username}/profile')
    def profile(username:str,body:ProfileInput,request:Request):
        auth.supervisor(request)
        with store.Session() as db:
            lock_dispatch(db)
            if not db.scalar(select(store.User).where(store.User.username==username).with_for_update()):raise HTTPException(404,'帳號不存在')
            p=db.get(store.EngineerProfile,username)
            if not p:p=store.EngineerProfile(username=username,payload='{}');db.add(p)
            p.payload=json.dumps(body.model_dump(),ensure_ascii=False)
            log(db,'profile_updated',request,{'username':username,**body.model_dump()});db.commit()
        return body.model_dump()

    @app.put('/api/admin/users/{username}/active')
    def active(username:str,body:ActiveInput,request:Request):
        auth.supervisor(request)
        with store.Session() as db:
            lock_dispatch(db)
            # Lock supervisors in a stable order to protect the last administrator on PostgreSQL.
            admins=db.scalars(select(store.User).where(store.User.role=='supervisor',store.User.active==1).order_by(store.User.username).with_for_update()).all()
            user=db.scalar(select(store.User).where(store.User.username==username).with_for_update())
            if not user:raise HTTPException(404,'帳號不存在')
            if not body.active:
                if username==request.state.user['username']:raise HTTPException(409,'不可停用自己')
                if user.role=='supervisor' and user.active and len(admins)<=1:raise HTTPException(409,'必須保留一位主管')
                if db.scalar(select(store.Ticket).where(store.Ticket.engineer==user.name,store.Ticket.status!='已完成')):raise HTTPException(409,'請先交接未結案工單')
                revoke(db,username)
            user.active=int(body.active);log(db,'user_active',request,{'username':username,'active':body.active});db.commit()
        return {'active':body.active}

    @app.put('/api/admin/users/{username}/password')
    def reset_password(username:str,body:PasswordInput,request:Request):
        auth.supervisor(request)
        with store.Session() as db:
            user=db.get(store.User,username)
            if not user:raise HTTPException(404,'帳號不存在')
            user.password_hash=auth.password_hash(body.password);revoke(db,username)
            log(db,'password_reset',request,{'username':username});db.commit()
        return {'ok':True,'sessions_revoked':True}

    @app.put('/api/auth/password')
    def change_password(body:ChangePassword,request:Request):
        import hmac
        with store.Session() as db:
            user=db.get(store.User,request.state.user['username'])
            if not hmac.compare_digest(auth.password_hash(body.current_password,user.password_hash.split(':')[0]),user.password_hash):raise HTTPException(403,'目前密碼不符')
            user.password_hash=auth.password_hash(body.password);revoke(db,user.username)
            log(db,'password_changed',request,{'username':user.username});db.commit()
        return {'ok':True,'sessions_revoked':True}

    @app.get('/api/duties')
    def duties():
        with store.Session() as db:
            return [{'id':d.id,'username':d.username,'starts_at':utc(d.starts_at).isoformat(),'ends_at':utc(d.ends_at).isoformat(),
                     'attendance':d.attendance,'capacity_minutes':d.capacity_minutes,'note':d.note} for d in db.scalars(select(store.Duty).order_by(store.Duty.starts_at.desc())).all()]

    @app.post('/api/duties',status_code=201)
    def create_duty(body:DutyInput,request:Request):
        auth.supervisor(request)
        if body.starts_at.tzinfo is None or body.ends_at.tzinfo is None:raise HTTPException(422,'排班時間必須包含時區')
        start,end=utc(body.starts_at),utc(body.ends_at)
        length=int((end-start).total_seconds()/60)
        if length<=0 or length>1440 or body.capacity_minutes>length:raise HTTPException(422,'班次需為 1–1440 分鐘，可用工時不得超過班次')
        with store.Session() as db:
            lock_dispatch(db)
            user=db.get(store.User,body.username)
            if not user or not user.active or user.role!='engineer':raise HTTPException(422,'工程師不存在或已停用')
            db.scalar(select(store.User).where(store.User.username==body.username).with_for_update())
            if db.scalar(select(store.Duty).where(store.Duty.username==body.username,store.Duty.starts_at<end,store.Duty.ends_at>start)):raise HTTPException(409,'與既有班次重疊')
            duty=store.Duty(id='DUTY-'+uuid.uuid4().hex,**{**body.model_dump(),'starts_at':start,'ends_at':end})
            db.add(duty);log(db,'duty_created',request,{'id':duty.id,**body.model_dump(mode='json')});db.commit()
        return {'id':duty.id}

    @app.put('/api/duties/{did}/attendance')
    def attendance(did:str,body:DutyInput,request:Request):
        auth.supervisor(request)
        with store.Session() as db:
            lock_dispatch(db)
            d=db.get(store.Duty,did)
            if not d:raise HTTPException(404,'班次不存在')
            db.scalar(select(store.User).where(store.User.username==d.username).with_for_update())
            if d.username!=body.username or utc(d.starts_at)!=utc(body.starts_at) or utc(d.ends_at)!=utc(body.ends_at):raise HTTPException(422,'此操作只更新出勤和可用工時')
            if body.capacity_minutes>int((utc(d.ends_at)-utc(d.starts_at)).total_seconds()/60):raise HTTPException(422,'可用工時超過班次')
            d.attendance=body.attendance;d.capacity_minutes=body.capacity_minutes;d.note=body.note
            log(db,'attendance_updated',request,{'id':did,'attendance':body.attendance,'capacity_minutes':body.capacity_minutes});db.commit()
        return {'ok':True}

    @app.get('/api/dispatch')
    def dispatch(part:str='',at:datetime|None=None,minutes:int=60,ticket_id:str=''):
        if minutes<1 or minutes>100000:raise HTTPException(422,'需求工時範圍不符')
        if at is not None and at.tzinfo is None:raise HTTPException(422,'時間必須包含時區')
        required=[]
        if ticket_id:
            with store.Session() as db:
                if not db.get(store.Ticket,ticket_id):raise HTTPException(404,'工單不存在')
                w=db.get(store.Workflow,ticket_id);data=json.loads(w.payload) if w else {}
                required=data.get('required_qualifications',[]);minutes=data.get('remaining_minutes',minutes)
        return recommendations(part,at,required=required,minutes=minutes)

    @app.put('/api/tickets/{tid}/estimate')
    def estimate(tid:str,body:EstimateInput,request:Request):
        auth.supervisor(request)
        with store.Session() as db:
            lock_dispatch(db)
            ticket=db.get(store.Ticket,tid)
            if not ticket:raise HTTPException(404,'工單不存在')
            db.scalar(select(store.User).where(store.User.name==ticket.engineer).with_for_update())
            if ticket.status in ('已完成','待主管審核'):raise HTTPException(409,'此狀態不可修改剩餘工時')
            meta=db.get(store.Workflow,tid)
            if not meta:meta=store.Workflow(id=tid,payload='{}');db.add(meta)
            data=json.loads(meta.payload);data.update(remaining_minutes=body.remaining_minutes,required_qualifications=body.required_qualifications)
            data.setdefault('estimates',[]).append({**body.model_dump(),'actor':request.state.user['username'],'at':datetime.now(timezone.utc).isoformat()})
            meta.payload=json.dumps(data,ensure_ascii=False);log(db,'estimate_updated',request,{'ticket_id':tid,**body.model_dump()});db.commit()
        return {'remaining_minutes':body.remaining_minutes}

    @app.post('/api/tickets/{tid}/work-logs',status_code=201)
    def work_log(tid:str,body:WorkLogInput,request:Request):
        with store.Session() as db:
            ticket=db.get(store.Ticket,tid)
            if not ticket:raise HTTPException(404,'工單不存在')
            auth.assigned(request,ticket)
            if ticket.status!='維修中':raise HTTPException(409,'開始維修後才能登錄工時')
            row=store.WorkLog(id='LOG-'+uuid.uuid4().hex,ticket_id=tid,username=request.state.user['username'],**body.model_dump())
            db.add(row);log(db,'work_logged',request,{'id':row.id,'ticket_id':tid,**body.model_dump()});db.commit()
        return {'id':row.id,'minutes':row.minutes,'notice':'實際工時不自動扣除剩餘估時，請主管更新估時'}

    @app.get('/api/tickets/{tid}/work-logs')
    def work_logs(tid:str):
        with store.Session() as db:
            if not db.get(store.Ticket,tid):raise HTTPException(404,'工單不存在')
            rows=db.scalars(select(store.WorkLog).where(store.WorkLog.ticket_id==tid)).all()
            return {'total_minutes':sum(r.minutes for r in rows),'entries':[{'id':r.id,'username':r.username,'minutes':r.minutes,'note':r.note,'at':utc(r.created_at).isoformat()} for r in rows]}
