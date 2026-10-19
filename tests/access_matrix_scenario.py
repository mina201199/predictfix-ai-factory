"""權限矩陣：每支路由都以未登入、工程師、主管實際呼叫；有資料歸屬的路由再加非指派工程師。"""
import inspect
import itertools
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

# 僅供此隔離矩陣子程序使用的假金鑰，不會成為正式來源預設值。
os.environ['INTEGRATION_SOURCES']=json.dumps({'matrix':{'keys':{'fixture':'ISOLATED-MATRIX-FAKE-INTEGRATION-SECRET'}}})

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
import backend.app as main
from backend import auth, maintenance_ai as ai, repair_flow, store
from backend.integration_models import ExternalOrder, MachineMapping, Outbox

PASSWORD=os.environ['BOOTSTRAP_PASSWORD']
MODEL='MATRIX-ATC'
MACHINE='MX-01'
ANON,ENG,OTHER,SUP='anon','engineer','other_engineer','supervisor'
# ENG 是工單負責人；OTHER 用來驗證「同角色但不是負責人」會被擋
# 展示模式已預建這些帳號，正式模式由 fixtures 建立同名帳號，兩種模式的身分才一致
USERS={ENG:('amy','Amy Chen'),OTHER:('alex','Alex Lin'),SUP:('supervisor','')}
# 主管派工的對象；正式模式要有當班出勤才能被指派，因此在 fixtures 另外排班
TARGET=('grace','Grace Huang')
OK,LOGIN,DENY,HIDDEN='2xx','401','403','404'

PUBLIC={ANON:OK,ENG:OK,SUP:OK}
SIGNED_IN={ANON:LOGIN,ENG:OK,SUP:OK}
SHARED={ANON:LOGIN,ENG:OK,OTHER:OK,SUP:OK}
SUPERVISOR={ANON:LOGIN,ENG:DENY,SUP:OK}
ASSIGNED={ANON:LOGIN,ENG:OK,OTHER:DENY,SUP:DENY}
ASSIGNED_OR_SUPERVISOR={ANON:LOGIN,ENG:OK,OTHER:DENY,SUP:OK}

STEPS=[{'label':'核對異常項目','kind':'inspect','criterion':'記錄檢查結果'},
       {'label':'復測驗收項目','kind':'verify','criterion':'記錄復測結果'}]
REPORT={'machine':MACHINE,'symptoms':'換刀卡住矩陣測試'}
TICKET={'machine':MACHINE,'issue':'矩陣測試報修'}
TEMPLATE={'name':'矩陣設備模板','asset_type':'CNC 加工中心','kind':'mill','parts':['主軸軸承'],
          'measurements':[],'steps':STEPS,'description':''}
MANUAL={'title':'矩陣測試換刀手冊','version':'1','machine_model':MODEL,'controller':'','component':'刀庫',
        'content':'## 換刀排查\n\n'+('換刀卡住時，記錄刀位、警報與發生條件，核對刀具資料。\n'*20),
        'is_synthetic':False,'source_label':'隔離測試原創資料','rights_confirmed':True}
FIELDS={'title':'矩陣測試案例','machine_model':MODEL,'component':'刀庫','symptoms':'換刀卡住',
        'conditions':'特定刀位','findings':'刀具資料不一致','cause_status':'unknown','root_cause':'尚未確認',
        'actions':'核對刀具資料','verification':'保存復測紀錄','is_synthetic':False}
FIXTURE={}
DAYS=itertools.count(1)


def uid(prefix):
  return prefix+uuid.uuid4().hex[:12]


def add(*rows):
  with store.Session() as db:
    db.add_all(rows)
    db.commit()


def pngBytes():
  buffer=BytesIO()
  Image.new('RGB',(4,4),'white').save(buffer,'PNG')
  return buffer.getvalue()


PNG=pngBytes()


def ticket(status='已指派',workflow=None):
  tid=uid('WO-MX-')
  engineer='待指派' if status=='待指派' else USERS[ENG][1]
  rows=[store.Ticket(id=tid,machine=MACHINE,issue='矩陣測試工單',engineer=engineer,status=status)]
  if workflow is not None:
    rows.append(store.Workflow(id=tid,payload=json.dumps(workflow,ensure_ascii=False)))
  add(*rows)
  return tid


def procedureTicket():
  steps=[{**s,'id':'STEP-'+s['kind'],'source_chunk_id':'','source_hash':'','source':None,'origin':'supervisor_authored'} for s in STEPS]
  return ticket(workflow={'procedure':{'revision':1,'machine_model':MODEL,'approved_by':'supervisor',
                                       'approval_note':'矩陣核准','steps':steps}})


def photo(tid):
  pid=uid('PHOTO-MX-')
  add(store.Evidence(id=pid,ticket_id=tid,uploader=USERS[ENG][0],filename='matrix.png',
                     media_type='image/png',sha256='0'*64,content=PNG))
  return pid


def case(status='draft'):
  cid=uid('CASE-MX-')
  data={'fields':FIELDS,'source_snapshot':{'ticket':{'completion_note':'核對刀具資料後復測正常'},'workflow':{}},
        'source_sha256':'fixture','history':[],'created_by':'supervisor',
        'published_by':'supervisor','published_at':'2026-10-16T00:00:00+00:00'}
  add(store.RepairCase(id=cid,ticket_id=uid('WO-CASE-'),status=status,payload=json.dumps(data,ensure_ascii=False)))
  return cid


def manual(active=True):
  mid=uid('MAN-MX-')
  doc={**FIXTURE['manual'],'id':mid,'title':'矩陣手冊 '+mid,'source_url':'/api/knowledge/manuals/'+mid}
  add(store.KnowledgeDocument(id=mid,active=int(active),payload=json.dumps(doc,ensure_ascii=False)))
  return mid


def machine(active=True):
  mid=uid('MX-')
  with store.Session() as db:
    payload=json.loads(db.get(store.Machine,MACHINE).payload)
  add(store.Machine(id=mid,payload=json.dumps({**payload,'id':mid},ensure_ascii=False),active=int(active)))
  return mid


def template():
  tid=uid('TPL-MX-')
  add(store.EquipmentTemplate(id=tid,revision=1,payload=json.dumps(TEMPLATE,ensure_ascii=False)))
  return tid


def plan():
  pid=uid('PM-MX-')
  payload={'machine':MACHINE,'title':'矩陣保養計畫','interval_days':30,'next_due':repair_flow.today().isoformat(),
           'machine_model':MODEL,'approval_note':'矩陣核准','steps':[{**s,'source_chunk_id':'','source_hash':''} for s in STEPS],
           'active':True,'open_ticket':None,'history':[],'created_by':'supervisor'}
  add(store.MaintenancePlan(id=pid,payload=json.dumps(payload,ensure_ascii=False)))
  return pid


def item():
  iid=uid('PART-MX-')
  add(store.StockItem(id=iid,name='矩陣備品',unit='個',quantity=100,minimum=0))
  return iid


def account(active=False):
  # 帳號管理路由會停用帳號、撤銷 session，所以用一次性帳號；預設停用，才不會混進派工與推薦名單
  username='mx'+uuid.uuid4().hex[:10]
  add(store.User(username=username,name='矩陣暫存'+username,role='engineer',password_hash='00:00',active=int(active)))
  return username


def dutyBody(username):
  # 每個班次錯開一天，同一位工程師多次排班也不會撞到重疊檢查
  start=datetime.now(timezone.utc).replace(microsecond=0)+timedelta(days=next(DAYS))
  return {'username':username,'starts_at':start.isoformat(),'ends_at':(start+timedelta(hours=8)).isoformat(),
          'attendance':'scheduled','capacity_minutes':60,'note':''}


def attendanceRequest(role):
  body=dutyBody(TARGET[0])
  did=uid('DUTY-MX-')
  add(store.Duty(id=did,username=body['username'],starts_at=datetime.fromisoformat(body['starts_at']),
                 ends_at=datetime.fromisoformat(body['ends_at']),attendance='scheduled',capacity_minutes=60,note=''))
  return {'url':f'/api/duties/{did}/attendance','json':{**body,'attendance':'present'}}


def freeTarget():
  # 正式模式派工會檢查未估時案件與剩餘工時；每次指派前結掉上一筆，結果才不受執行順序影響
  with store.Session() as db:
    for t in db.scalars(select(store.Ticket).where(store.Ticket.engineer==TARGET[1],store.Ticket.status!='已完成')).all():
      t.status='已完成'
    db.commit()


def assignTarget(role):
  freeTarget()
  return {'url':f'/api/tickets/{ticket("待指派")}/assign','json':{'engineer':TARGET[1]}}


def createForTarget(role):
  freeTarget()
  return {'json':{**TICKET,'engineer':TARGET[1]}}


def photoScope(role,response):
  ids={p['id'] for p in response.json()}
  if role==OTHER:
    return ids=={FIXTURE['submittedPhoto']}
  return ids=={FIXTURE['submittedPhoto'],FIXTURE['unsubmittedPhoto']}


def manualScope(role,response):
  ids={d['id'] for d in response.json()}
  return FIXTURE['manual']['id'] in ids and (FIXTURE['withdrawn'] in ids)==(role==SUP)


def caseScope(role,response):
  statuses={c['status'] for c in response.json()}
  return 'draft' in statuses if role==SUP else statuses=={'published'}


def row(method,path,expect,request=None,**options):
  return {'method':method,'path':path,'expect':expect,'request':request or (lambda role:{}),**options}


def stockRequest(body):
  return lambda role:{'url':f'/api/stock/{item()}/movements','json':body(),'headers':{'Idempotency-Key':uid('matrix-')}}


def recommendationScope(role,response):
  person=next((p for p in response.json() if p['name']=='Matrix New Engineer'),None)
  return bool(person and person['method']=='attendance_capacity_rules'
              and person['attendance']=='no_schedule' and not person['eligible']
              and 'history' not in person['breakdown'])


def graphBody():
  mid=manual()
  source=next(chunk for chunk in ai.buildCorpus() if chunk['id']==mid)
  return {'sourceChunkId':source['chunk_id'],'machineModel':MODEL,
    'head':{'kind':'symptom','label':'換刀卡住'},
    'tail':{'kind':'inspect_step','label':'核對刀具資料'},
    'relation':'inspect','quote':source['text']}


def graphReview(role):
  from backend.knowledge_graph import CandidateInput, createCandidate
  body=graphBody()
  with store.Session() as db:
    relation,_=createCandidate(db,CandidateInput(**body),'supervisor')
    relationId=relation.id
    revision=relation.revision
    db.commit()
  return {'url':f'/api/graph/relations/{relationId}/review',
    'json':{'revision':revision,'action':'approve','note':'矩陣來源核對'}}


def integrationResolve(role):
  payload={'externalId':uid('EXT-'),'eventId':uid('EVT-'),'version':1,'machineCode':'MX-EXT',
           'alarm':'','symptoms':'矩陣介接異常','occurredAt':'2026-10-19T00:00:00+00:00'}
  with store.Session() as db:
    mapping=db.scalar(select(MachineMapping).where(MachineMapping.source=='matrix',MachineMapping.machineCode=='MX-EXT'))
    if not mapping:db.add(MachineMapping(source='matrix',machineCode='MX-EXT',machineId=MACHINE))
    order=ExternalOrder(source='matrix',externalId=payload['externalId'],version=1,machineCode='MX-EXT',
                        payload=json.dumps(payload),reason='unknown_machine_code')
    db.add(order);db.commit()
    return {'url':f'/api/integrations/orders/{order.id}/resolve'}


def integrationRetry(role):
  with store.Session() as db:
    event=Outbox(eventId=uid('OUT-MX-'),source='matrix',ticketId=uid('WO-'),payload='{}',state='dead',attempts=5)
    db.add(event);db.commit()
    return {'url':f'/api/integrations/outbox/{event.id}/retry'}


MATRIX=[
  # 公開頁面與登入
  row('GET','/healthz',PUBLIC),
  row('GET','/',PUBLIC),
  row('GET','/{filename}',PUBLIC,lambda role:{'url':'/console.js'},variant='正式頁面檔案'),
  row('GET','/{filename}',PUBLIC,lambda role:{'url':'/index.js'},variant='展示頁面檔案',demoOnly=True),
  row('GET','/openapi.json',PUBLIC,demoOnly=True),
  row('GET','/docs',PUBLIC,demoOnly=True),
  row('GET','/docs/oauth2-redirect',PUBLIC,demoOnly=True),
  row('GET','/redoc',PUBLIC,demoOnly=True),
  row('GET','/api/auth/config',PUBLIC),
  row('POST','/api/auth/login',PUBLIC,lambda role:{'json':{'username':USERS[ENG if role==ANON else role][0],'password':PASSWORD}}),
  # 快速登入不在 DEMO_ONLY_PATHS，正式模式靠函式內檢查回 403
  row('POST','/api/auth/demo',PUBLIC,lambda role:{'json':{'role':'engineer','username':'bob'}},
      production={ANON:DENY,ENG:DENY,SUP:DENY}),
  row('GET','/api/auth/me',SIGNED_IN),
  row('POST','/api/auth/logout',SIGNED_IN),
  row('PUT','/api/auth/password',SIGNED_IN,lambda role:{'json':{'current_password':PASSWORD,'password':PASSWORD}}),
  row('GET','/api/health',SIGNED_IN),
  row('GET','/api/openai/budget',SUPERVISOR),
  row('GET','/api/audit',SUPERVISOR),
  # 展示專用
  row('GET','/api/model/report',SIGNED_IN,demoOnly=True),
  row('GET','/api/replay',SIGNED_IN,demoOnly=True),
  row('POST','/api/predict',SIGNED_IN,lambda role:{'json':{'machine':MACHINE,'sample_id':(main.replay or [{'sample_id':'none'}])[0]['sample_id']}},demoOnly=True),
  row('POST','/api/copilot',SIGNED_IN,lambda role:{'json':{'text':'MX-01 主軸異音'}},demoOnly=True,ai=True),
  row('POST','/api/chat',SIGNED_IN,lambda role:{'json':{'text':'有哪些未結案工單'}},demoOnly=True,ai=True),
  row('GET','/api/documents',SIGNED_IN,demoOnly=True),
  # 工單
  row('GET','/api/tickets',SHARED),
  row('POST','/api/tickets',SIGNED_IN,lambda role:{'json':TICKET},variant='待指派'),
  row('POST','/api/tickets',SUPERVISOR,createForTarget,variant='指派給其他工程師'),
  row('PATCH','/api/tickets/{tid}/assign',SUPERVISOR,assignTarget),
  row('POST','/api/tickets/{tid}/start',ASSIGNED,lambda role:{'url':f'/api/tickets/{ticket()}/start'}),
  row('PUT','/api/tickets/{tid}/report-context',ASSIGNED_OR_SUPERVISOR,lambda role:{'url':f'/api/tickets/{ticket()}/report-context','json':REPORT}),
  row('PUT','/api/tickets/{tid}/procedure',SUPERVISOR,lambda role:{'url':f'/api/tickets/{ticket()}/procedure',
      'json':{'revision':0,'machine_model':MODEL,'approval_note':'矩陣核准清單','steps':STEPS}}),
  row('PUT','/api/tickets/{tid}/procedure/results',ASSIGNED,lambda role:{'url':f'/api/tickets/{procedureTicket()}/procedure/results',
      'json':{'revision':1,'results':[{'step_id':'STEP-inspect','outcome':'pass','note':'檢查結果正常'}]}}),
  row('PUT','/api/tickets/{tid}/estimate',SUPERVISOR,lambda role:{'url':f'/api/tickets/{ticket()}/estimate',
      'json':{'remaining_minutes':60,'required_qualifications':[],'note':'矩陣估時'}}),
  row('POST','/api/tickets/{tid}/work-logs',ASSIGNED,lambda role:{'url':f'/api/tickets/{ticket("維修中")}/work-logs','json':{'minutes':30,'note':'矩陣工時'}}),
  row('GET','/api/tickets/{tid}/work-logs',SHARED,lambda role:{'url':f'/api/tickets/{FIXTURE["photoTicket"]}/work-logs'}),
  row('POST','/api/tickets/{ticket_id}/complete',ASSIGNED,lambda role:{'url':f'/api/tickets/{ticket("維修中")}/complete','json':{'note':'矩陣測試完成紀錄'}}),
  # 「工程師」是這張工單的負責人：執行者不能審核自己的工作
  row('POST','/api/tickets/{tid}/review',SUPERVISOR,lambda role:{'url':f'/api/tickets/{ticket("待主管審核")}/review',
      'json':{'decision':'approve','note':'矩陣審核通過'}}),
  row('POST','/api/tickets/{tid}/review',SUPERVISOR,lambda role:{'url':f'/api/tickets/{ticket("待主管審核")}/review',
      'json':{'reviewer':'管理員','decision':'approve','note':'偽造主管審核'},'headers':{'X-Demo-Role':'supervisor'}},
      variant='偽造主管標頭與審核人'),
  # 照片與量測
  row('POST','/api/tickets/{tid}/photos',ASSIGNED,lambda role:{'url':f'/api/tickets/{ticket()}/photos','content':PNG,'params':{'filename':'matrix.png'}}),
  row('POST','/api/tickets/{tid}/measurements/import',ASSIGNED,lambda role:{'url':f'/api/tickets/{ticket()}/measurements/import',
      'content':'metric,before,after,conditions\ntemperature,80,60,idle\n'.encode()}),
  row('GET','/api/tickets/{tid}/photos',SHARED,lambda role:{'url':f'/api/tickets/{FIXTURE["photoTicket"]}/photos'},check=photoScope),
  row('GET','/api/evidence/{eid}',ASSIGNED_OR_SUPERVISOR,lambda role:{'url':'/api/evidence/'+FIXTURE['unsubmittedPhoto']},variant='未提交照片'),
  row('GET','/api/evidence/{eid}',SHARED,lambda role:{'url':'/api/evidence/'+FIXTURE['submittedPhoto']},variant='已提交照片'),
  # 設備與模板
  row('GET','/api/machines',SIGNED_IN),
  row('POST','/api/machines',SUPERVISOR,lambda role:{'json':{'id':uid('MX-'),'name':'矩陣新增設備','kind':'mill','machine_model':MODEL}}),
  row('PATCH','/api/machines/{mid}/asset',SUPERVISOR,lambda role:{'url':f'/api/machines/{machine()}/asset','json':{}}),
  row('DELETE','/api/machines/{mid}',SUPERVISOR,lambda role:{'url':f'/api/machines/{machine()}'}),
  row('POST','/api/machines/{mid}/restore',SUPERVISOR,lambda role:{'url':f'/api/machines/{machine(active=False)}/restore'}),
  row('GET','/api/equipment-templates',SIGNED_IN),
  row('POST','/api/equipment-templates',SUPERVISOR,lambda role:{'json':TEMPLATE}),
  row('PUT','/api/equipment-templates/{tid}',SUPERVISOR,lambda role:{'url':f'/api/equipment-templates/{template()}','json':{**TEMPLATE,'revision':1}}),
  # 人員、出勤與派工
  row('GET','/api/personnel',SUPERVISOR),
  row('GET','/api/engineers',SUPERVISOR,lambda role:{'params':{'machine':MACHINE,'part':'主軸軸承'}},check=recommendationScope),
  row('GET','/api/dispatch',SUPERVISOR),
  row('GET','/api/analytics',SIGNED_IN),
  row('GET','/api/duties',SUPERVISOR),
  row('POST','/api/duties',SUPERVISOR,lambda role:{'json':dutyBody(TARGET[0])}),
  row('PUT','/api/duties/{did}/attendance',SUPERVISOR,attendanceRequest),
  # 帳號管理
  row('GET','/api/admin/users',SUPERVISOR),
  # 以建立主管帳號測試：工程師自行開主管帳號就是提權
  row('POST','/api/admin/users',SUPERVISOR,lambda role:{'json':{'username':'mx'+uuid.uuid4().hex[:10],
      'name':'矩陣新帳號'+uuid.uuid4().hex[:6],'role':'supervisor','password':PASSWORD}}),
  row('PUT','/api/admin/users/{username}/profile',SUPERVISOR,lambda role:{'url':f'/api/admin/users/{account()}/profile',
      'json':{'specialty':'主軸','skills':['主軸'],'qualifications':[]}}),
  row('PUT','/api/admin/users/{username}/active',SUPERVISOR,lambda role:{'url':f'/api/admin/users/{account()}/active','json':{'active':False}}),
  row('PUT','/api/admin/users/{username}/password',SUPERVISOR,lambda role:{'url':f'/api/admin/users/{account()}/password','json':{'password':PASSWORD+'-reset'}}),
  # 知識庫與案例
  row('GET','/api/knowledge/manuals',SIGNED_IN,check=manualScope),
  row('POST','/api/knowledge/manuals',SUPERVISOR,lambda role:{'json':{**MANUAL,'title':'矩陣匯入手冊 '+uuid.uuid4().hex[:8]}}),
  row('GET','/api/knowledge/manuals/{mid}',SIGNED_IN,lambda role:{'url':'/api/knowledge/manuals/'+FIXTURE['manual']['id']},variant='有效手冊'),
  row('GET','/api/knowledge/manuals/{mid}',{ANON:LOGIN,ENG:HIDDEN,SUP:OK},lambda role:{'url':'/api/knowledge/manuals/'+FIXTURE['withdrawn']},variant='已撤回手冊'),
  row('POST','/api/knowledge/manuals/{mid}/withdraw',SUPERVISOR,lambda role:{'url':f'/api/knowledge/manuals/{manual()}/withdraw'}),
  row('GET','/api/knowledge/search',SIGNED_IN,lambda role:{'params':{'q':'換刀卡住'}}),
  row('POST','/api/assist',SIGNED_IN,lambda role:{'json':{'question':'換刀卡住要核對什麼','machine_model':MODEL}},ai=True),
  row('GET','/api/cases',SIGNED_IN,check=caseScope),
  row('GET','/api/cases/{cid}',SIGNED_IN,lambda role:{'url':'/api/cases/'+FIXTURE['published']},variant='已發布案例'),
  row('GET','/api/cases/{cid}',{ANON:LOGIN,ENG:HIDDEN,SUP:OK},lambda role:{'url':'/api/cases/'+FIXTURE['draft']},variant='草稿案例'),
  row('POST','/api/tickets/{tid}/case-draft',SUPERVISOR,lambda role:{'url':f'/api/tickets/{ticket("已完成")}/case-draft'}),
  row('PUT','/api/cases/{cid}',SUPERVISOR,lambda role:{'url':f'/api/cases/{case()}','json':{'revision':1,'fields':FIELDS}}),
  row('POST','/api/cases/{cid}/ai-suggestion',SUPERVISOR,lambda role:{'url':f'/api/cases/{case()}/ai-suggestion'},ai=True),
  row('POST','/api/cases/{cid}/publish',SUPERVISOR,lambda role:{'url':f'/api/cases/{case()}/publish','json':{'revision':1,'note':'矩陣發布審核'}}),
  row('POST','/api/cases/{cid}/withdraw',SUPERVISOR,lambda role:{'url':f'/api/cases/{case("published")}/withdraw','json':{'revision':1,'note':'矩陣撤回說明'}}),
  # 維修流程、保養與備品
  row('POST','/api/repair-flow/analyze',SIGNED_IN,lambda role:{'json':REPORT},ai=True),
  row('POST','/api/repair-flow/report',SIGNED_IN,lambda role:{'json':REPORT,'headers':{'Idempotency-Key':uid('matrix-')}}),
  row('GET','/api/maintenance-plans',SIGNED_IN),
  row('POST','/api/maintenance-plans',SUPERVISOR,lambda role:{'json':{'machine':MACHINE,'title':'矩陣保養計畫','interval_days':30,
      'next_due':repair_flow.today().isoformat(),'revision':0,'machine_model':MODEL,'approval_note':'矩陣核准','steps':STEPS}}),
  row('PUT','/api/maintenance-plans/{pid}/active',SUPERVISOR,lambda role:{'url':f'/api/maintenance-plans/{plan()}/active','json':{'active':False}}),
  row('POST','/api/maintenance-plans/{pid}/generate',SUPERVISOR,lambda role:{'url':f'/api/maintenance-plans/{plan()}/generate'}),
  row('GET','/api/stock',SIGNED_IN),
  row('POST','/api/stock',SUPERVISOR,lambda role:{'json':{'name':'矩陣備品','unit':'個','minimum':1}}),
  row('GET','/api/stock/movements',SIGNED_IN),
  row('POST','/api/stock/{iid}/movements',SUPERVISOR,stockRequest(lambda:{'kind':'receive','quantity':5,'note':'矩陣入庫'}),variant='入庫'),
  row('POST','/api/stock/{iid}/movements',ASSIGNED_OR_SUPERVISOR,stockRequest(lambda:{'kind':'issue','quantity':1,
      'ticket_id':ticket('維修中'),'note':'矩陣領料'}),variant='依工單領料'),
]

# 第二波外部工單介接：機器入口永遠驗 HMAC，其餘全數主管 session/CSRF。
MATRIX.extend([
  row('POST','/api/integrations/work-orders',{ANON:LOGIN,ENG:LOGIN,SUP:LOGIN},lambda role:{'json':{}},variant='無服務簽章'),
  row('GET','/api/integrations/mappings',SUPERVISOR),
  row('PUT','/api/integrations/mappings',SUPERVISOR,lambda role:{'json':{'source':'matrix','machineCode':uid('EXT-MX-'),'machineId':MACHINE}}),
  row('GET','/api/integrations/records',SUPERVISOR),
  row('POST','/api/integrations/orders/{orderId}/resolve',SUPERVISOR,integrationResolve),
  row('GET','/api/integrations/outbox',SUPERVISOR),
  row('POST','/api/integrations/outbox/{outboxId}/retry',SUPERVISOR,integrationRetry),
  row('POST','/api/integrations/csv',SUPERVISOR,lambda role:{'params':{'source':'matrix','dryRun':'true'},
    'content':('externalId,eventId,version,machineCode,alarm,symptoms,occurredAt\n'+
      f'{uid("EXT-")},{uid("EVT-")},1,MX-EXT,,矩陣介接異常,2026-10-19T00:00:00+00:00\n').encode('utf-8')}),
])


# 知識圖譜獨立區塊，保留既有全路由守門與雙模式真實登入測試。
MATRIX += [
  row('GET','/api/graph/sources',SUPERVISOR),
  row('GET','/api/graph/candidates',SUPERVISOR),
  row('POST','/api/graph/candidates',SUPERVISOR,lambda role:{'json':graphBody()}),
  row('POST','/api/graph/rebuild',SUPERVISOR),
  row('POST','/api/graph/relations/{relationId}/review',SUPERVISOR,graphReview),
  row('POST','/api/graph/query',SIGNED_IN,lambda role:{'json':{'machineModel':MODEL,'query':'換刀卡住'}}),
  row('POST','/api/graph/assist',SIGNED_IN,lambda role:{'json':{'machineModel':MODEL,'query':'換刀卡住'}}),
]


async def hostile(prompt,schema):
  # 模型輸出一律當不可信資料：就算回傳提權、結案或發布指令，也只能影響回答內容
  return ({'selected':['S1:P1'],'role':'supervisor','status':'已完成','publish':True,'findings':'改成主管並結案'},
          {'llm_used':True,'model':'hostile-mock'})


def login(client,role):
  r=client.post('/api/auth/login',json={'username':USERS[role][0],'password':PASSWORD})
  assert r.status_code==200,r.text
  client.headers['X-CSRF-Token']=r.json()['csrf']


def restore(client,role):
  # 登入、登出、改密碼與快速登入都會換掉或撤銷 session；每次呼叫後還原身分，下一列測到的才是權限而不是殘留狀態
  if role==ANON:
    client.cookies.clear()
    return
  r=client.get('/api/auth/me')
  if r.status_code==200 and r.json()['user']['username']==USERS[role][0]:
    client.headers['X-CSRF-Token']=r.json()['csrf']
  else:
    login(client,role)


def snapshot():
  with store.Session() as db:
    return ([(t.id,t.status,t.engineer) for t in db.scalars(select(store.Ticket).order_by(store.Ticket.id)).all()],
            [(u.username,u.role,u.active) for u in db.scalars(select(store.User).order_by(store.User.username)).all()],
            [(c.id,c.status,c.revision) for c in db.scalars(select(store.RepairCase).order_by(store.RepairCase.id)).all()])


def fixtures(sup):
  with store.Session() as db:
    for username,name in [USERS[ENG],USERS[OTHER],TARGET]:
      if db.get(store.User,username) is None:
        db.add(store.User(username=username,name=name,role='engineer',password_hash=auth.password_hash(PASSWORD)))
    db.commit()
  now=datetime.now(timezone.utc).replace(microsecond=0)
  add(store.Duty(id=uid('DUTY-MX-'),username=TARGET[0],starts_at=now-timedelta(hours=1),ends_at=now+timedelta(hours=23),
                 attendance='present',capacity_minutes=1440,note='矩陣派工班'))
  login(sup,SUP)
  r=sup.post('/api/admin/users',json={'username':'matrix_new','name':'Matrix New Engineer','role':'engineer','password':PASSWORD})
  assert r.status_code==201,r.text
  r=sup.post('/api/machines',json={'id':MACHINE,'name':'矩陣測試機','kind':'mill','machine_model':MODEL})
  assert r.status_code==201,r.text
  r=sup.post('/api/knowledge/manuals',json=MANUAL)
  assert r.status_code==201,r.text
  FIXTURE['manual']=r.json()
  FIXTURE['withdrawn']=manual(active=False)
  FIXTURE['published']=case('published')
  FIXTURE['draft']=case('draft')
  tid=ticket(status='待主管審核')
  submitted,unsubmitted=photo(tid),photo(tid)
  add(store.Workflow(id=tid,payload=json.dumps({'submissions':[{'photos':[{'id':submitted}]}]})))
  FIXTURE.update(photoTicket=tid,submittedPhoto=submitted,unsubmittedPhoto=unsubmitted)


def expected(entry,mode):
  if mode=='production' and entry.get('demoOnly'):
    # 正式模式由最外層 middleware 直接回 404，連登入檢查都不會走到
    return {role:HIDDEN for role in entry['expect']}
  if mode=='production' and entry.get('production'):
    return entry['production']
  return entry['expect']


def statusClass(code):
  return OK if 200<=code<300 else str(code)


def coverage():
  listed={(e['method'],e['path']) for e in MATRIX}
  actual=set()
  gaps=[]
  for route in main.app.routes:
    endpoint=getattr(route,'endpoint',None)
    source=inspect.getsource(endpoint) if endpoint and endpoint.__module__.startswith('backend') else ''
    for method in sorted(getattr(route,'methods',None) or []):
      if method=='HEAD':continue
      actual.add((method,route.path))
      entries=[e for e in MATRIX if (e['method'],e['path'])==(method,route.path)]
      # 程式裡呼叫了 auth.supervisor／auth.assigned，矩陣就必須至少有一列真的測到被擋，避免只列路由卻沒驗證防線
      if 'auth.supervisor(' in source and not any(e['expect'].get(ENG)==DENY for e in entries):
        gaps.append(f'{method} {route.path}: 有 auth.supervisor 但沒有一列預期工程師 403')
      if 'auth.assigned(' in source and not any(e['expect'].get(OTHER)==DENY for e in entries):
        gaps.append(f'{method} {route.path}: 有 auth.assigned 但沒有一列預期非指派工程師 403')
  return {'unlisted':[' '.join(r) for r in sorted(actual-listed)],
          'stale':[' '.join(r) for r in sorted(listed-actual)],'gaps':gaps}


def run(mode):
  failures=[]
  checked=0
  with patch.object(ai,'generate_json',hostile),TestClient(main.app,raise_server_exceptions=False) as sup:
    clients={ANON:TestClient(main.app,raise_server_exceptions=False),ENG:TestClient(main.app,raise_server_exceptions=False),
             OTHER:TestClient(main.app,raise_server_exceptions=False),SUP:sup}
    fixtures(sup)
    login(clients[ENG],ENG)
    login(clients[OTHER],OTHER)
    for entry in MATRIX:
      for role,want in expected(entry,mode).items():
        request=entry['request'](role)
        url=request.pop('url',entry['path'])
        before=snapshot() if entry.get('ai') else None
        response=clients[role].request(entry['method'],url,**request)
        got=statusClass(response.status_code)
        problem=None
        if got!=want:
          problem='status'
        elif got==OK and entry.get('check') and not entry['check'](role,response):
          problem='scope'
        elif before is not None and snapshot()!=before:
          problem='ai_mutation'
        checked+=1
        if problem:
          failures.append({'route':f"{entry['method']} {entry['path']}",'variant':entry.get('variant',''),'role':role,
                           'problem':problem,'expected':want,'got':got,'detail':response.text[:200]})
        restore(clients[role],role)
  return {'mode':mode,'checked':checked,'failures':failures,**coverage()}


if __name__=='__main__':
  report=run(os.environ['APP_MODE'])
  print(json.dumps(report))
  if report['failures'] or report['unlisted'] or report['stale'] or report['gaps']:
    raise SystemExit(1)
