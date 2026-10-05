import os
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

@pytest.fixture(scope='module')
def client(tmp_path_factory):
    database=tmp_path_factory.mktemp('db')/'test.db'
    os.environ['BOOTSTRAP_PASSWORD']='TestOnly-Factory-12345'
    os.environ['DATABASE_URL']='sqlite:///'+str(database)
    os.environ.pop('OLLAMA_MODEL',None)
    from fastapi.testclient import TestClient
    from backend.app import app
    with TestClient(app) as client:
        yield client

def login(client,username='supervisor'):
    r=client.post('/api/auth/login',json={'username':username,'password':'TestOnly-Factory-12345'})
    assert r.status_code==200,r.text
    client.headers['X-CSRF-Token']=r.json()['csrf']

@pytest.fixture(autouse=True)
def authenticated(client):
    login(client)

def test_ticket_persistence_idempotency_and_completion(client):
    payload={'machine':'CNC-03','issue':'檢查主軸軸承','engineer':'Amy Chen'}
    first=client.post('/api/tickets',json=payload,headers={'Idempotency-Key':'test-request'})
    assert first.status_code==201
    again=client.post('/api/tickets',json=payload,headers={'Idempotency-Key':'test-request'})
    assert first.json()['id']==again.json()['id']
    assert len(client.get('/api/tickets').json())==1
    changed=client.post('/api/tickets',json={**payload,'issue':'不同内容'},headers={'Idempotency-Key':'test-request'})
    assert changed.status_code==409
    ticket_id=first.json()['id']
    assert client.post('/api/tickets/'+ticket_id+'/complete',json={'note':' '}).status_code==422
    login(client,'amy')
    done=client.post('/api/tickets/'+ticket_id+'/complete',json={'note':'檢查潤滑，量測結果恢復，確認結案'})
    assert done.json()['status']=='待主管審核'
    login(client)
    assert client.post('/api/tickets/'+ticket_id+'/review',json={'reviewer':'陳主管','decision':'approve','note':'復測紀錄確認通過'},headers={'X-Demo-Role':'supervisor'}).json()['status']=='已完成'
    assert client.get('/api/tickets').json()[0]['completion_note']==done.json()['completion_note']

def test_reject_invalid_machine_and_blank_issue(client):
    for payload in [{'machine':'CNC-99','issue':'測試'}, {'machine':'CNC-03','issue':'  '}]:
        assert client.post('/api/tickets',json=payload).status_code==422

def test_rule_workload_changes_rank(client):
    before=client.get('/api/engineers?part=主軸軸承').json()
    person=next(e for e in before if e['name']=='Amy Chen')
    client.post('/api/tickets',json={'machine':'CNC-03','issue':'檢查軸承','engineer':'Amy Chen'})
    after=client.get('/api/engineers?part=主軸軸承').json()
    now=next(e for e in after if e['name']=='Amy Chen')
    assert now['score']==person['score']-6
    assert now['workload']==person['workload']+1

def test_copilot_honestly_reports_no_llm(client):
    result=client.post('/api/copilot',json={'text':'CNC03 主軸震動，溫度92度 E102'}).json()
    assert result['llm_used'] is False
    assert result['extracted']['machine_id']=='CNC-03'
    assert result['extracted']['temperature_c']==92
    assert result['citations']
    ambiguous=client.post('/api/copilot',json={'text':'CNC01 和 CNC03 都有問題'}).json()
    assert ambiguous['needs_confirmation'] is True

def test_real_model_predictions_are_auditable(client):
    samples=client.get('/api/replay').json()
    assert samples, 'Run scripts/prepare_model.py first'
    result=client.post('/api/predict',json={'sample_id':samples[0]['sample_id']}).json()
    assert result['prediction'] in ['inner_race','ball','outer_race']
    assert abs(sum(result['probabilities'].values())-1)<.00001
    assert len(result['input_sha256'])==64
    audits=client.get('/api/audit').json()
    assert any(r['request_id']==result['request_id'] for r in audits)
    assert client.post('/api/predict',json={'sample_id':'missing'}).status_code==404

def test_static_route_does_not_expose_database(client):
    assert client.get('/predictfix.db').status_code==404
    assert client.get('/.env').status_code==404
    assert client.get('/').status_code==200

def test_added_demo_machine_workflow(client):
    created=client.post('/api/tickets',json={'machine':'CNC-09','issue':'新增機台螺桿巡檢','engineer':'Bob Wang'})
    assert created.status_code==201
    assert client.get('/api/engineers?machine=CNC-09&part=進給螺桿').status_code==200
    assert client.post('/api/copilot',json={'text':'CNC09 進給螺桿異音'}).json()['extracted']['machine_id']=='CNC-09'
    login(client,'bob')
    assert client.post('/api/tickets/'+created.json()['id']+'/complete',json={'note':'示例巡檢完成'}).status_code==200
    login(client)
    assert client.post('/api/tickets/'+created.json()['id']+'/review',json={'reviewer':'陳主管','decision':'approve','note':'確認檢核結果'},headers={'X-Demo-Role':'supervisor'}).status_code==200

def test_catalog_soft_delete_restore_and_assignment(client):
    initial=client.get('/api/machines').json()
    assert len(initial)>=18
    assert client.post('/api/machines',json={'id':'CNC-99','name':'測試加工中心','kind':'mill'}).status_code==201
    assert client.post('/api/machines',json={'id':'CNC-99','name':'重複編號','kind':'mill'}).status_code==409
    machine=next(m for m in client.get('/api/machines').json() if m['id']=='CNC-99')
    assert all(p[1] is None for p in machine['parts'])
    t=client.post('/api/tickets',json={'machine':'CNC-99','issue':'設備建檔巡檢'}).json()
    assert client.delete('/api/machines/CNC-99').status_code==409
    assert client.patch('/api/tickets/'+t['id']+'/assign',json={'engineer':'Grace Huang'}).status_code==200
    staff=client.get('/api/personnel').json()
    assert len(staff)==8
    assert next(p for p in staff if p['name']=='Grace Huang')['workload']==1
    login(client,'grace')
    client.post('/api/tickets/'+t['id']+'/complete',json={'note':'建檔巡檢完成'})
    login(client)
    client.post('/api/tickets/'+t['id']+'/review',json={'reviewer':'陳主管','decision':'approve','note':'確認建檔結果'},headers={'X-Demo-Role':'supervisor'})
    assert client.delete('/api/machines/CNC-99').status_code==200
    assert not any(m['id']=='CNC-99' for m in client.get('/api/machines').json())
    assert any(m['id']=='CNC-99' and not m['active'] for m in client.get('/api/machines?include_inactive=true').json())
    assert client.post('/api/tickets',json={'machine':'CNC-99','issue':'停用機台'}).status_code==422
    assert client.post('/api/machines/CNC-99/restore').status_code==200
    assert client.get('/api/analytics').json()['completed']>=1
    docs=client.get('/api/documents').json()
    assert len(docs)==30
    assert sum(d.get('source_type')=='synthetic_demo_manual' for d in docs)==4
    assert client.get('/api/documents?q=交班').json()

def test_chat_database_routes_and_context(client):
    r=client.post('/api/chat',json={'text':'現在有哪些機台要檢查？'}).json()
    assert r['route']=='database'
    assert r['llm_used'] is False
    assert r['sql'].startswith('SELECT')
    assert 'CNC-05' in r['machine_ids']
    assert all(row['health']<70 for row in r['rows'])
    r=client.post('/api/chat',json={'text':'它的工單有哪些？','history':[{'role':'user','content':'CNC-09 健康如何？'}]}).json()
    assert r['parameters']['machine']=='CNC-09'
    assert all(row['machine']=='CNC-09' for row in r['rows'])
    r=client.post('/api/chat',json={'text':'DROP TABLE tickets'}).json()
    assert r['sql'] is None
    assert client.get('/api/tickets').status_code==200
    assert client.post('/api/chat',json={'text':'你可以問什麼？'}).json()['route']=='help'


def test_chat_workload_query(client):
    r=client.post("/api/chat",json={"text":"誰的任務負荷最多？"}).json()
    assert r["query_kind"]=="workload"
    assert "GROUP BY engineer" in r["sql"]


def test_submission_requires_supervisor_review(client):
    t=client.post('/api/tickets',json={'machine':'CNC-03','issue':'主管審核測試','engineer':'Amy Chen'}).json()
    assert t['status']=='已指派'
    login(client,'amy')
    assert client.patch('/api/tickets/'+t['id']+'/assign',json={'engineer':'David Wu'},headers={'X-Demo-Role':'supervisor'}).status_code==403
    login(client)
    assert client.patch('/api/tickets/'+t['id']+'/assign',json={'engineer':'David Wu','reason':'調整當班專長'},headers={'X-Demo-Role':'supervisor'}).status_code==200
    login(client,'david')
    assert client.post('/api/tickets/'+t['id']+'/start').json()['status']=='維修中'
    assert client.post('/api/tickets/'+t['id']+'/complete',json={'note':'完成復測，結果正常'}).json()['status']=='待主管審核'
    review={'reviewer':'陳主管','decision':'reject','note':'請補充量測結果'}
    assert client.post('/api/tickets/'+t['id']+'/review',json=review).status_code==403
    login(client)
    assert client.post('/api/tickets/'+t['id']+'/review',json=review,headers={'X-Demo-Role':'supervisor'}).json()['status']=='退回重修'
    login(client,'david')
    client.post('/api/tickets/'+t['id']+'/complete',json={'note':'已补量測記錄，確認正常'})
    review.update(decision='approve',note='確認復測記錄，核准結案')
    login(client)
    r=client.post('/api/tickets/'+t['id']+'/review',json=review,headers={'X-Demo-Role':'supervisor'})
    assert r.json()['status']=='已完成'
    assert len(r.json()['workflow']['reviews'])==2
    assert client.patch('/api/tickets/'+t['id']+'/assign',json={'engineer':'Amy Chen','reason':'錯誤重新派工'}).status_code==409

def test_idle_people_and_lifecycle(client):
    r=client.post('/api/chat',json={'text':'誰沒有維修工單？'}).json()
    assert r['query_kind']=='idle_people'
    assert all(row['open_tasks']==0 for row in r['rows'])
    assert not any(row['engineer']=='Amy Chen' for row in r['rows'])
    assert r['intent_model']=='zh-maintenance-intent-v1'
    payload={'installed_on':'2020-01-01','responsible':'Amy Chen','part_dates':{'0':'2023-01-01'},'inspection_date':'2026-10-01','inspector':'Alex Lin','inspection_note':'冷卻與潤滑巡檢完成','next_inspection':'2026-11-01'}
    assert client.patch('/api/machines/CNC-03/asset',json=payload).status_code==200
    m=next(m for m in client.get('/api/machines').json() if m['id']=='CNC-03')
    assert m['asset']['inspections'][-1]['inspector']=='陳主管'
    assert client.patch('/api/machines/CNC-03/asset',json={**payload,'installed_on':'2099-01-01'}).status_code==422

def test_authentication_permissions_and_logout(client):
    from fastapi.testclient import TestClient
    from backend.app import app
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/machines').status_code==401
        assert anonymous.post('/api/auth/login',json={'username':'supervisor','password':'wrong'}).status_code==401
    login(client,'amy')
    assert client.post('/api/machines',json={'id':'CNC-77','name':'拒絕新增','kind':'mill'},headers={'X-Demo-Role':'supervisor'}).status_code==403
    t=next(t for t in client.get('/api/tickets').json() if t['engineer']=='Bob Wang')
    assert client.post('/api/tickets/'+t['id']+'/complete',json={'note':'冒用工程師'}).status_code==403
    assert client.post('/api/auth/logout',headers={'X-CSRF-Token':'invalid'}).status_code==403
    assert client.post('/api/auth/logout').status_code==200
    assert client.get('/api/tickets').status_code==401
    login(client)

def test_seeded_asset_persistence(client):
    from backend import operations
    before=client.get('/api/machines').json()
    demo=[m for m in before if m['id']!='CNC-99']
    assert len(demo)>=18
    assert all(m['asset']['installed_on'] and m['asset']['responsible'] and m['asset']['next_inspection'] for m in demo)
    assert all(len(m['asset']['part_dates'])==len(m['parts']) and len(m['asset']['inspections'])>=3 for m in demo)
    operations.seed()
    assert client.get('/api/machines').json()==before


def test_session_cookie_origin_and_expiry(client):
    import hashlib
    from datetime import datetime,timezone,timedelta
    from backend import store
    login(client,'amy')
    assert client.post('/api/auth/logout',headers={'Origin':'https://another-site.example'}).status_code==403
    token=client.cookies.get('predictfix_session')
    with store.Session() as db:
        session=db.get(store.LoginSession,hashlib.sha256(token.encode()).hexdigest())
        session.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    assert client.get('/api/machines').status_code==401
    r=client.post('/api/auth/login',json={'username':'supervisor','password':'TestOnly-Factory-12345'})
    assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
    client.headers['X-CSRF-Token']=r.json()['csrf']


def test_multimodal_evidence_and_review_history(client):
    import io,hashlib
    from PIL import Image
    t=client.post('/api/tickets',json={'machine':'CNC-03','issue':'照片與量測驗證','engineer':'Amy Chen'}).json()
    login(client,'amy')
    buf=io.BytesIO();Image.new('RGB',(48,32),(20,130,100)).save(buf,format='PNG');image=buf.getvalue()
    endpoint='/api/tickets/'+t['id']+'/photos'
    assert client.post(endpoint,content=b'not an image',headers={'Content-Type':'image/png'}).status_code==422
    uploaded=client.post(endpoint+'?filename=repair.png',content=image,headers={'Content-Type':'image/png'})
    assert uploaded.status_code==201,uploaded.text
    photo=uploaded.json();assert photo['sha256']==hashlib.sha256(image).hexdigest()
    assert client.get(photo['url']).content==image
    imported=client.post('/api/tickets/'+t['id']+'/measurements/import',content='metric,before,after,conditions\ntemperature,92,56,same load\n'.encode(),headers={'Content-Type':'text/csv'}).json()
    login(client,'bob')
    assert client.get(photo['url']).status_code==403
    assert client.post(endpoint,content=image).status_code==403
    login(client,'amy')
    payload={'note':'更換軸承並完成復測','measurements':imported['measurements'],'photo_ids':[photo['id']]}
    result=client.post('/api/tickets/'+t['id']+'/complete',json=payload)
    assert result.status_code==200,result.text
    proof=result.json()['workflow']['evidence']
    assert proof['measurements'][0]['unit']=='°C' and proof['measurements'][0]['after']==56
    assert proof['photos'][0]['sha256']==photo['sha256'] and proof['image_ai_used'] is False
    assert client.post(endpoint,content=image).status_code==409
    login(client,'bob');assert client.get(photo['url']).status_code==200
    login(client)
    assert client.post('/api/tickets/'+t['id']+'/review',json={'reviewer':'冒用姓名','decision':'reject','note':'請補充復測值'}).json()['workflow']['reviews'][-1]['reviewer']=='陳主管'
    login(client,'amy')
    payload['measurements'][0]['after']=54
    assert client.post('/api/tickets/'+t['id']+'/complete',json=payload).status_code==200
    saved=next(row for row in client.get('/api/tickets').json() if row['id']==t['id'])
    assert len(saved['workflow']['submissions'])==2
    assert saved['workflow']['submissions'][0]['measurements'][0]['after']==56
    assert saved['workflow']['submissions'][1]['measurements'][0]['after']==54

def test_invalid_evidence_and_csv(client):
    t=client.post('/api/tickets',json={'machine':'CNC-03','issue':'資料驗證測試','engineer':'Amy Chen'}).json()
    login(client,'amy')
    assert client.post('/api/tickets/'+t['id']+'/photos',content=b'x'*(6*1024*1024+1)).status_code==413
    assert client.post('/api/tickets/'+t['id']+'/measurements/import',content=b'metric,after\ntemperature,no-number').status_code==422
    assert client.post('/api/tickets/'+t['id']+'/complete',json={'note':'測試偽造照片','photo_ids':['missing']}).status_code==422
    assert client.post('/api/tickets/'+t['id']+'/complete',json={'note':'測試量測值','measurements':[{'metric':'temperature','after':'NaN'}]}).status_code==422

def test_demo_mode_is_explicit_and_roles_are_real(client,monkeypatch):
    monkeypatch.setenv('DEMO_MODE','0')
    assert client.post('/api/auth/demo',json={'role':'supervisor'}).status_code==403
    assert client.get('/api/auth/config').json()['demo_mode'] is False
    monkeypatch.setenv('DEMO_MODE','1')
    r=client.post('/api/auth/demo',json={'role':'engineer'})
    assert r.status_code==200 and r.json()['user']['role']=='engineer'
    client.headers['X-CSRF-Token']=r.json()['csrf']
    assert client.post('/api/machines',json={'id':'CNC-78','name':'不可新增','kind':'mill'}).status_code==403
    r=client.post('/api/auth/demo',json={'role':'supervisor'})
    assert r.json()['user']['role']=='supervisor'
    client.headers['X-CSRF-Token']=r.json()['csrf']


def test_chat_shift_ambiguity_and_unknown(client):
    r=client.post('/api/chat',json={'text':'哪些人是白班'}).json()
    assert r['route']=='clarification' and r['rows']==[] and r['sql'] is None
    assert '不知道' in r['answer'] and '早班' in r['answer']
    r=client.post('/api/chat',json={'text':'哪些人是白斑'}).json()
    assert r['route']=='clarification'
    r=client.post('/api/chat',json={'text':'哪些人是早班'}).json()
    assert r['query_kind']=='shifts' and len(r['rows'])==5
    assert all(row['shift']=='早班' for row in r['rows'])
    for question in ['今天誰上早班','Amy Chen 薪水多少','E999 是什麼意思','工廠明天會下雨嗎','公司的老闆叫什麼名字','誰沒有老婆','主軸壽命幾年','主管批准休假了嗎']:
        r=client.post('/api/chat',json={'text':question}).json()
        assert r['route']=='unknown', (question,r)
        assert '不知道' in r['answer'] and r['sql'] is None and not r['llm_used']

def test_classifier_cannot_force_unrelated_database_queries(client,monkeypatch):
    from backend import chat
    for intent in ['idle_people','unassigned','review','open_tickets','history','workload']:
        monkeypatch.setattr(chat,'classify',lambda q,i=intent:(i,.99))
        assert chat.database_answer('哪些人是白班')['route']=='clarification'
        assert chat.database_answer('明天的天氣會怎麼樣') is None
    monkeypatch.setattr(chat,'classify',lambda q:('idle_people',.99))
    assert chat.database_answer('誰沒有維修工單')['query_kind']=='idle_people'


def test_llm_unknown_is_not_replaced_with_unrelated_excerpt(client,monkeypatch):
    from backend import chat
    async def missing_answer(*args,**kwargs):
        return {'answer':'我不知道，沒有足夠的文件依據。','llm_used':True,'citations':[{'title':'無關摘錄','text':'不應覆蓋拒答'}]}
    monkeypatch.setattr(chat,'analyze',missing_answer)
    r=client.post('/api/chat',json={'text':'換刀後能直接量產嗎？'}).json()
    assert r['route']=='unknown' and r['answer']=='我不知道，沒有足夠的文件依據。'
