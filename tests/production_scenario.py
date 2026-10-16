"""Isolated integration scenario; its fixture records never enter the deployed DB."""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import app
from backend import store
from scripts.backup_database import backup,restore

PASSWORD='Isolated-Test-Password-123456'

def login(client,username='supervisor',password=PASSWORD):
    response=client.post('/api/auth/login',json={'username':username,'password':password})
    assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=response.json()['csrf']

def scenario():
    with TestClient(app) as c:
        assert c.get('/healthz').json()['mode']=='production'
        assert c.get('/api/tickets').status_code==401
        assert c.post('/api/auth/demo',json={'role':'supervisor'}).status_code==403
        login(c)
        assert c.get('/api/machines').json()==[]
        assert c.get('/api/personnel').json()==[]
        assert c.get('/api/knowledge/manuals').json()==[]
        assert c.get('/api/cases').json()==[]
        for route in ['/api/chat','/api/copilot','/api/replay','/api/predict','/factory.js','/index.html']:
            assert c.get(route).status_code==404
        assert 'console.js' in c.get('/').text
        assert c.get('/api/health').json()['sensor_model_ready'] is False
        assert c.get('/api/health').json()['component_health']=='not_connected'
        assert c.get('/').headers['x-content-type-options']=='nosniff'
        assert c.put('/api/admin/users/supervisor/active',json={'active':False}).status_code==409
        for username,name,skill in [('alice','測試工程師甲','主軸'),('bravo','測試工程師乙','冷卻')]:
            payload={'username':username,'name':name,'role':'engineer','password':PASSWORD,'skills':[skill],'qualifications':['電控授權'] if username=='alice' else []}
            assert c.post('/api/admin/users',json=payload).status_code==201
            assert c.post('/api/admin/users',json=payload).status_code==409
        assert all(not p['eligible'] for p in c.get('/api/dispatch').json())
        now=datetime.now(timezone.utc)
        d={'username':'alice','starts_at':(now-timedelta(minutes=5)).isoformat(),'ends_at':(now+timedelta(hours=8)).isoformat(),'attendance':'scheduled','capacity_minutes':420,'note':'測試排班'}
        assert c.post('/api/duties',json={**d,'starts_at':'2026-10-06T08:00:00'}).status_code==422
        assert c.post('/api/duties',json={**d,'capacity_minutes':1000}).status_code==422
        did=c.post('/api/duties',json=d).json()['id']
        assert c.post('/api/duties',json=d).status_code==409
        assert not next(p for p in c.get('/api/dispatch').json() if p['username']=='alice')['eligible']
        assert c.put('/api/duties/'+did+'/attendance',json={**d,'attendance':'present'}).status_code==200
        assert c.post('/api/duties',json={**d,'username':'bravo','attendance':'present'}).status_code==201
        assert c.post('/api/machines',json={'id':'MILL-001','name':'隔離測試設備','kind':'mill','machine_model':'TEST-MODEL'}).status_code==201
        machine=c.get('/api/machines').json()[0]
        assert machine['temp'] is None and machine['risk'] is None and machine['parts'][0][1] is None
        first=c.post('/api/tickets',json={'machine':'MILL-001','issue':'測試主軸異常'}).json()
        tid=first['id']
        assert c.put('/api/tickets/'+tid+'/estimate',json={'remaining_minutes':300,'required_qualifications':['電控授權'],'note':'測試估時依據'}).status_code==200
        rank=c.get('/api/dispatch',params={'part':'主軸','ticket_id':tid}).json()
        assert rank[0]['username']=='alice' and rank[0]['eligible']
        assert not next(p for p in rank if p['username']=='bravo')['eligible']
        assert c.patch('/api/tickets/'+tid+'/assign',json={'engineer':'測試工程師乙'}).status_code==409
        assert c.patch('/api/tickets/'+tid+'/assign',json={'engineer':'測試工程師甲'}).status_code==200
        after=c.get('/api/dispatch',params={'minutes':200}).json()
        assert not next(p for p in after if p['username']=='alice')['eligible']
        second=c.post('/api/tickets',json={'machine':'MILL-001','issue':'測試冷卻異常','engineer':'測試工程師乙'}).json()
        assert second.get('id')
        assert next(p for p in c.get('/api/dispatch').json() if p['username']=='bravo')['unestimated_cases']==1
        assert not next(p for p in c.get('/api/dispatch').json() if p['username']=='bravo')['eligible']
        assert c.put('/api/tickets/'+second['id']+'/estimate',json={'remaining_minutes':60,'note':'測試估時依據'}).status_code==200
        manual={'title':'隔離測試維修手冊','version':'1','machine_model':'TEST-MODEL','component':'主軸','content':'## 異常紀錄\n'+('主軸振動需要核對轉速與量測條件，記錄主軸警報全文。\n'*20),'is_synthetic':False,'rights_confirmed':True,'source_label':'僅供自動化測試，資料不進正式環境'}
        assert c.post('/api/knowledge/manuals',json={**manual,'is_synthetic':True}).status_code==422
        assert c.post('/api/knowledge/manuals',json=manual).status_code==201
        answer=c.post('/api/assist',json={'question':'主軸振動要記錄什麼','machine_model':'TEST-MODEL','use_llm':False,'allow_synthetic':True}).json()
        assert answer['citations'] and all(not p['is_synthetic'] for p in answer['citations'])
        with TestClient(app) as engineer:
            login(engineer,'alice')
            assert engineer.post('/api/duties',json=d).status_code==403
            assert engineer.get('/api/admin/users').status_code==403
            assert engineer.put('/api/tickets/'+tid+'/estimate',json={'remaining_minutes':1,'note':'非法估時'}).status_code==403
            assert engineer.post('/api/tickets/'+second['id']+'/start').status_code==403
            assert engineer.post('/api/tickets/'+tid+'/start').status_code==200
            assert engineer.post('/api/tickets/'+tid+'/work-logs',json={'minutes':45,'note':'測試量測與檢查'}).status_code==201
            assert engineer.post('/api/tickets/'+tid+'/complete',json={'note':'測試發現、處置與驗收紀錄','measurements':[{'metric':'temperature','before':60,'after':40,'conditions':'隔離測試條件'}]}).status_code==200
            assert c.post('/api/tickets/'+tid+'/review',json={'decision':'approve','note':'測試驗收結果確認'}).status_code==200
            assert c.get('/api/tickets/'+tid+'/work-logs').json()['total_minutes']==45
            case=c.post('/api/tickets/'+tid+'/case-draft').json()
            assert case['fields']['is_synthetic'] is False
            assert c.put('/api/admin/users/alice/password',json={'password':PASSWORD+'new'}).status_code==200
            assert engineer.get('/api/auth/me').status_code==401
        assert c.put('/api/admin/users/bravo/active',json={'active':False}).status_code==409
        audits=c.get('/api/audit').json()
        assert all('password' not in a['payload'] for a in audits)
        # Online backup retains committed changes, restore clears all sessions.
        if store.engine.dialect.name=='sqlite':
            source=Path(store.engine.url.database)
            dest=source.parent/'backup.db';restored=source.parent/'restored.db'
            backup(source,dest);restore(dest,restored)
            import sqlite3
            with sqlite3.connect(restored) as db:
                assert db.execute('SELECT count(*) FROM tickets').fetchone()[0]==2
                assert db.execute('SELECT count(*) FROM work_logs').fetchone()[0]==1
                assert db.execute('SELECT count(*) FROM login_sessions').fetchone()[0]==0
            try:restore(dest,restored)
            except FileExistsError:pass
            else:raise AssertionError('Restore overwrote an existing database')
            backup_result=True
        else:
            # PostgreSQL 備份要用容器內的 pg_dump，由 verify_postgres.py 的容器層驗證，這裡不假裝已驗證
            backup_result='verified_in_container_layer'
    # Restart preserves records and does not seed demonstration records.
    with TestClient(app) as c:
        login(c)
        assert len(c.get('/api/machines').json())==1
        assert len(c.get('/api/tickets').json())==2
    # Reusing a previously seeded demo database is rejected at startup.
    with store.Session() as db:
        db.add(store.Audit(kind='asset_demo_seed_v1',request_id='contamination-test',payload='{}'));db.commit()
    try:
        with TestClient(app):pass
    except RuntimeError as e:assert 'Demo database' in str(e)
    else:raise AssertionError('Contaminated database was accepted')
    print(json.dumps({'production_isolation':True,'account_permissions':True,'attendance_dispatch':True,'qualification_and_load_checks':True,'maintenance_workflow':True,'online_backup_restore':backup_result,'restart_persistence':True}))

if __name__=='__main__':scenario()
