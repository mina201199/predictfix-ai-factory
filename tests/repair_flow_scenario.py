"""Full production workflow using an isolated database, including concurrent stock use."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import app
from backend import repair_flow, store

PASSWORD = 'Isolated-Flow-Password-123456'


def login(c, user='supervisor'):
    r = c.post('/api/auth/login', json={'username': user, 'password': PASSWORD})
    assert r.status_code == 200, r.text
    c.headers['X-CSRF-Token'] = r.json()['csrf']


def checked(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


with TestClient(app) as c:
    login(c)
    checked(c.post('/api/machines', json={'id': 'M01', 'name': '驗證加工中心', 'kind': 'mill', 'machine_model': 'MODEL-01'}), 201)
    for username, name in [('tech', '測試工程師'), ('other', '其他工程師')]:
        checked(c.post('/api/admin/users', json={'username': username, 'name': name, 'role': 'engineer', 'password': PASSWORD,
            'specialty': '換刀', 'skills': ['換刀'], 'qualifications': ['內部換刀資格']}), 201)
    now = datetime.now(timezone.utc)
    checked(c.post('/api/duties', json={'username': 'tech', 'starts_at': (now-timedelta(hours=1)).isoformat(),
        'ends_at': (now+timedelta(hours=6)).isoformat(), 'attendance': 'present', 'capacity_minutes': 300, 'note': '隔離驗證班次'}), 201)
    manual = checked(c.post('/api/knowledge/manuals', json={'title': '授權換刀檢查手冊', 'version': '1.0', 'machine_model': 'MODEL-01',
        'component': '換刀', 'content': '# 換刀排查\n\n'+('換刀卡住時記錄刀位與刀號、發生條件、警報全文及近期變更。核對刀具資料一致性，保存檢查發現。\n'*8)+
            '\n# 維修後驗收\n\n'+('依核准程序確認刀位資料一致性，記錄測試範圍、條件與警報是否再現。未測範圍保留未驗證。\n'*8),
        'is_synthetic': False, 'source_label': '隔離測試手冊', 'rights_confirmed': True}), 201)
    body = {'machine': 'M01', 'symptoms': '換刀卡住刀位不一致', 'machine_model': 'MODEL-01', 'component': '換刀',
        'conditions': '特定刀位換刀時', 'alarm': '無警報', 'recent_change': '剛更換刀把', 'scope': '單一刀位', 'previous_checks': '尚未檢查', 'use_llm': False}
    a = checked(c.post('/api/repair-flow/analyze', json=body))
    assert a['ready_for_approval'] and a['candidates'] and not a['assistant']['llm_used']
    incomplete = checked(c.post('/api/repair-flow/analyze', json={**body, 'conditions': ''}))
    assert any(q['field']=='conditions' for q in incomplete['follow_up'])
    ticket = checked(c.post('/api/repair-flow/report', json=body, headers={'Idempotency-Key': 'flow-report-key'}), 201)
    tid = ticket['id']
    assert checked(c.post('/api/repair-flow/report', json=body, headers={'Idempotency-Key': 'flow-report-key'}), 201)['id'] == tid
    assert c.post('/api/repair-flow/report', json={**body, 'scope': '所有刀位'}, headers={'Idempotency-Key': 'flow-report-key'}).status_code == 409
    updated=checked(c.put('/api/tickets/'+tid+'/report-context',json={**body,'previous_checks':'補充核對刀位資料'}))
    assert updated['workflow']['report_context']['previous_checks']=='補充核對刀位資料'
    source = a['candidates'][0]
    procedure = {'revision': 0, 'machine_model': 'MODEL-01', 'approval_note': '依核准手冊確認適用範圍', 'steps': [
        {'label': '記錄刀位與刀號', 'kind': 'inspect', 'criterion': '核對與刀具主檔一致', 'source_chunk_id': source['chunk_id'], 'source_hash': source['source_hash']},
        {'label': '維修後復測確認', 'kind': 'verify', 'criterion': '依核准程序完成測試，紀錄條件與結果'}]}
    assert c.put('/api/tickets/'+tid+'/procedure', json={**procedure, 'steps': [{**procedure['steps'][0], 'source_hash': 'bad'}, procedure['steps'][1]]}).status_code == 409
    t = checked(c.put('/api/tickets/'+tid+'/procedure', json=procedure))
    assert t['workflow']['procedure']['steps'][0]['source']['text'] == source['text']
    assert c.put('/api/tickets/'+tid+'/procedure', json=procedure).status_code == 409
    checked(c.put('/api/tickets/'+tid+'/estimate', json={'remaining_minutes': 30, 'required_qualifications': ['內部換刀資格'], 'note': '依核准清單估時'}))
    rank = checked(c.get('/api/dispatch', params={'ticket_id': tid, 'part': '換刀'}))
    assert next(p for p in rank if p['username']=='tech')['eligible']
    assert not next(p for p in rank if p['username']=='other')['eligible']
    checked(c.patch('/api/tickets/'+tid+'/assign', json={'engineer': '測試工程師'}))
    item = checked(c.post('/api/stock', json={'name': 'TEST-密封件', 'unit': '個', 'minimum': 2}), 201)['id']
    received = checked(c.post('/api/stock/'+item+'/movements', json={'kind': 'receive', 'quantity': 5, 'note': '驗證入庫批號'}, headers={'Idempotency-Key': 'receive-stock-key'}))
    assert checked(c.post('/api/stock/'+item+'/movements', json={'kind': 'receive', 'quantity': 5, 'note': '驗證入庫批號'}, headers={'Idempotency-Key': 'receive-stock-key'}))['id'] == received['id']
    login(c, 'other')
    assert c.put('/api/tickets/'+tid+'/report-context',json=body).status_code==403
    assert c.put('/api/tickets/'+tid+'/procedure', json=procedure).status_code == 403
    assert c.put('/api/tickets/'+tid+'/procedure/results', json={'revision': 1, 'results': []}).status_code == 422
    assert c.post('/api/stock/'+item+'/movements', json={'kind': 'issue', 'quantity': 1, 'ticket_id': tid, 'note': '越權領用驗證'}, headers={'Idempotency-Key': 'other-stock-key'}).status_code == 403
    login(c, 'tech')
    p = t['workflow']['procedure']
    result = {'revision': p['revision'], 'results': [{'step_id': s['id'], 'outcome': 'pass', 'note': '核對與紀錄確認一致'} for s in p['steps']]}
    assert c.post('/api/tickets/'+tid+'/complete', json={'note': '尚未檢查不能通過'}).status_code == 422
    assert c.put('/api/tickets/'+tid+'/procedure/results', json={**result, 'results': [{**result['results'][1], 'outcome': 'na'}]}).status_code == 422
    assert c.put('/api/tickets/'+tid+'/procedure/results', json={**result, 'results': [{**result['results'][0], 'step_id': 'foreign'}]}).status_code == 422
    checked(c.post('/api/tickets/'+tid+'/start'))
    failure = {**result, 'results': [result['results'][0], {**result['results'][1], 'outcome': 'fail', 'note': '復測仍有刀位不一致'}]}
    t = checked(c.put('/api/tickets/'+tid+'/procedure/results', json=failure))
    assert c.post('/api/tickets/'+tid+'/complete', json={'note': '復測未通過不能結案'}).status_code == 422
    result['revision'] = t['workflow']['procedure']['revision']
    t = checked(c.put('/api/tickets/'+tid+'/procedure/results', json=result))
    assert c.put('/api/tickets/'+tid+'/procedure/results', json=result).status_code == 409
    def issue(n):
        return c.post('/api/stock/'+item+'/movements', json={'kind': 'issue', 'quantity': 3, 'ticket_id': tid, 'note': '並發領用檢查'}, headers={'Idempotency-Key': f'concurrent-issue-{n}'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(issue, [1, 2]))
    assert sorted(r.status_code for r in responses)==[200,409]
    assert checked(c.get('/api/stock'))[0]['quantity']==2
    returned = checked(c.post('/api/stock/'+item+'/movements', json={'kind': 'return', 'quantity': 1, 'ticket_id': tid, 'note': '未使用備品退料'}, headers={'Idempotency-Key': 'return-one-key'}))
    assert returned['balance']==3
    assert c.post('/api/stock/'+item+'/movements', json={'kind': 'return', 'quantity': 3, 'ticket_id': tid, 'note': '退料不可超領用'}, headers={'Idempotency-Key': 'return-extra-key'}).status_code==422
    submitted = checked(c.post('/api/tickets/'+tid+'/complete', json={'note': '核對刀具資料後，依核准程序復測確認'}))
    assert submitted['workflow']['evidence']['procedure']['steps'][1]['result']['outcome']=='pass'
    assert c.put('/api/tickets/'+tid+'/procedure/results', json={**result,'revision':t['workflow']['procedure']['revision']}).status_code==409
    assert c.post('/api/tickets/'+tid+'/review', json={'decision':'approve','note':'工程師不能自行審核'}).status_code==403
    login(c)
    rejected = checked(c.post('/api/tickets/'+tid+'/review', json={'decision':'reject','note':'請補齊復測範圍'}))
    assert 'result' not in rejected['workflow']['procedure']['steps'][0]
    assert rejected['workflow']['submissions'][0]['procedure']['steps'][0]['result']['outcome']=='pass'
    login(c,'tech')
    assert c.post('/api/tickets/'+tid+'/complete', json={'note':'重修仍需新結果'}).status_code==422
    result['revision']=rejected['workflow']['procedure']['revision']
    checked(c.put('/api/tickets/'+tid+'/procedure/results',json=result))
    checked(c.post('/api/tickets/'+tid+'/complete',json={'note':'已補齊刀位測試範圍並確認'}))
    login(c)
    completed = checked(c.post('/api/tickets/'+tid+'/review',json={'decision':'approve','note':'復測範圍與清單確認'}))
    login(c,'tech')
    success_index=next(i for i,r in enumerate(responses,1) if r.status_code==200)
    assert c.post('/api/stock/'+item+'/movements',json={'kind':'issue','quantity':3,'ticket_id':tid,'note':'並發領用檢查'},headers={'Idempotency-Key':f'concurrent-issue-{success_index}'}).status_code==200
    login(c)
    assert len(completed['workflow']['submissions'])==2
    case = checked(c.post('/api/tickets/'+tid+'/case-draft'),201)
    assert case['fields']['machine_model']=='MODEL-01' and '核對與紀錄' in case['fields']['verification']
    assert case['source_snapshot']['workflow']['procedure']['steps'][0]['source']['text']==source['text']
    checked(c.post('/api/knowledge/manuals/'+manual['id']+'/withdraw'))
    newer = checked(c.post('/api/repair-flow/report',json=body,headers={'Idempotency-Key':'new-source-ticket'}),201)
    assert c.put('/api/tickets/'+newer['id']+'/procedure',json=procedure).status_code==422
    pm_body = {**procedure,'steps':[{k:v for k,v in s.items() if not k.startswith('source_')} for s in procedure['steps']],
        'machine':'M01','title':'定期換刀檢查','interval_days':30,'next_due':(repair_flow.today()-timedelta(days=2)).isoformat()}
    plan=checked(c.post('/api/maintenance-plans',json=pm_body),201)
    assert plan['reminder']=='overdue'
    pm=checked(c.post('/api/maintenance-plans/'+plan['id']+'/generate'))
    assert checked(c.post('/api/maintenance-plans/'+plan['id']+'/generate'))['id']==pm['id']
    checked(c.put('/api/tickets/'+pm['id']+'/estimate',json={'remaining_minutes':20,'note':'週期保養估時'}))
    checked(c.patch('/api/tickets/'+pm['id']+'/assign',json={'engineer':'測試工程師'}))
    login(c,'tech')
    checked(c.put('/api/tickets/'+pm['id']+'/procedure/results',json={'revision':1,'results':[{'step_id':s['id'],'outcome':'pass','note':'保養項目逐項確認'} for s in pm['workflow']['procedure']['steps']]}))
    checked(c.post('/api/tickets/'+pm['id']+'/complete',json={'note':'週期保養與復測完成'}))
    login(c)
    checked(c.post('/api/tickets/'+pm['id']+'/review',json={'decision':'approve','note':'確認保養項目與復測'}))
    advanced=checked(c.get('/api/maintenance-plans'))[0]
    assert advanced['next_due']==(repair_flow.today()+timedelta(days=30)).isoformat() and not advanced['open_ticket']
    assert c.post('/api/maintenance-plans/'+plan['id']+'/generate').status_code==409
    assert c.get('/workflow.html').status_code==200

with TestClient(app) as c:
    login(c)
    assert checked(c.get('/api/stock'))[0]['quantity']==3
    assert checked(c.get('/api/maintenance-plans'))[0]['next_due']==advanced['next_due']
    assert next(t for t in checked(c.get('/api/tickets')) if t['id']==tid)['status']=='已完成'
print(json.dumps({'production_flow':'passed','checklist_history':'passed','concurrent_stock':'passed','calendar_cycle':'passed','restart_persistence':'passed'}))
