"""Demo-mode scenario for nameplate scan, machine overview and AI summary; isolated database only."""
import io
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from PIL import Image
from backend.app import app
from scripts.generate_nameplates import render_nameplate

PASSWORD=os.environ['BOOTSTRAP_PASSWORD']


def png(image):
  buffer=io.BytesIO()
  image.save(buffer,'PNG')
  return buffer.getvalue()


def login(client,username='supervisor'):
  response=client.post('/api/auth/login',json={'username':username,'password':PASSWORD})
  assert response.status_code==200,response.text
  client.headers['X-CSRF-Token']=response.json()['csrf']


def scan(client,content):
  return client.post('/api/scan/nameplate',content=content,headers={'Content-Type':'application/octet-stream'})


def scenario():
  with TestClient(app) as c:
    login(c)
    first=scan(c,png(render_nameplate('CNC-07')))
    assert first.status_code==200,first.text
    body=first.json()
    assert body['decision']=='auto' and body['candidates'][0]['machine_id']=='CNC-07',body
    assert body['engine'].startswith('rapidocr') and body['elapsed_ms']>=0 and body['text']
    blank=scan(c,png(Image.new('RGB',(400,300),(128,128,128)))).json()
    assert blank['candidates']==[] and blank['decision']=='manual',blank
    assert scan(c,'not an image'.encode()).status_code==422
    assert scan(c,b'0'*(7*1024*1024)).status_code==413
    samples=c.get('/api/scan/samples').json()
    assert len(samples)==18 and samples[0]['machine_id']=='CNC-01'
    image=c.get(samples[0]['url'])
    assert image.status_code==200 and image.headers['content-type']=='image/png'
    assert c.get('/api/scan/samples/..%2Fsecret.png').status_code==404
    assert c.get('/api/scan/samples/CNC-99.png').status_code==404
    from scripts.seed_machine_history import seed_history
    seeded=seed_history()
    assert seeded['machines']==18 and seeded['tickets']>=54,seeded
    assert seed_history().get('skipped') is True
    assert c.post('/api/stock',json={'name':'主軸軸承 6206','unit':'個','minimum':2}).status_code==201
    response=c.get('/api/machines/CNC-07/overview')
    assert response.status_code==200,response.text
    overview=response.json()
    assert set(overview)=={'data_mode','machine','live','parts','people','in_progress','history','maintenance','stock','reliability'}
    assert overview['data_mode']=='demo' and overview['machine']['id']=='CNC-07' and overview['machine']['installed_on']
    assert overview['live']['temp'] is not None and len(overview['parts'])==4 and overview['parts'][0]['replaced_on']
    history=overview['history']
    assert history and [h['closed_at'] for h in history]==sorted((h['closed_at'] for h in history),reverse=True)
    assert all(h['issue'].startswith('【DEMO 歷史】') and h['completion_note'] for h in history)
    assert overview['reliability']['mtbf_days'] is not None and overview['reliability']['mttr_hours'] is not None
    responsible=overview['people']['responsible']
    assert responsible['name'] and responsible['on_duty'] in (True,False) and responsible['open_tickets']>=0
    assert overview['people']['last_inspection']['inspector']
    assert overview['maintenance']['next_inspection']
    assert any(s['part']=='主軸軸承' and s['low'] for s in overview['stock']),overview['stock']
    busy=[o for o in (c.get(f'/api/machines/CNC-{n:02}/overview').json() for n in range(1,19)) if o['in_progress']]
    assert busy and all(o['in_progress'][0]['latest_log'] and o['in_progress'][0]['logged_minutes']>0 for o in busy)
    assert c.get('/api/machines/CNC-99/overview').status_code==404
    summary=c.post('/api/machines/CNC-07/ai-summary')
    assert summary.status_code==200,summary.text
    summary=summary.json()
    # 測試環境沒有本機模型，必須退回規則摘要而不是報錯
    assert summary['mode']=='rule' and len(summary['summary'])==3 and all(summary['summary'])
    assert 2<=len(summary['suggestions'])<=4
    assert all(s['text'] and s['source']['type'] in {'part','ticket','manual','plan','stock'} for s in summary['suggestions'])
    assert c.post('/api/machines/CNC-99/ai-summary').status_code==404
    login(c,'amy')
    assert c.get('/api/machines/CNC-07/overview').status_code==200
    assert scan(c,png(render_nameplate('CNC-03'))).json()['candidates'][0]['machine_id']=='CNC-03'
    c.post('/api/auth/logout')
    assert scan(c,png(render_nameplate('CNC-03'))).status_code==401
  print('machine_scan_scenario_passed')


if __name__=='__main__':
  scenario()
