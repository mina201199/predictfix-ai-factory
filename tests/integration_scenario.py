"""所有 secret、帳號與 transport 均為隔離 fixture，不連企業或 LLM。"""
import csv
import hashlib
import hmac
import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from backend.app import app
from backend import store

SECRET = 'ISOLATED-FAKE-HMAC-FIXTURE-NOT-A-REAL-KEY'
SOURCES = {'fixture': {'keys': {'k1': SECRET}, 'outboundUrl': 'http://127.0.0.1:9998/events', 'allowHttp': True}}
PATH = '/api/integrations/work-orders'
PASSWORD = os.environ['BOOTSTRAP_PASSWORD']


def encode(body):
  return json.dumps(body, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()


def body(**changes):
  return {'externalId': 'EXT-1', 'eventId': 'EVT-1', 'version': 1, 'machineCode': 'LATHE-1',
    'alarm': 'AL-01', 'symptoms': '主軸出現異音', 'occurredAt': '2026-10-19T08:00:00+08:00', **changes}


def signed(raw, eventId='EVT-1', timestamp=None, secret=SECRET, source='fixture', key='k1'):
  timestamp = str(int(time.time()) if timestamp is None else timestamp)
  prefix = f'v1\nPOST\n{PATH}\n{source}\n{key}\n{timestamp}\n{eventId}\n'.encode()
  return {'Content-Type': 'application/json', 'X-Integration-Source': source, 'X-Integration-Key': key,
    'X-Integration-Timestamp': timestamp, 'X-Integration-Event': eventId,
    'X-Integration-Signature': hmac.new(secret.encode(), prefix + raw, hashlib.sha256).hexdigest()}


def send(client, data=None, **kwargs):
  data = body() if data is None else data
  raw = encode(data)
  return client.post(PATH, content=raw, headers=signed(raw, data['eventId'], **kwargs))


def checked(response, code=200):
  assert response.status_code == code, response.text
  return response.json()


def login(client, username):
  result = checked(client.post('/api/auth/login', json={'username': username, 'password': PASSWORD}))
  client.headers['X-CSRF-Token'] = result['csrf']


@pytest.fixture(scope='module')
def clients():
  with patch.dict(os.environ, {'INTEGRATION_SOURCES': json.dumps(SOURCES)}), TestClient(app) as supervisor:
    login(supervisor, 'supervisor')
    checked(supervisor.post('/api/machines', json={'id': 'INT-01', 'name': '介接隔離測試機',
      'kind': 'mill', 'machine_model': 'INT-MODEL'}), 201)
    checked(supervisor.post('/api/admin/users', json={'username': 'inttech', 'name': '介接工程師',
      'role': 'engineer', 'password': PASSWORD}), 201)
    with TestClient(app) as engineer, TestClient(app) as anonymous:
      login(engineer, 'inttech')
      yield supervisor, engineer, anonymous


@pytest.fixture
def c(clients):
  from backend.integration_models import ExternalOrder, InboundEvent, MachineMapping, Outbox
  with store.Session() as db:
    for table in [Outbox, InboundEvent, ExternalOrder, MachineMapping, store.Ticket, store.Workflow]:
      db.execute(delete(table))
    db.commit()
  return clients[0]


def mapping(client, code='LATHE-1'):
  return checked(client.put('/api/integrations/mappings', json={'source': 'fixture',
    'machineCode': code, 'machineId': 'INT-01'}))


def records(client):
  return checked(client.get('/api/integrations/records'))


def outbox(client):
  return checked(client.get('/api/integrations/outbox'))


def test_exact_machine_route_does_not_require_browser_login(clients):
  response = send(clients[2])
  assert response.status_code == 200, response.text


@pytest.mark.parametrize('variation', ['body', 'secret', 'source', 'key', 'expired', 'future', 'event'])
def test_hmac_rejects_tampering_and_inactive_keys(c, variation):
  raw = encode(body())
  headers = signed(raw, timestamp=1000)
  if variation == 'body':
    raw += b' '
  if variation == 'secret':
    headers = signed(raw, secret='ISOLATED-INCORRECT-SECRET', timestamp=1000)
  if variation == 'source':
    headers = signed(raw, source='unknown', timestamp=1000)
  if variation == 'key':
    headers = signed(raw, key='revoked', timestamp=1000)
  if variation in ['expired', 'future']:
    headers = signed(raw, timestamp=1000 + (301 if variation == 'future' else -301))
  if variation == 'event':
    headers['X-Integration-Event'] = 'changed'
  with patch('backend.integration_service.time.time', return_value=1000):
    result = c.post(PATH, content=raw, headers=headers)
  assert result.status_code == 401
  assert SECRET not in result.text and 'ISOLATED-INCORRECT' not in result.text
  assert records(c)['events'] == []


def test_runtime_key_revocation(c):
  with patch.dict(os.environ, {'INTEGRATION_SOURCES': json.dumps({'fixture': {'keys': {}}})}):
    assert send(c).status_code == 401


@pytest.mark.parametrize('changes', [{'role': 'supervisor'}, {'engineer': '主管'}, {'status': '已完成'},
  {'callbackUrl': 'http://example.invalid'}, {'occurredAt': '2026-10-19T00:00:00'},
  {'symptoms': ' '}, {'version': True}, {'version': '1'}, {'machineCode': '../x'}, {'alarm': 'x' * 201}])
def test_payload_rejects_privilege_fields_and_invalid_data(c, changes):
  assert send(c, body(**changes)).status_code == 422
  assert records(c)['events'] == []


def test_size_and_missing_fields(c):
  raw = b'x' * 16385
  assert c.post(PATH, content=raw, headers=signed(raw)).status_code == 413
  data = body()
  del data['symptoms']
  assert send(c, data).status_code == 422


def test_duplicate_returns_original_result_and_conflict_does_not_create(c):
  mapping(c)
  result = checked(send(c))
  assert checked(send(c)) == result
  assert send(c, body(symptoms='另一種異常')).status_code == 409
  assert len(checked(c.get('/api/tickets'))) == 1
  assert len(records(c)['events']) == 1
  ticket = checked(c.get('/api/tickets'))[0]
  assert ticket['status'] == '待指派' and ticket['engineer'] == '待指派'
  assert ticket['workflow']['report_context']['alarm'] == 'AL-01'
  assert ticket['workflow']['integration']['externalId'] == 'EXT-1'


def test_concurrent_duplicate_creates_one_ticket(c):
  mapping(c)
  raw = encode(body())
  def attempt(index):
    with TestClient(app) as client:
      return client.post(PATH, content=raw, headers=signed(raw))
  with ThreadPoolExecutor(max_workers=6) as pool:
    results = list(pool.map(attempt, range(6)))
  assert all(r.status_code == 200 for r in results), [r.text for r in results]
  assert len({r.json()['ticketId'] for r in results}) == 1
  assert len(checked(c.get('/api/tickets'))) == 1


def test_version_ordering_and_update_preserve_internal_work(c):
  mapping(c)
  assert send(c, body(version=2)).status_code == 409
  result = checked(send(c))
  assert send(c, body(eventId='EVT-gap', version=3)).status_code == 409
  assert send(c, body(eventId='EVT-stale', version=1)).status_code == 409
  updated = checked(send(c, body(eventId='EVT-2', version=2, symptoms='更新外部症狀')))
  assert updated['ticketId'] == result['ticketId']
  assert checked(c.get('/api/tickets'))[0]['issue'] == '主軸出現異音'
  assert records(c)['orders'][0]['version'] == 2


def test_unknown_machine_resolution_once_and_inactive_mapping(c):
  first = checked(send(c))
  assert first['state'] == 'pending' and first['ticketId'] is None
  checked(send(c, body(eventId='EVT-2', version=2, symptoms='待對應最新內容')))
  assert len(checked(c.get('/api/tickets'))) == 0
  pending = records(c)['orders'][0]
  assert pending['reason']
  assert c.post('/api/integrations/orders/' + str(pending['id']) + '/resolve').status_code == 409
  mapping(c)
  url = '/api/integrations/orders/' + str(pending['id']) + '/resolve'
  a = checked(c.post(url))
  assert checked(c.post(url))['ticketId'] == a['ticketId']
  assert len(checked(c.get('/api/tickets'))) == 1
  assert checked(c.get('/api/tickets'))[0]['issue'] == '待對應最新內容'
  with store.Session() as db:
    db.get(store.Machine, 'INT-01').active = 0
    db.commit()
  try:
    assert checked(send(c, body(externalId='EXT-inactive', eventId='EVT-inactive')))['state'] == 'pending'
  finally:
    with store.Session() as db:
      db.get(store.Machine, 'INT-01').active = 1
      db.commit()


@pytest.mark.parametrize('method,path,data', [('GET', 'records', None), ('GET', 'mappings', None),
  ('GET', 'outbox', None), ('PUT', 'mappings', {'source': 'fixture', 'machineCode': 'X', 'machineId': 'INT-01'}),
  ('POST', 'orders/999/resolve', None), ('POST', 'outbox/999/retry', None), ('POST', 'csv?source=fixture', None)])
def test_management_permissions_and_csrf(c, clients, method, path, data):
  url = '/api/integrations/' + path
  assert clients[2].request(method, url, json=data).status_code == 401
  assert clients[1].request(method, url, json=data).status_code == 403
  if method != 'GET':
    assert c.request(method, url, json=data, headers={'X-CSRF-Token': ''}).status_code == 403


def csvBytes(rows, bom=False):
  text = io.StringIO(newline='')
  writer = csv.DictWriter(text, fieldnames=list(body()))
  writer.writeheader()
  writer.writerows(rows)
  return text.getvalue().encode('utf-8-sig' if bom else 'utf-8')


def test_csv_dry_run_bom_duplicate_and_per_row_errors(c):
  mapping(c)
  rows = [body(), body(), body(externalId='EXT-2', eventId='EVT-2', symptoms=' ')]
  raw = csvBytes(rows, True)
  dry = checked(c.post('/api/integrations/csv?source=fixture&dryRun=true', content=raw))
  assert [row['ok'] for row in dry['rows']] == [True, True, False]
  assert records(c)['events'] == [] and checked(c.get('/api/tickets')) == []
  real = checked(c.post('/api/integrations/csv?source=fixture&dryRun=false', content=raw))
  assert [row['ok'] for row in real['rows']] == [True, True, False]
  assert len(checked(c.get('/api/tickets'))) == 1
  repeated = checked(c.post('/api/integrations/csv?source=fixture&dryRun=false', content=raw))
  assert repeated['rows'][0]['result'] == real['rows'][0]['result']


@pytest.mark.parametrize('raw', [b'\xff', b'wrong,columns\na,b\n', b'x' * 262145,
  csvBytes([body(eventId='EVT-' + str(i), externalId='EXT-' + str(i)) for i in range(201)])],
  ids=['encoding', 'columns', 'size', 'row-count'])
def test_csv_limits(c, raw):
  assert c.post('/api/integrations/csv?source=fixture', content=raw).status_code in [413, 422]


def test_outbox_atomic_rollback_and_status_hook(c):
  from backend.integration_models import Outbox
  mapping(c)
  tid = checked(send(c))['ticketId']
  before = len(outbox(c))
  with store.Session() as db:
    db.get(store.Ticket, tid).status = '維修中'
    db.flush()
    assert len(db.scalars(select(Outbox)).all()) == before + 1
    db.rollback()
  assert len(outbox(c)) == before
  assert checked(c.get('/api/tickets'))[0]['status'] == '待指派'
  with store.Session() as db:
    db.get(store.Ticket, tid).status = '退回重修'
    db.commit()
  assert outbox(c)[-1]['payload']['status'] == '退回重修'


def test_worker_retry_dead_letter_and_manual_retry(c):
  from backend.integration_worker import runOnce
  mapping(c)
  checked(send(c))
  delivered = []
  def failed(request):
    delivered.append(request)
    assert request.headers['X-Integration-Signature']
    return httpx.Response(503, text='must-never-be-saved-SECRET')
  for timestamp in [1000, 1010, 1030, 1070, 1150]:
    assert runOnce(now=timestamp, transport=httpx.MockTransport(failed))
  row = outbox(c)[0]
  assert row['state'] == 'dead' and row['attempts'] == 5
  assert 'must-never' not in row['lastError']
  checked(c.post('/api/integrations/outbox/' + str(row['id']) + '/retry'))
  def success(request):
    delivered.append(request)
    return httpx.Response(200)
  assert runOnce(now=time.time() + 1, transport=httpx.MockTransport(success))
  assert outbox(c)[0]['state'] == 'sent'
  assert len({json.loads(r.content)['eventId'] for r in delivered}) == 1


def test_worker_restart_lease_and_no_network_inside_transaction(c):
  from backend.integration_worker import claimNext, runOnce
  mapping(c)
  tid = checked(send(c))['ticketId']
  claimed = claimNext(1000)
  assert claimed
  assert not runOnce(now=1020, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
  def recovered(request):
    with store.Session() as db:
      db.get(store.Ticket, tid).completion_note = '網路傳送時資料庫仍可寫入'
      db.commit()
    return httpx.Response(200)
  assert runOnce(now=1061, transport=httpx.MockTransport(recovered))
  assert outbox(c)[0]['state'] == 'sent' and outbox(c)[0]['attempts'] == 2


def test_outbox_order_blocks_later_events_and_redirects(c):
  from backend.integration_worker import runOnce
  mapping(c)
  tid = checked(send(c))['ticketId']
  with store.Session() as db:
    db.get(store.Ticket, tid).status = '維修中'
    db.commit()
  sent = []
  def redirect(request):
    sent.append(str(request.url))
    return httpx.Response(302, headers={'location': 'http://example.invalid/secret'})
  assert runOnce(now=1000, transport=httpx.MockTransport(redirect))
  assert not runOnce(now=1001, transport=httpx.MockTransport(redirect))
  assert sent == ['http://127.0.0.1:9998/events']
  assert outbox(c)[1]['attempts'] == 0


def test_disabled_destination_keeps_event(c):
  from backend.integration_worker import runOnce
  mapping(c)
  checked(send(c))
  with patch.dict(os.environ, {'INTEGRATION_SOURCES': json.dumps({'fixture': {'keys': {'k1': SECRET}}})}):
    assert runOnce(now=1000, transport=httpx.MockTransport(lambda r: pytest.fail('unexpected network')))
  assert outbox(c)[0]['state'] == 'pending'


def test_api_workflow_keeps_checklist_and_human_review(c, clients):
  mapping(c)
  tid = checked(send(c))['ticketId']
  checked(c.post('/api/duties', json={'username': 'inttech',
    'starts_at': (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    'ends_at': (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
    'attendance': 'present', 'capacity_minutes': 120, 'note': '隔離介接測試'}), 201)
  checked(c.patch('/api/tickets/' + tid + '/assign', json={'engineer': '介接工程師'}))
  engineer = clients[1]
  checked(engineer.post('/api/tickets/' + tid + '/start'))
  procedure = checked(c.put('/api/tickets/' + tid + '/procedure', json={'revision': 0,
    'machine_model': 'INT-MODEL', 'approval_note': '隔離主管核准程序', 'steps': [
      {'label': '核對異常來源', 'kind': 'inspect', 'criterion': '記錄檢查結果'},
      {'label': '維修後復測', 'kind': 'verify', 'criterion': '復測確認通過'}]}))['workflow']['procedure']
  assert engineer.post('/api/tickets/' + tid + '/complete', json={'note': '未填清單不得送審'}).status_code == 422
  def fillChecklist(procedure):
    checked(engineer.put('/api/tickets/' + tid + '/procedure/results', json={'revision': procedure['revision'],
      'results': [{'step_id': step['id'], 'outcome': 'pass', 'note': '隔離檢查結果正常'} for step in procedure['steps']]}))
  fillChecklist(procedure)
  assert engineer.post('/api/tickets/' + tid + '/review', json={'decision': 'approve', 'note': '不可以自行核准'}).status_code == 403
  checked(engineer.post('/api/tickets/' + tid + '/complete', json={'note': '隔離驗收紀錄完成'}))
  rework = checked(c.post('/api/tickets/' + tid + '/review', json={'decision': 'reject', 'note': '隔離退回確認'}))
  checked(engineer.post('/api/tickets/' + tid + '/start'))
  assert engineer.post('/api/tickets/' + tid + '/complete', json={'note': '退回後重新填清單'}).status_code == 422
  fillChecklist(rework['workflow']['procedure'])
  checked(engineer.post('/api/tickets/' + tid + '/complete', json={'note': '隔離複測完成確認'}))
  checked(c.post('/api/tickets/' + tid + '/review', json={'decision': 'approve', 'note': '隔離人工審核通過'}))
  states = [r['payload']['status'] for r in outbox(c)]
  assert states == ['待指派', '已指派', '維修中', '待主管審核', '退回重修', '維修中', '待主管審核', '已完成']


def test_ui_has_strict_csp_and_no_secrets(c):
  response = c.get('/integrations.html')
  assert response.status_code == 200
  assert "script-src 'self'" in response.headers['content-security-policy']
  for path in ['/integrations.js', '/integrations.css']:
    assert c.get(path).status_code == 200
  assert SECRET not in c.get('/integrations.js').text
  assert 'outboundUrl' not in c.get('/api/integrations/mappings').text


def test_csv_bad_row_shape_and_long_version_are_row_errors(c):
  raw = csvBytes([body()]).decode() + 'EXT-bad,EVT-bad,1,LATHE-1,,異常描述,2026-10-19T00:00:00Z,extra\n'
  result = checked(c.post('/api/integrations/csv?source=fixture&dryRun=false', content=raw.encode()))
  assert [row['ok'] for row in result['rows']] == [True, False]
  raw = csvBytes([body(eventId='EVT-huge', version='9' * 5000)])
  result = checked(c.post('/api/integrations/csv?source=fixture', content=raw))
  assert not result['rows'][0]['ok']


def test_hmac_cannot_access_supervisor_routes(clients):
  raw = encode(body())
  for method, path in [('GET', 'records'), ('PUT', 'mappings'), ('POST', 'outbox/1/retry')]:
    response = clients[2].request(method, '/api/integrations/' + path, content=raw, headers=signed(raw))
    assert response.status_code == 401


def test_simulator_receiver_deduplicates_across_restart(tmp_path):
  from scripts.integration_simulator import ReceiverInbox
  dbPath = tmp_path / 'receiver.db'
  data = {'eventId': 'OUT-fixture', 'status': '已完成'}
  raw = encode(data)
  first = ReceiverInbox(dbPath, failFirst=1)
  assert first.accept('fixture', 'OUT-fixture', raw) == 503
  assert ReceiverInbox(dbPath, failFirst=1).accept('fixture', 'OUT-fixture', raw) == 200
  assert ReceiverInbox(dbPath, failFirst=1).accept('fixture', 'OUT-fixture', raw) == 200
  assert ReceiverInbox(dbPath).accept('fixture', 'OUT-fixture', encode({**data, 'status': 'changed'})) == 409
  assert ReceiverInbox(dbPath).count() == 1


def test_worker_stale_ack_cannot_overwrite_new_lease(c):
  from backend.integration_worker import claimNext, runOnce
  mapping(c)
  checked(send(c))
  newer = []
  def delayed(request):
    newer.append(claimNext(1061))
    return httpx.Response(200)
  assert runOnce(now=1000, transport=httpx.MockTransport(delayed))
  assert newer[0] and outbox(c)[0]['state'] == 'sending'


def test_pending_resolve_race_and_initial_ingest_rollback(c):
  from backend.integration_models import ExternalOrder, InboundEvent, Outbox
  from backend.integration_service import lockTransaction, receiveEvent
  mapping(c)
  with store.Session() as db:
    lockTransaction(db)
    receiveEvent(db, 'fixture', encode(body()))
    db.rollback()
  with store.Session() as db:
    assert not db.scalars(select(ExternalOrder)).all()
    assert not db.scalars(select(InboundEvent)).all()
    assert not db.scalars(select(Outbox)).all()
    assert not db.scalars(select(store.Ticket)).all()
  pending = checked(send(c, body(machineCode='UNKNOWN')))
  mapping(c, 'UNKNOWN')
  def resolve(index):
    with TestClient(app) as client:
      client.cookies.update(c.cookies)
      client.headers['X-CSRF-Token'] = c.headers['X-CSRF-Token']
      return client.post('/api/integrations/orders/' + str(pending['orderId']) + '/resolve')
  with ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(resolve, range(4)))
  assert all(r.status_code == 200 for r in results)
  assert len({r.json()['ticketId'] for r in results}) == 1
  assert len(checked(c.get('/api/tickets'))) == 1


def test_env_loader_is_explicit_and_does_not_echo_secrets(tmp_path):
  from scripts.integration_run import loadSettings
  envFile = tmp_path / '.env'
  envFile.write_text('INTEGRATION_SOURCES=\'{"fixture":{"keys":{"k1":"ISOLATED-ENV-FIXTURE-SECRET"}}}\'\n', encoding='utf-8')
  with patch.dict(os.environ, {}, clear=True):
    loadSettings(envFile)
    assert json.loads(os.environ['INTEGRATION_SOURCES'])['fixture']['keys']['k1'] == 'ISOLATED-ENV-FIXTURE-SECRET'
  envFile.write_text('INVALID LINE WITH ISOLATED-ENV-FIXTURE-SECRET\n', encoding='utf-8')
  with pytest.raises(ValueError) as caught:
    loadSettings(envFile)
  assert 'ISOLATED-ENV' not in str(caught.value)


def test_crash_at_final_attempt_becomes_dead_without_losing_event(c):
  from backend.integration_models import Outbox
  from backend.integration_worker import runOnce
  mapping(c)
  checked(send(c))
  with store.Session() as db:
    row = db.scalar(select(Outbox))
    row.state, row.attempts, row.leaseUntil, row.leaseToken = 'sending', 5, 1000, 'crashed'
    db.commit()
  assert runOnce(now=1061, transport=httpx.MockTransport(lambda r: pytest.fail('sixth delivery')))
  assert outbox(c)[0]['state'] == 'dead' and outbox(c)[0]['attempts'] == 5


@pytest.mark.parametrize('occurredAt', ['0001-01-01T00:00:00+01:00', '9999-12-31T23:59:59-01:00'])
def test_date_overflow_is_validation_error_and_csv_keeps_valid_rows(c, occurredAt):
  assert send(c, body(occurredAt=occurredAt)).status_code == 422
  rows = [body(), body(externalId='EXT-bad-time', eventId='EVT-bad-time', occurredAt=occurredAt)]
  result = checked(c.post('/api/integrations/csv?source=fixture&dryRun=false', content=csvBytes(rows)))
  assert [row['ok'] for row in result['rows']] == [True, False]
  assert result['rows'][1]['status'] == 422
  assert len(records(c)['events']) == 1


def test_simulator_unknown_uses_order_specific_machine_code(c):
  from scripts.integration_simulator import runSend
  from types import SimpleNamespace
  deliveries = []
  def capture(request):
    deliveries.append(json.loads(request.content))
    return httpx.Response(200, json={'state': 'pending'})
  args = SimpleNamespace(target='http://127.0.0.1:8096', source='fixture', key='k1',
    external_id='SIM-UNIQUE-ORDER', event_id='SIM-UNIQUE-EVENT', machine_code='SIM-CNC-01', scenario='unknown')
  client = httpx.Client(transport=httpx.MockTransport(capture))
  with patch('httpx.Client', return_value=client):
    runSend(args)
  assert deliveries[0]['machineCode'] == 'UNKNOWN-' + hashlib.sha256(args.external_id.encode()).hexdigest()[:16]


def test_concurrent_csv_reverse_order_does_not_deadlock(c, monkeypatch):
  import threading
  from backend import integration_service
  mapping(c)
  rows = [body(externalId='CSV-A', eventId='CSV-EVENT-A'), body(externalId='CSV-B', eventId='CSV-EVENT-B')]
  originalLock = integration_service.lockExternalOrder
  state = threading.local()
  def interleavedLock(*args):
    originalLock(*args)
    if not getattr(state, 'paused', False):
      state.paused = True
      # 放大首列已持鎖的交錯時間，才能驗證整批鎖順序。
      time.sleep(0.2)
  monkeypatch.setattr(integration_service, 'lockExternalOrder', interleavedLock)
  with TestClient(app, raise_server_exceptions=False) as first, TestClient(app, raise_server_exceptions=False) as second:
    for client in [first, second]:
      client.cookies.update(c.cookies)
      client.headers['X-CSRF-Token'] = c.headers['X-CSRF-Token']
    def importRows(arguments):
      client, items = arguments
      return client.post('/api/integrations/csv?source=fixture&dryRun=false', content=csvBytes(items))
    with ThreadPoolExecutor(max_workers=2) as pool:
      responses = list(pool.map(importRows, [(first, rows), (second, list(reversed(rows)))]))
    for response in responses:
      assert response.status_code == 200, (response.status_code, response.text)
      assert all(row['ok'] for row in response.json()['rows']), response.text
  assert len(records(c)['orders']) == 2
  assert len(records(c)['events']) == 2
