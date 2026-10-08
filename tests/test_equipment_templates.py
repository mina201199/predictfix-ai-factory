import os
import subprocess
import sys
from pathlib import Path


def test_equipment_templates_and_workflow(tmp_path):
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'APP_MODE':'demo','DEMO_MODE':'1','BOOTSTRAP_PASSWORD':'Isolated-Template-Password-123456',
         'DATABASE_URL':'sqlite:///'+str(tmp_path/'templates.db'),'LOCAL_LLM_MODEL':'','OLLAMA_MODEL':''}
    result=subprocess.run([sys.executable,str(root/'tests/equipment_template_scenario.py')],env=env,
                          cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=90)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
