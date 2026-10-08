import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_production_end_to_end_and_backup(tmp_path):
    env={**os.environ,'APP_MODE':'production','DEMO_MODE':'0','BOOTSTRAP_PASSWORD':'Isolated-Test-Password-123456',
         'DATABASE_URL':'sqlite:///'+str(tmp_path/'production-test.db'),'OLLAMA_MODEL':'','LOCAL_LLM_MODEL':''}
    result=subprocess.run([sys.executable,str(ROOT/'tests/production_scenario.py')],env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    report=json.loads(result.stdout.strip())
    assert all(report.values())

def test_first_production_start_requires_strong_password(tmp_path):
    env={**os.environ,'APP_MODE':'production','DEMO_MODE':'0','BOOTSTRAP_PASSWORD':'short',
         'DATABASE_URL':'sqlite:///'+str(tmp_path/'empty.db')}
    code='from fastapi.testclient import TestClient; from backend.app import app;\nwith TestClient(app): pass'
    result=subprocess.run([sys.executable,'-c',code],env=env,cwd=ROOT,capture_output=True,text=True,timeout=30)
    assert result.returncode!=0 and '16+ characters' in result.stderr

def test_concurrent_assignments_do_not_overbook_sqlite(tmp_path):
    env={**os.environ,'APP_MODE':'production','DEMO_MODE':'0','BOOTSTRAP_PASSWORD':'Isolated-Test-Password-123456',
         'DATABASE_URL':'sqlite:///'+str(tmp_path/'concurrency.db')}
    result=subprocess.run([sys.executable,str(ROOT/'tests/dispatch_concurrency_scenario.py')],env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'concurrent_capacity_check_passed' in result.stdout
