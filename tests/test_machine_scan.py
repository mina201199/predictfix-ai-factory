import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def run_scenario(tmp_path,script,mode):
  # 匯入 backend 會固定 DATABASE_URL，情境必須在子程序執行，避免影響 test_api 的隔離資料庫
  env={**os.environ,'APP_MODE':mode,'DEMO_MODE':'1' if mode=='demo' else '0','BOOTSTRAP_PASSWORD':'Isolated-Scan-Password-123456',
       'DATABASE_URL':'sqlite:///'+str(tmp_path/f'{mode}-scan.db'),'OLLAMA_MODEL':'','LOCAL_LLM_MODEL':''}
  result=subprocess.run([sys.executable,str(ROOT/'tests'/script)],env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=300)
  assert result.returncode==0,result.stdout+'\n'+result.stderr
  return result.stdout


def test_demo_scan_overview_and_summary(tmp_path):
  assert 'machine_scan_scenario_passed' in run_scenario(tmp_path,'machine_scan_scenario.py','demo')
