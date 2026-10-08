import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def test_demo_preparation_idempotency_and_complete_flow(tmp_path):
    env={**os.environ,'APP_MODE':'demo','DEMO_MODE':'1',
         'BOOTSTRAP_PASSWORD':'Isolated-Interview-Password-123456',
         'DATABASE_URL':'sqlite:///'+str(tmp_path/'demo.db'),'LOCAL_LLM_MODEL':'','OLLAMA_MODEL':'','PYTHONUTF8':'1'}
    code='''
from fastapi.testclient import TestClient
from backend.app import app
from scripts.prepare_interview_demo import prepare
with TestClient(app) as c:
    assert c.post('/api/auth/demo',json={'role':'engineer','username':'supervisor'}).status_code==403
    first=prepare(c)
    assert c.get('/api/auth/config').json()['interview_demo_available']
    again=prepare(c)
    assert first['ticket_id']==again['ticket_id']
    done=prepare(c,complete=True)
    assert done['failed_verification_blocked'] and done['published_case_retrievable']
    fresh=prepare(c)
    assert fresh['ticket_id']!=done['ticket_id']
print('repeatable_demo_passed')
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,
                          text=True,encoding='utf-8',timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'repeatable_demo_passed' in result.stdout
