import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import app
from backend import maintenance_ai

with TestClient(app) as c:
    r=c.post('/api/auth/demo',json={'role':'supervisor'})
    assert r.status_code==200,r.text
    c.headers['X-CSRF-Token']=r.json()['csrf']
    assert all(s.get('chunk_id') for s in maintenance_ai.corpus())
    body={'machine':'CNC-03','symptoms':'換刀卡住只發生在特定刀位','machine_model':'PF-VMC850-DEMO','component':'換刀','use_llm':False}
    r=c.post('/api/repair-flow/analyze',json=body)
    assert r.status_code==200,r.text
    assert r.json()['follow_up'] and r.json()['candidates']
    source=r.json()['candidates'][0]
    assert source['is_synthetic']
    ticket=c.post('/api/repair-flow/report',json=body,headers={'Idempotency-Key':'demo-flow-source-key'})
    assert ticket.status_code==201,ticket.text
    r=c.put('/api/tickets/'+ticket.json()['id']+'/procedure',json={'revision':0,'machine_model':body['machine_model'],'approval_note':'虛構示範清單核准','steps':[
        {'label':'依示範手冊記錄刀位','kind':'inspect','criterion':'記錄刀位與刀具資料','source_chunk_id':source['chunk_id'],'source_hash':source['source_hash']},
        {'label':'復測記錄驗收範圍','kind':'verify','criterion':'依示範程序紀錄測試範圍'}]})
    assert r.status_code==200,r.text
    assert r.json()['workflow']['procedure']['steps'][0]['source']['text']==source['text']
print('demo sources and attachment passed')
