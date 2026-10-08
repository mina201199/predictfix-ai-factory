import sys
from pathlib import Path
from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import app

with TestClient(app) as client:
    login=client.post('/api/auth/login',json={'username':'supervisor','password':'Isolated-Test-Password-123456'})
    client.headers['X-CSRF-Token']=login.json()['csrf']
    assert client.post('/api/admin/users',json={'username':'alice','name':'並發測試工程師','role':'engineer','password':'Isolated-Test-Password-123456','skills':['主軸']}).status_code==201
    now=datetime.now(timezone.utc)
    assert client.post('/api/duties',json={'username':'alice','starts_at':(now-timedelta(minutes=1)).isoformat(),'ends_at':(now+timedelta(hours=2)).isoformat(),'attendance':'present','capacity_minutes':90}).status_code==201
    assert client.post('/api/machines',json={'id':'TEST-01','name':'並發測試設備','kind':'mill'}).status_code==201
    tids=[]
    for n in range(2):
        t=client.post('/api/tickets',json={'machine':'TEST-01','issue':'主軸測試 '+str(n)}).json()
        tids.append(t['id'])
        assert client.put('/api/tickets/'+t['id']+'/estimate',json={'remaining_minutes':60,'note':'並發測試估時'}).status_code==200
    assert client.get('/api/dispatch').json()[0]['eligible']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda tid:client.patch('/api/tickets/'+tid+'/assign',json={'engineer':'並發測試工程師'}).status_code,tids))
    assert sorted(results)==[200,409],results
    assert sum(t['engineer']=='並發測試工程師' for t in client.get('/api/tickets').json())==1
    print('concurrent_capacity_check_passed')
