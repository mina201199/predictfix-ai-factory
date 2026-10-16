import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module',params=['production','demo'])
def report(request,tmp_path_factory):
  mode=request.param
  # 匯入 backend 會固定 DATABASE_URL 與 APP_MODE，必須在子程序執行，才能兩種模式各用一個全新的資料庫
  env={**os.environ,'APP_MODE':mode,'DEMO_MODE':'1' if mode=='demo' else '0',
       'BOOTSTRAP_PASSWORD':'Isolated-Matrix-Password-123456',
       'DATABASE_URL':'sqlite:///'+str(tmp_path_factory.mktemp(mode)/'matrix.db'),
       'LLM_PROVIDER':'ollama','LOCAL_LLM_MODEL':'','OLLAMA_MODEL':'','OLLAMA_URL':'http://127.0.0.1:9','OPENAI_ENABLED':'0'}
  result=subprocess.run([sys.executable,str(ROOT/'tests/access_matrix_scenario.py')],env=env,cwd=ROOT,
                        capture_output=True,text=True,encoding='utf-8',timeout=600)
  lines=result.stdout.strip().splitlines()
  assert lines,result.stderr[-4000:]
  return json.loads(lines[-1])


def test_every_route_is_listed_in_access_matrix(report):
  # 新增 API 時這裡會失敗：先在 tests/access_matrix_scenario.py 的 MATRIX 與 docs/access-control.md 寫下誰能呼叫
  assert not report['unlisted'],'以下路由不在權限矩陣：\n'+'\n'.join(report['unlisted'])
  assert not report['stale'],'矩陣列了已不存在的路由：\n'+'\n'.join(report['stale'])
  assert not report['gaps'],'\n'.join(report['gaps'])


def test_access_matrix_matches_real_responses(report):
  failures=['{route} [{variant}] {role}: {problem} 預期 {expected} 實際 {got} {detail}'.format(**f) for f in report['failures']]
  assert not failures,f"{report['mode']} 模式權限不符：\n"+'\n'.join(failures)
  # 防止矩陣被意外清空後仍顯示通過
  assert report['checked']>=250
