import json
import time
import uuid
import hashlib
import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Literal
import joblib
import numpy as np
import httpx
from fastapi import FastAPI, HTTPException, Header, Query, Request
from fastapi.responses import FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from . import store
from .ml import features, WINDOW, FEATURE_NAMES, LABELS
from .copilot import analyze
from .knowledge import DOCUMENTS, retrieve
from . import operations, chat, auth, evidence, maintenance_ai, config, workforce, repair_flow, equipment_templates, machine_scan
from . import knowledge_graph

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts'
model=None
report=None
replay=[]
MACHINES=['CNC-01','CNC-02','CNC-03','CNC-04','CNC-05','CNC-06','CNC-07','CNC-08','CNC-09']
ENGINEERS=['待指派','Amy Chen','Alex Lin','Bob Wang']

@asynccontextmanager
async def lifespan(app):
    global model,report,replay
    config.validate()
    store.init()
    with store.Session() as db:
        latest=db.scalar(select(store.SchemaVersion.version).order_by(store.SchemaVersion.version.desc()))
        if latest and latest>1:raise RuntimeError('Database schema is newer than this application')
        if not latest:db.add(store.SchemaVersion(version=1));db.commit()
        if not config.demo():
            if db.scalar(select(store.Audit).where(store.Audit.kind.in_(['asset_demo_seed_v1','demo_login']))):
                raise RuntimeError('Demo database cannot be used in production; use a separate empty database')
    operations.seed()
    auth.seed(operations.PEOPLE)
    if config.demo() and (ART/'bearing-model.joblib').exists():
        model=joblib.load(ART/'bearing-model.joblib')
        report=json.loads((ART/'model-report.json').read_text(encoding='utf-8'))
        replay=json.loads((ART/'replay.json').read_text(encoding='utf-8'))
    yield

app=FastAPI(title='PredictFix AI',version='0.2.0',lifespan=lifespan)

@app.exception_handler(RequestValidationError)
async def safe_validation_error(request:Request, exc:RequestValidationError):
    # FastAPI's default errors echo input, including passwords or entire malformed bodies.
    # Keep field locations and error types, but never serialize input, context or body.
    errors=[{'loc':e['loc'], 'type':e['type'], 'msg':'輸入格式或內容不符合要求'}
            for e in exc.errors()]
    return JSONResponse(status_code=422,content={'detail':errors})

auth.register(app)

# 只執行、套用本站的 js／css 檔：注入的 <script>、事件屬性與 style 屬性都不會生效
CSP=("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; "
     "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
# Swagger UI 需要 CDN 與 inline script；/docs 只在展示模式提供，因此只有這幾頁放寬
DOCS_CSP=("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
          "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; "
          "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
DOCS_PATHS=['/docs','/docs/oauth2-redirect','/redoc']
# 正式模式不需登入就能看到完整 API 結構的文件頁也一併關閉
DEMO_ONLY_PATHS=['/api/replay','/api/predict','/api/model/report','/api/chat','/api/copilot','/api/documents','/demo-measurements.csv',
                 '/index.html','/index.js','/index.css','/dynamic-styles.js','/roles.css','/factory.js','/live.js','/management.js',
                 '/mobile.html','/app.css','/app.js','/openapi.json',*DOCS_PATHS]

@app.middleware('http')
async def operational_boundary(request:Request,call_next):
    from fastapi.responses import JSONResponse
    if not config.demo() and request.url.path in DEMO_ONLY_PATHS:
        return JSONResponse({'detail':'展示功能未在正式環境啟用；維修 AI 請使用 /api/assist'},status_code=404)
    response=await call_next(request)
    response.headers['Content-Security-Policy']=DOCS_CSP if request.url.path in DOCS_PATHS else CSP
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='DENY'
    return response

@app.get('/healthz')
def readiness():
    from sqlalchemy import text
    with store.Session() as db:db.execute(text('SELECT 1'))
    return {'status':'ok','mode':'demo' if config.demo() else 'production','schema':1}

def audit(kind, payload, request_id=None):
    request_id=request_id or str(uuid.uuid4())
    with store.Session() as session:
        session.add(store.Audit(kind=kind,request_id=request_id,payload=json.dumps(payload,ensure_ascii=False)))
        session.commit()
    return request_id

@app.get('/api/health')
async def health():
    from . import openai_runtime
    if openai_runtime.configured():
        return {'status':'ok','database':store.engine.dialect.name,'sensor_model_ready':model is not None,
                'llm':{'configured':True,'model':openai_runtime.settings()['model'],'provider':'openai',
                       'available':False,'availability':'not_probed_by_health'},
                'retrieval':'keyword_and_optional_openai_embeddings','app_mode':'demo' if config.demo() else 'production',
                'component_health':'simulated' if config.demo() else 'not_connected','openai_budget':openai_runtime.budget_status()}
    provider=os.getenv('LLM_PROVIDER','ollama')
    model_name=os.getenv('LOCAL_LLM_MODEL') if provider=='llamacpp' else os.getenv('OLLAMA_MODEL')
    llm={'configured':bool(model_name), 'model':model_name, 'provider':provider, 'available':False}
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            if provider=='llamacpp':
                body=(await client.get(os.getenv('LLM_URL','http://127.0.0.1:8081')+'/health')).json()
                llm['available']=body.get('status')=='ok'
            else:
                body=(await client.get(os.getenv('OLLAMA_URL','http://127.0.0.1:11434')+'/api/tags')).json()
                llm['available']=any(m['name']==llm['model'] for m in body.get('models',[]))
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    return {'status':'ok', 'database':store.engine.dialect.name, 'sensor_model_ready':model is not None,
            'llm':llm, 'documents':'synthetic_and_imported_manuals_with_reviewed_cases',
            'retrieval':'tfidf_bm25_fusion', 'component_health':'simulated' if config.demo() else 'not_connected',
            'app_mode':'demo' if config.demo() else 'production'}

@app.get('/api/openai/budget')
def openai_budget(request:Request):
    auth.supervisor(request)
    from . import openai_runtime
    return {'configured':openai_runtime.configured(),'model':openai_runtime.settings()['model'],
            **openai_runtime.budget_status()}

@app.get('/api/model/report')
def model_report():
    if report is None:
        raise HTTPException(503,'模型尚未訓練')
    return report

@app.get('/api/replay')
def replay_list():
    return [{k:v for k,v in s.items() if k!='signal'} for s in replay]

class PredictInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    machine: str='CNC-03'
    sample_id: str=Field(min_length=1,max_length=100)

@app.post('/api/predict')
def predict(body:PredictInput):
    operations.active_machine(body.machine)
    if model is None:
        raise HTTPException(503,'模型尚未訓練')
    sample=next((s for s in replay if s['sample_id']==body.sample_id),None)
    if sample is None:
        raise HTTPException(404,'回放資料不存在')
    vector=features(sample['signal'])
    start=time.perf_counter()
    scores=model.predict_proba([vector])[0]
    label=str(model.classes_[int(np.argmax(scores))])
    elapsed=round((time.perf_counter()-start)*1000,2)
    signal_hash=hashlib.sha256(np.asarray(sample['signal'],dtype=np.float64).tobytes()).hexdigest()
    result={'machine':body.machine, 'sample_id':body.sample_id, 'prediction':label,
            'prediction_label':LABELS[label], 'probabilities':{str(c):round(float(p),6) for c,p in zip(model.classes_,scores)},
            'expected':sample['expected'], 'model_version':report['model_version'],
            'elapsed_ms':elapsed, 'input_sha256':signal_hash,
            'features':dict(zip(FEATURE_NAMES,vector)), 'source':'CWRU lab replay, NOT live CNC measurements',
            'limits':'已知故障類型分類；無正常類別，不是健康度、嚴重度、壽命或未來故障機率。',
            'signal_preview':sample['signal'][::8]}
    result['request_id']=audit('prediction',result)
    return result

class TicketInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    machine: str
    issue: str=Field(min_length=1,max_length=160)
    engineer: str='待指派'
    @field_validator('issue')
    @classmethod
    def nonempty(cls,value):
        if not value.strip():
            raise ValueError('異常描述不可空白')
        return value.strip()

@app.get('/api/tickets')
def list_tickets(limit:int|None=Query(default=None,ge=1,le=1000),offset:int=Query(default=0,ge=0)):
    # 未指定 limit 時維持回傳全部，現有前端不受影響；加上 id 當排序依據，分頁結果才穩定
    statement=(select(store.Ticket,store.Workflow).outerjoin(store.Workflow,store.Workflow.id==store.Ticket.id)
               .order_by(store.Ticket.created_at.desc(),store.Ticket.id).offset(offset).limit(limit))
    with store.Session() as session:
        return [store.ticket_dict(t,meta) for t,meta in session.execute(statement).all()]

@app.post('/api/tickets',status_code=201)
def create_ticket(body:TicketInput,request:Request,idempotency_key:str|None=Header(default=None,max_length=100)):
    if request.state.user['role']!='supervisor' and body.engineer not in ['待指派',request.state.user['name']]:raise HTTPException(403,'只有主管可以指派其他人員')
    operations.active_machine(body.machine)
    if body.engineer not in ['待指派']+[p['name'] for p in operations.people()]:raise HTTPException(422,'維修人員不存在')
    with store.Session() as session:
        if not config.demo():workforce.lock_dispatch(session,body.engineer)
        if idempotency_key:
            existing=session.scalar(select(store.Ticket).where(store.Ticket.request_key==idempotency_key))
            if existing:
                if any(getattr(existing,k)!=getattr(body,k) for k in ['machine','issue','engineer']):
                    raise HTTPException(409,'相同請求編號的工單內容不同')
                return store.ticket_dict(existing)
        if not config.demo():workforce.check_assignment(body.engineer)
        ticket=store.Ticket(id='WO-'+uuid.uuid4().hex[:12].upper(),request_key=idempotency_key,status='待指派' if body.engineer=='待指派' else '已指派',**body.model_dump())
        session.add(ticket)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409,'請求已提交，請重新讀取工單')
        result=store.ticket_dict(ticket)
    audit('ticket_created',result)
    return result

class CompleteInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    note:str=Field(min_length=3,max_length=1000)
    measurements:list[evidence.Measurement]=Field(default_factory=list,max_length=12)
    photo_ids:list[str]=Field(default_factory=list,max_length=6)
    @field_validator('note')
    @classmethod
    def nonempty(cls,value):
        if len(value.strip())<3:
            raise ValueError('請填寫修復結果')
        return value.strip()

@app.post('/api/tickets/{ticket_id}/complete')
def complete_ticket(ticket_id:str,body:CompleteInput,request:Request):
    with store.Session() as session:
        ticket=repair_flow.locked(session,store.Ticket,ticket_id)
        auth.assigned(request,ticket)
        if ticket.status=='已完成':
            return store.ticket_dict(ticket)
        if ticket.status=='待主管審核':raise HTTPException(409,'已提交主管審核')
        if ticket.engineer=='待指派':raise HTTPException(409,'工單尚未指派')
        procedure=repair_flow.checklist_submission(session,ticket)
        proof=evidence.submission(session,ticket,body,request.state.user)
        if procedure:proof['procedure']=procedure
        ticket.status='待主管審核'
        ticket.completion_note=body.note
        meta=session.get(store.Workflow,ticket_id)
        if meta is None:meta=store.Workflow(id=ticket_id,payload='{}');session.add(meta)
        data=json.loads(meta.payload);data.setdefault('submissions',[]).append(proof);data.update(submitted_by=proof['submitted_by'],submitted_at=proof['submitted_at'],evidence=proof);meta.payload=json.dumps(data,ensure_ascii=False)
        session.commit()
        result=store.ticket_dict(ticket)
    audit('ticket_submitted',result)
    return result

@app.get('/api/engineers')
def recommend_engineers(request:Request,machine:str='CNC-03',part:str='主軸軸承'):
    auth.supervisor(request)
    operations.active_machine(machine)
    if not config.demo():return workforce.recommendations(part)
    output=[]
    for p in operations.people():
        if 'cases' not in p:continue
        match=any(w in part for w in p['skills'])
        skill=40 if match else 28
        history=round(30*(p['success']+1)/(p['cases']+2))
        availability=max(0,30-6*p['workload'])
        output.append({'name':p['name'],'score':skill+history+availability,'breakdown':{'skill':skill,'history':history,'availability':availability},'workload':p['workload'],'method':'transparent_weighted_rules','reasons':[p['specialty']+'專長；'+('符合' if match else '非主要專長，需確認')+'本零件需求。',f"展示履歷：{p['cases']} 筆案例，{p['success']} 筆成功修復。",f"正式未完成工單 {p['workload']} 筆；班別 {p['shift']}（示例），需確認當班可派工。"]})
    # 新建帳號沒有展示履歷，沿用出勤與容量規則，避免捏造案例成績。
    names={p['name'] for p in operations.PEOPLE}
    output.extend(p for p in workforce.recommendations(part) if p['name'] not in names)
    return sorted(output,key=lambda e:e['score'],reverse=True)

class CopilotInput(BaseModel):
    text:str=Field(min_length=1,max_length=2000)

@app.post('/api/copilot')
async def copilot(body:CopilotInput):
    if not body.text.strip():
        raise HTTPException(422,'請輸入問題')
    start=time.perf_counter()
    result=await analyze(body.text)
    result['elapsed_ms']=round((time.perf_counter()-start)*1000,2)
    result['request_id']=audit('copilot',{'input':body.text,**result})
    return result

@app.get('/api/documents')
def documents(q:str=''):
    return retrieve(q) if q else DOCUMENTS

@app.get('/api/audit')
def audit_list(request:Request):
    auth.supervisor(request)
    with store.Session() as session:
        return [{'id':t.id,'kind':t.kind,'request_id':t.request_id,'created_at':t.created_at.isoformat(),
                 'payload':json.loads(t.payload)} for t in session.scalars(select(store.Audit).order_by(store.Audit.id.desc()).limit(30)).all()]

evidence.register(app)
workforce.register(app)
operations.register(app)
chat.register(app)
maintenance_ai.register(app)
repair_flow.register(app)
equipment_templates.register(app)
machine_scan.register(app)
knowledge_graph.register(app)

# 外部工單介接保持獨立註冊，方便與其他第二波子系統依序整合。
from . import integrations
integrations.register(app)

from . import agent
agent.register(app)

STATIC={'':'index.html','index.html':'index.html','index.js':'index.js','index.css':'index.css','dynamic-styles.js':'dynamic-styles.js',
        'auth.css':'auth.css','roles.css':'roles.css',
        'factory.css':'factory.css','factory.js':'factory.js',
        'neon.css':'neon.css','live.css':'live.css','live.js':'live.js','management.js':'management.js','management.css':'management.css','auth.js':'auth.js','evidence.js':'evidence.js','demo-measurements.csv':'demo-measurements.csv',
        'knowledge.html':'knowledge.html','knowledge.js':'knowledge.js','knowledge.css':'knowledge.css',
        'console.html':'console.html','console.js':'console.js','console.css':'console.css','templates.js':'templates.js',
        'workflow.html':'workflow.html','workflow.js':'workflow.js','workflow.css':'workflow.css',
        'scan.html':'scan.html','scan.js':'scan.js','scan.css':'scan.css',
        'graph.html':'graph.html','graph.js':'graph.js','graph.css':'graph.css'}
STATIC.update({'mobile.html':'sites/predictfix-mobile/dist/index.html',
               'app.css':'sites/predictfix-mobile/dist/app.css',
               'app.js':'sites/predictfix-mobile/dist/app.js'})
STATIC.update({name:name for name in ['integrations.html','integrations.js','integrations.css']})
STATIC.update({name:name for name in ['agent-widget.js','agent-widget.css']})
@app.get('/')
def index():
    return FileResponse(ROOT/('index.html' if config.demo() else 'console.html'),headers={'Cache-Control':'no-store'})

@app.get('/{filename}')
def static(filename:str):
    if filename not in STATIC:
        raise HTTPException(404)
    return FileResponse(ROOT/STATIC[filename],headers={'Cache-Control':'no-store'})
