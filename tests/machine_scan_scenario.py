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
    login(c,'amy')
    assert scan(c,png(render_nameplate('CNC-03'))).json()['candidates'][0]['machine_id']=='CNC-03'
    c.post('/api/auth/logout')
    assert scan(c,png(render_nameplate('CNC-03'))).status_code==401
  print('machine_scan_scenario_passed')


if __name__=='__main__':
  scenario()
