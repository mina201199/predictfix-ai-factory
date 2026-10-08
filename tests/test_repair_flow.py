import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_production_repair_flow_checklist_calendar_and_stock(tmp_path):
    env={**os.environ, 'APP_MODE':'production','DEMO_MODE':'0','BOOTSTRAP_PASSWORD':'Isolated-Flow-Password-123456',
         'DATABASE_URL':'sqlite:///'+str(tmp_path/'repair-flow.db'),'OLLAMA_MODEL':'','LOCAL_LLM_MODEL':''}
    result=subprocess.run([sys.executable,str(ROOT/'tests/repair_flow_scenario.py')],env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=120)
    assert result.returncode==0,result.stdout+'\n'+result.stderr


def test_demo_source_comparison_and_attachment(tmp_path):
    env={**os.environ,'APP_MODE':'demo','DEMO_MODE':'1','BOOTSTRAP_PASSWORD':'Isolated-Flow-Password-123456',
         'DATABASE_URL':'sqlite:///'+str(tmp_path/'demo-flow.db'),'OLLAMA_MODEL':'','LOCAL_LLM_MODEL':''}
    result=subprocess.run([sys.executable,str(ROOT/'tests/demo_flow_scenario.py')],env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=90)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
