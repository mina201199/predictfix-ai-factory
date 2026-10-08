"""Exercise template permissions, revision conflicts, snapshots and checklist gates."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import app

with TestClient(app) as c:
    def ok(r,status=200):
        assert r.status_code==status,r.text
        return r.json()
    def login(user):
        r=ok(c.post('/api/auth/demo',json={'role':'supervisor' if user=='supervisor' else 'engineer',
                                          **({} if user=='supervisor' else {'username':user})}))
        c.headers['X-CSRF-Token']=r['csrf']
    login('supervisor')
    existing=ok(c.get('/api/machines'))
    builtins=ok(c.get('/api/equipment-templates'))
    assert len(builtins)==2
    body={k:v for k,v in builtins[0].items() if k not in ('id','revision','builtin')}
    body.update(name='本廠精密加工模板',parts=['主軸軸承','換刀機構','冷卻迴路','進給螺桿','控制模組'])
    template=ok(c.post('/api/equipment-templates',json=body),201)
    assert c.post('/api/equipment-templates',json={**body,'parts':['控制模組','控制模組']}).status_code==422
    assert c.post('/api/equipment-templates',json={**body,'name':'  '}).status_code==422
    assert c.post('/api/equipment-templates',json={**body,'steps':[body['steps'][0]]*2}).status_code==422
    assert c.post('/api/machines',json={'id':'BAD-TPL','name':'錯誤模板設備','kind':'lathe','template_id':template['id']}).status_code==422
    m=ok(c.post('/api/machines',json={'id':'TPL-TEST','name':'模板驗證機台','kind':'mill',
                                    'machine_model':'FACTORY-MODEL-1','template_id':template['id']}),201)
    assert [p[0] for p in m['parts']]==body['parts']
    assert all(p[1] is None for p in m['parts']) and m['risk'] is None
    assert m['measurement_fields'][0]['unit']=='°C'
    revised=ok(c.put('/api/equipment-templates/'+template['id'],json={**body,'revision':1,'parts':['新版主軸','新版控制器']}))
    assert revised['revision']==2
    assert c.put('/api/equipment-templates/'+template['id'],json={**body,'revision':1}).status_code==409
    stored=next(m for m in ok(c.get('/api/machines')) if m['id']=='TPL-TEST')
    assert stored['equipment_template']['revision']==1 and [p[0] for p in stored['parts']]==body['parts']
    assert all(next(m for m in ok(c.get('/api/machines')) if m['id']==old['id'])==old for old in existing)
    t=ok(c.post('/api/tickets',json={'machine':m['id'],'issue':'模板流程驗證','engineer':'Amy Chen'}),201)
    tid=t['id'];procedure={'revision':0,'machine_model':'FACTORY-MODEL-1','approval_note':'主管確認本廠機型與驗收範圍',
                          'steps':m['equipment_template']['steps']}
    t=ok(c.put('/api/tickets/'+tid+'/procedure',json=procedure))
    login('amy')
    assert c.post('/api/equipment-templates',json=body).status_code==403
    assert c.put('/api/equipment-templates/'+template['id'],json={**body,'revision':2}).status_code==403
    ok(c.post('/api/tickets/'+tid+'/start'))
    assert c.post('/api/tickets/'+tid+'/complete',json={'note':'未填驗收應阻擋'}).status_code==422
    p=t['workflow']['procedure']
    ok(c.put('/api/tickets/'+tid+'/procedure/results',json={'revision':p['revision'],
        'results':[{'step_id':s['id'],'outcome':'pass','note':'隔離測試，已依核准條件记录結果'} for s in p['steps']]}))
    ok(c.post('/api/tickets/'+tid+'/complete',json={'note':'測試驗收通過後提交'}))
    print('Template creation, snapshot preservation, permissions, revision conflicts and workflow gates passed.')
