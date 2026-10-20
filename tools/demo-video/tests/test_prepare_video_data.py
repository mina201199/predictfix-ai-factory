import importlib.util
import json
from pathlib import Path

import httpx
import pytest


@pytest.mark.parametrize('existingDuties,noShift,expectedUsers', [
  ([], True, {'amy', 'alex', 'bob'}),
  ([{'username':'amy', 'starts_at':'2020-01-01T00:00:00+00:00',
    'ends_at':'2020-01-01T08:00:00+00:00'}], False, {'amy', 'alex', 'bob', 'grace'}),
])
def test_demo_preparation_omits_no_shift_and_ignores_expired_duties(monkeypatch, existingDuties, noShift, expectedUsers):
  modulePath = Path(__file__).resolve().parents[1] / 'prepare_video_data.py'
  spec = importlib.util.spec_from_file_location('videoPreparation', modulePath)
  preparation = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(preparation)
  staff = dict(preparation.STAFF)
  if noShift:
    staff['grace'] = (*staff['grace'][:3], None)
  monkeypatch.setattr(preparation, 'STAFF', staff)
  sentDuties = []

  def respond(request):
    if request.url.path == '/api/auth/config':
      return httpx.Response(200, json={'app_mode':'demo', 'demo_mode':True})
    if request.url.path == '/api/auth/demo':
      return httpx.Response(200, json={'csrf':'test-csrf'})
    if request.method == 'POST' and request.url.path == '/api/duties':
      body = json.loads(request.content)
      if body['attendance'] not in ['present', 'scheduled', 'leave', 'absent']:
        return httpx.Response(422, json={'detail':'invalid attendance'})
      sentDuties.append(body)
      return httpx.Response(201, json={'id':'test-duty'})
    if request.url.path == '/api/duties':
      return httpx.Response(200, json=existingDuties)
    if request.url.path == '/api/dispatch':
      return httpx.Response(200, json=[])
    if request.method == 'PUT' and request.url.path.startswith('/api/admin/users/'):
      return httpx.Response(200, json={})
    raise AssertionError((request.method, str(request.url)))

  originalClient = httpx.Client
  def isolatedClient(*args, **kwargs):
    return originalClient(*args, **kwargs, transport=httpx.MockTransport(respond), trust_env=False)
  monkeypatch.setattr(preparation.httpx, 'Client', isolatedClient)
  monkeypatch.setattr(preparation.sys.stdout, 'reconfigure', lambda **kwargs: None, raising=False)
  preparation.main()
  assert {duty['username'] for duty in sentDuties} == expectedUsers
