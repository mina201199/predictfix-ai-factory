"""驗簽、正規化與交易內的工單介接；不執行外部網路呼叫。"""
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import event, inspect, select, text

from . import repair_flow, store
from .integration_models import ExternalOrder, InboundEvent, MachineMapping, Outbox

INBOUND_PATH = '/api/integrations/work-orders'
MAX_BODY = 16384
IDENTIFIER = r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,59}$'


def sourceConfig(source):
  try:
    sources = json.loads(os.environ.get('INTEGRATION_SOURCES', '{}'))
    result = sources.get(source)
    if not isinstance(result, dict) or not isinstance(result.get('keys'), dict):
      raise ValueError()
    return result
  except (ValueError, TypeError, AttributeError):
    raise HTTPException(401, '介接來源或驗證資訊無效') from None


def canonicalPrefix(method, path, source, keyId, timestamp, eventId):
  return f'v1\n{method}\n{path}\n{source}\n{keyId}\n{timestamp}\n{eventId}\n'.encode('utf-8')


def signature(rawBody, source, keyId, timestamp, eventId, secret, method='POST', path=INBOUND_PATH):
  return hmac.new(secret.encode('utf-8'), canonicalPrefix(method, path, source, keyId, timestamp, eventId) + rawBody,
    hashlib.sha256).hexdigest()


async def boundedBody(request, limit):
  chunks = bytearray()
  async for chunk in request.stream():
    if len(chunks) + len(chunk) > limit:
      raise HTTPException(413, '介接資料超過大小限制')
    chunks.extend(chunk)
  return bytes(chunks)


async def verifyRequest(request):
  rawBody = await boundedBody(request, MAX_BODY)
  source = request.headers.get('x-integration-source', '')
  keyId = request.headers.get('x-integration-key', '')
  timestamp = request.headers.get('x-integration-timestamp', '')
  eventId = request.headers.get('x-integration-event', '')
  supplied = request.headers.get('x-integration-signature', '')
  try:
    if not all(re.fullmatch(IDENTIFIER, part, flags=re.ASCII) for part in [source, keyId, eventId]):
      raise ValueError()
    if not re.fullmatch(r'[0-9]{1,12}', timestamp) or abs(time.time() - int(timestamp)) > 300:
      raise ValueError()
    secret = sourceConfig(source)['keys'].get(keyId)
    if not isinstance(secret, str) or len(secret) < 32:
      raise ValueError()
    expected = signature(rawBody, source, keyId, timestamp, eventId, secret)
    if not re.fullmatch(r'[a-f0-9]{64}', supplied) or not hmac.compare_digest(expected, supplied):
      raise ValueError()
  except (ValueError, TypeError):
    raise HTTPException(401, '介接來源或驗證資訊無效') from None
  request.state.integrationPrincipal = {'source': source, 'keyId': keyId, 'eventId': eventId}
  request.state.integrationBody = rawBody


class WorkOrderInput(BaseModel):
  model_config = ConfigDict(extra='forbid', strict=True)
  externalId: str = Field(pattern=IDENTIFIER, max_length=60)
  eventId: str = Field(pattern=IDENTIFIER, max_length=60)
  version: int = Field(ge=1, le=2147483647)
  machineCode: str = Field(pattern=IDENTIFIER, max_length=60)
  alarm: str = Field(default='', max_length=200)
  symptoms: str = Field(min_length=3, max_length=160)
  occurredAt: str = Field(max_length=40)

  @field_validator('symptoms')
  @classmethod
  def nonblank(cls, value):
    if len(value.strip()) < 3:
      raise ValueError('症狀不可空白')
    return value.strip()

  @field_validator('occurredAt')
  @classmethod
  def zonedTime(cls, value):
    timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
      raise ValueError('發生時間須包含時區')
    try:
      return timestamp.astimezone(timezone.utc).isoformat()
    except OverflowError:
      raise ValueError('發生時間超出可轉換範圍') from None


def normalize(rawBody):
  try:
    return WorkOrderInput.model_validate_json(rawBody)
  except ValidationError:
    raise HTTPException(422, '工單欄位、長度或時間格式無效') from None


def jsonText(value):
  return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def audit(db, kind, data):
  db.add(store.Audit(kind=kind, request_id=uuid.uuid4().hex, payload=jsonText(data)))


def lockTransaction(db):
  # SQLite 的寫入鎖必須先於讀取，否則併發重送可能同時判定不存在。
  if db.bind.dialect.name == 'sqlite':
    db.connection().exec_driver_sql('BEGIN IMMEDIATE')


def lockExternalOrder(db, source, externalId):
  # 新工單尚無資料列可鎖定，必須先依來源與外部編號序列化事件。
  if db.bind.dialect.name == 'postgresql':
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'), {'key': source + '\n' + externalId})


def orderResult(order):
  return {'orderId': order.id, 'source': order.source, 'externalId': order.externalId,
    'version': order.version, 'ticketId': order.ticketId, 'state': 'linked' if order.ticketId else 'pending',
    'reason': order.reason}


def enqueue(db, order, ticket):
  eventId = 'OUT-' + uuid.uuid4().hex
  payload = {'eventId': eventId, 'source': order.source, 'externalId': order.externalId,
    'ticketId': ticket.id, 'externalVersion': order.version, 'status': ticket.status, 'engineer': ticket.engineer}
  db.add(Outbox(eventId=eventId, source=order.source, ticketId=ticket.id, payload=jsonText(payload)))


def resolveOrder(db, order):
  if order.ticketId:
    return orderResult(order)
  mapping = db.scalar(select(MachineMapping).where(MachineMapping.source == order.source,
    MachineMapping.machineCode == order.machineCode))
  machine = db.get(store.Machine, mapping.machineId) if mapping else None
  if not machine or not machine.active:
    order.reason = 'unknown_machine_code' if not mapping else 'mapped_machine_inactive'
    return orderResult(order)
  machineData = repair_flow.machine(db, machine.id)
  data = json.loads(order.payload)
  ticket = store.Ticket(id='WO-' + uuid.uuid4().hex[:12].upper(), machine=machine.id,
    issue=data['symptoms'], engineer='待指派', status='待指派',
    request_key='integration:' + str(order.id))
  order.ticketId = ticket.id
  order.reason = ''
  context = {'machine': machine.id, 'machine_model': machineData.get('machine_model', ''),
    'symptoms': data['symptoms'], 'alarm': data['alarm'], 'component': '', 'conditions': '',
    'recent_change': '', 'scope': '', 'previous_checks': ''}
  db.add_all([ticket, store.Workflow(id=ticket.id, payload=jsonText({'report_context': context,
    'integration': {'source': order.source, 'externalId': order.externalId, 'orderId': order.id}}))])
  enqueue(db, order, ticket)
  audit(db, 'integration_linked', orderResult(order))
  return orderResult(order)


def receiveEvent(db, source, rawBody, expectedEvent=None):
  sourceConfig(source)
  data = normalize(rawBody)
  if expectedEvent is not None and data.eventId != expectedEvent:
    raise HTTPException(422, '事件標頭與工單事件不一致')
  lockExternalOrder(db, source, data.externalId)
  digest = hashlib.sha256(rawBody).hexdigest()
  existing = db.scalar(select(InboundEvent).where(InboundEvent.source == source, InboundEvent.eventId == data.eventId))
  if existing:
    if existing.payloadHash != digest:
      raise HTTPException(409, '相同事件 ID 的內容不同')
    return json.loads(existing.result)
  order = db.scalar(select(ExternalOrder).where(ExternalOrder.source == source,
    ExternalOrder.externalId == data.externalId).with_for_update())
  if data.version != (order.version + 1 if order else 1):
    raise HTTPException(409, '外部版本必須從 1 依序遞增')
  if order and order.machineCode != data.machineCode:
    raise HTTPException(409, '既有外部工單不可改變機台代號')
  if order is None:
    order = ExternalOrder(source=source, externalId=data.externalId, version=0,
      machineCode=data.machineCode, payload='{}', reason='')
    db.add(order)
    db.flush()
  order.version = data.version
  order.payload = jsonText(data.model_dump())
  result = resolveOrder(db, order)
  db.add(InboundEvent(source=source, eventId=data.eventId, payloadHash=digest, result=jsonText(result), receivedAt=time.time()))
  audit(db, 'integration_received', {'source': source, 'eventId': data.eventId, 'payloadHash': digest, **result})
  db.flush()
  return result


def installOutboxHook():
  if event.contains(store.Session, 'before_flush', captureChanges):
    return
  event.listen(store.Session, 'before_flush', captureChanges)


def captureChanges(db, flushContext, instances):
  # 只觀察 ORM 工單狀態與人員變更，所有送出資料都與原交易一起成功或回滾。
  tickets = [row for row in db.dirty if isinstance(row, store.Ticket)]
  for ticket in tickets:
    state = inspect(ticket)
    if not (state.attrs.status.history.has_changes() or state.attrs.engineer.history.has_changes()):
      continue
    order = db.scalar(select(ExternalOrder).where(ExternalOrder.ticketId == ticket.id))
    if order:
      enqueue(db, order, ticket)
      audit(db, 'integration_status', {'ticketId': ticket.id, 'status': ticket.status, 'engineer': ticket.engineer})
