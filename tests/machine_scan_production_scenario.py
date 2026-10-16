"""Production-mode scenario: a freshly registered machine has no readings or history and must not break the overview."""
import io
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import app
from scripts.generate_nameplates import render_nameplate

PASSWORD=os.environ['BOOTSTRAP_PASSWORD']


def scenario():
  with TestClient(app) as c:
    response=c.post('/api/auth/login',json={'username':'supervisor','password':PASSWORD})
    c.headers['X-CSRF-Token']=response.json()['csrf']
    assert c.post('/api/machines',json={'id':'MILL-001','name':'正式模式測試設備','kind':'mill','machine_model':'TEST-MODEL'}).status_code==201
    overview=c.get('/api/machines/MILL-001/overview')
    assert overview.status_code==200,overview.text
    body=overview.json()
    assert body['data_mode']=='production'
    assert body['live']['temp'] is None and body['live']['risk'] is None
    assert body['parts'] and body['parts'][0]['health'] is None
    assert body['history']==[] and body['in_progress']==[] and body['stock']==[]
    assert body['people']['responsible'] is None and body['people']['last_inspection'] is None
    assert body['reliability']['mtbf_days'] is None and body['reliability']['failures']==0
    assert c.get('/api/machines/NOPE-01/overview').status_code==404
    assert c.get('/api/scan/samples').status_code==404
    buffer=io.BytesIO();render_nameplate('MILL-001').save(buffer,'PNG')
    scan=c.post('/api/scan/nameplate',content=buffer.getvalue()).json()
    assert scan['candidates'][0]['machine_id']=='MILL-001',scan
    from scripts.seed_machine_history import seed_history
    try:seed_history()
    except SystemExit:pass
    else:raise AssertionError('History seeding must refuse production mode')
  print('machine_scan_production_scenario_passed')


if __name__=='__main__':
  scenario()
