"""以隔離資料庫驗證異常請求、登入節流及履歷部分更新。"""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = r'''
import copy
from concurrent.futures import ThreadPoolExecutor
import threading
from fastapi.testclient import TestClient
from backend.app import app
from backend import auth

with TestClient(app, raise_server_exceptions=False) as client:
  if case == 'malformed_origin':
    response = client.post('/api/auth/login', json={'username':'supervisor','password':'Audit-Password-123456'},
      headers={'origin':'http://['})
    assert response.status_code == 403, (response.status_code, response.text)
  elif case == 'cross_scheme_origin':
    response = client.post('/api/auth/login', json={'username':'supervisor','password':'Audit-Password-123456'},
      headers={'origin':'https://testserver'})
    assert response.status_code == 403, (response.status_code, response.text)
  elif case == 'concurrent_login':
    originalHash = auth.password_hash
    barrier = threading.Barrier(5)
    def synchronizedHash(password, salt=None):
      if password == 'wrong-password':
        barrier.wait(timeout=20)
      return originalHash(password, salt)
    auth.password_hash = synchronizedHash
    def wrongLogin(_):
      return client.post('/api/auth/login', json={'username':'supervisor','password':'wrong-password'}).status_code
    with ThreadPoolExecutor(max_workers=5) as executor:
      statuses = list(executor.map(wrongLogin, range(5)))
    assert statuses == [401] * 5, statuses
    response = client.post('/api/auth/login', json={'username':'supervisor','password':'Audit-Password-123456'})
    assert response.status_code == 429, (response.status_code, response.text)
  else:
    response = client.post('/api/auth/login', json={'username':'supervisor','password':'Audit-Password-123456'},
      headers={'origin':'http://testserver'})
    assert response.status_code == 200, response.text
    csrf = response.json()['csrf']
    if case == 'non_ascii_csrf':
      response = client.post('/api/auth/logout', headers={b'x-csrf-token':b'\xff'})
      assert response.status_code == 403, (response.status_code, response.text)
      assert client.get('/api/auth/me').status_code == 200
    elif case == 'partial_asset':
      before = next(machine for machine in client.get('/api/machines').json() if machine['id'] == 'CNC-03')['asset']
      saved = copy.deepcopy(before)
      response = client.patch('/api/machines/CNC-03/asset', json={'responsible':'Alex Lin'},
        headers={'x-csrf-token':csrf})
      assert response.status_code == 200, response.text
      saved['responsible'] = 'Alex Lin'
      assert response.json()['asset'] == saved, response.json()['asset']
      response = client.patch('/api/machines/CNC-03/asset', json={}, headers={'x-csrf-token':csrf})
      assert response.status_code == 200 and response.json()['asset'] == saved
      response = client.patch('/api/machines/CNC-03/asset', json={'installed_on':None}, headers={'x-csrf-token':csrf})
      assert response.status_code == 200 and response.json()['asset']['installed_on'] is None
      assert response.json()['asset']['part_dates'] == saved['part_dates']
    else:
      raise AssertionError(case)
'''


@pytest.mark.parametrize('case', ['malformed_origin', 'cross_scheme_origin', 'non_ascii_csrf',
  'concurrent_login', 'partial_asset'])
def test_request_boundary_regression(case, tmp_path):
  env = {**os.environ, 'APP_MODE':'demo', 'DEMO_MODE':'0', 'LAN_MODE':'0',
    'BOOTSTRAP_PASSWORD':'Audit-Password-123456', 'DATABASE_URL':'sqlite:///' + str(tmp_path / 'audit.db'),
    'OPENAI_ENABLED':'0', 'OPENAI_API_KEY':'', 'LOCAL_LLM_MODEL':'', 'OLLAMA_MODEL':'',
    'PYTHONIOENCODING':'utf-8'}
  result = subprocess.run([sys.executable, '-c', 'case=' + repr(case) + '\n' + SCENARIO],
    cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
  assert result.returncode == 0, result.stdout + result.stderr
