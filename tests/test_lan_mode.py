import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def runLan(tmpPath,quickLogin):
  password=secrets.token_urlsafe(24)
  env={**os.environ,'APP_MODE':'demo','DEMO_MODE':str(quickLogin),'LAN_MODE':'1',
       'DATABASE_URL':'sqlite:///'+str(tmpPath/'lan.db'),'BOOTSTRAP_PASSWORD':password,
       'OLLAMA_MODEL':'','LOCAL_LLM_MODEL':'','PYTHONUTF8':'1'}
  code='''import json, os
from fastapi.testclient import TestClient
from backend.app import app
with TestClient(app) as client:
  config=client.get('/api/auth/config').json()
  demo=client.post('/api/auth/demo',json={'role':'supervisor'}).status_code
  login=client.post('/api/auth/login',json={'username':'supervisor','password':os.environ['BOOTSTRAP_PASSWORD']}).status_code
  os.environ['DEMO_MODE']='1'
  forced=client.post('/api/auth/demo',json={'role':'supervisor'}).status_code
  print(json.dumps({'config':config,'demo':demo,'login':login,'forced':forced}))
'''
  return subprocess.run([sys.executable,'-c',code],env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=90)


def test_lan_disables_quick_login_but_accepts_password(tmp_path):
  result=runLan(tmp_path,0)
  assert result.returncode==0,result.stderr
  report=json.loads(result.stdout)
  assert report['config']['lan_mode'] is True
  assert report['config']['demo_mode'] is False
  assert report['demo']==403 and report['forced']==403
  assert report['login']==200


def test_lan_rejects_quick_login_configuration(tmp_path):
  result=runLan(tmp_path,1)
  assert result.returncode!=0
  assert 'LAN mode forbids quick login' in result.stderr
