"""服務入口與主管管理 API；服務不取得任何使用者角色。"""
import csv
import io
import json

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import auth, repair_flow, store
from .integration_models import ExternalOrder, InboundEvent, MachineMapping, Outbox
from .integration_service import (IDENTIFIER, audit, boundedBody, installOutboxHook, jsonText,
  lockTransaction, orderResult, receiveEvent, resolveOrder, sourceConfig)


class MappingInput(BaseModel):
  model_config = ConfigDict(extra='forbid')
  source: str = Field(pattern=IDENTIFIER, max_length=60)
  machineCode: str = Field(pattern=IDENTIFIER, max_length=60)
  machineId: str = Field(min_length=1, max_length=30)


def outboxResult(row):
  return {'id': row.id, 'eventId': row.eventId, 'source': row.source, 'ticketId': row.ticketId,
    'payload': json.loads(row.payload), 'state': row.state, 'attempts': row.attempts,
    'nextAttempt': row.nextAttempt, 'leaseUntil': row.leaseUntil, 'lastError': row.lastError}


def register(app):
  installOutboxHook()

  @app.post('/api/integrations/work-orders')
  def inbound(request: Request):
    principal = getattr(request.state, 'integrationPrincipal', None)
    if not principal:
      raise HTTPException(401, '缺少介接服務驗證')
    with store.Session() as db:
      lockTransaction(db)
      try:
        result = receiveEvent(db, principal['source'], request.state.integrationBody, principal['eventId'])
        db.commit()
        return result
      except IntegrityError:
        db.rollback()
        raise HTTPException(409, '介接資料已由其他交易處理，請重送事件') from None

  @app.get('/api/integrations/mappings')
  def mappings(request: Request, limit: int = Query(default=200, ge=1, le=1000), offset: int = Query(default=0, ge=0)):
    auth.supervisor(request)
    with store.Session() as db:
      rows = db.scalars(select(MachineMapping).order_by(MachineMapping.id).offset(offset).limit(limit))
      return [{'source': row.source, 'machineCode': row.machineCode, 'machineId': row.machineId} for row in rows]

  @app.put('/api/integrations/mappings')
  def putMapping(body: MappingInput, request: Request):
    auth.supervisor(request)
    sourceConfig(body.source)
    with store.Session() as db:
      lockTransaction(db)
      repair_flow.machine(db, body.machineId)
      row = db.scalar(select(MachineMapping).where(MachineMapping.source == body.source,
        MachineMapping.machineCode == body.machineCode).with_for_update())
      if row is None:
        db.add(MachineMapping(**body.model_dump()))
      else:
        row.machineId = body.machineId
      audit(db, 'integration_mapping', {**body.model_dump(), 'actor': request.state.user['username']})
      db.commit()
    return body.model_dump()

  @app.get('/api/integrations/records')
  def records(request: Request, limit: int = Query(default=200, ge=1, le=1000), offset: int = Query(default=0, ge=0)):
    auth.supervisor(request)
    with store.Session() as db:
      orders = db.scalars(select(ExternalOrder).order_by(ExternalOrder.id.desc()).offset(offset).limit(limit)).all()
      events = db.scalars(select(InboundEvent).order_by(InboundEvent.id.desc()).offset(offset).limit(limit)).all()
      return {'orders': [{'id': row.id, **orderResult(row), 'machineCode': row.machineCode,
        'latestPayload': json.loads(row.payload)} for row in orders],
        'events': [{'source': row.source, 'eventId': row.eventId, 'payloadHash': row.payloadHash,
          'receivedAt': row.receivedAt, 'result': json.loads(row.result)} for row in events]}

  @app.post('/api/integrations/orders/{orderId}/resolve')
  def resolve(orderId: int, request: Request):
    auth.supervisor(request)
    with store.Session() as db:
      lockTransaction(db)
      row = db.scalar(select(ExternalOrder).where(ExternalOrder.id == orderId).with_for_update())
      if row is None:
        raise HTTPException(404, '外部工單不存在')
      result = resolveOrder(db, row)
      if not result['ticketId']:
        raise HTTPException(409, '請先建立有效機台映射')
      audit(db, 'integration_resolved', {**result, 'actor': request.state.user['username']})
      db.commit()
      return result

  @app.get('/api/integrations/outbox')
  def outbox(request: Request, limit: int = Query(default=200, ge=1, le=1000), offset: int = Query(default=0, ge=0)):
    auth.supervisor(request)
    with store.Session() as db:
      return [outboxResult(row) for row in db.scalars(select(Outbox).order_by(Outbox.id).offset(offset).limit(limit))]

  @app.post('/api/integrations/outbox/{outboxId}/retry')
  def retry(outboxId: int, request: Request):
    auth.supervisor(request)
    with store.Session() as db:
      lockTransaction(db)
      row = db.scalar(select(Outbox).where(Outbox.id == outboxId).with_for_update())
      if row is None:
        raise HTTPException(404, '待送事件不存在')
      if row.state != 'dead':
        raise HTTPException(409, '只有 dead-letter 可人工重試')
      audit(db, 'integration_retry', {'outboxId': row.id, 'priorAttempts': row.attempts,
        'actor': request.state.user['username']})
      row.state, row.attempts, row.nextAttempt = 'pending', 0, 0
      row.leaseToken, row.leaseUntil, row.lastError = '', 0, ''
      db.commit()
      return outboxResult(row)

  @app.post('/api/integrations/csv')
  async def importCsv(request: Request, source: str = Query(max_length=60), dryRun: bool = True):
    auth.supervisor(request)
    sourceConfig(source)
    rawBody = await boundedBody(request, 262144)
    try:
      text = rawBody.decode('utf-8-sig')
      reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
      required = {'externalId', 'eventId', 'version', 'machineCode', 'alarm', 'symptoms', 'occurredAt'}
      if not reader.fieldnames or set(reader.fieldnames) != required or len(reader.fieldnames) != len(required):
        raise ValueError()
      rows = list(reader)
      if not rows or len(rows) > 200:
        raise ValueError()
    except (UnicodeError, ValueError, csv.Error):
      raise HTTPException(422, 'CSV 必須是 UTF-8、正確七欄且包含 1 至 200 列') from None
    results = []
    with store.Session() as db:
      lockTransaction(db)
      for index, row in enumerate(rows, start=2):
        try:
          with db.begin_nested():
            if set(row) != required or any(value is None for value in row.values()):
              raise HTTPException(422, 'CSV 列的欄位數不符')
            if (not isinstance(row.get('version'), str) or not 1 <= len(row['version']) <= 10
                or not row['version'].isascii() or not row['version'].isdigit()):
              raise HTTPException(422, 'version 必須是正整數')
            row['version'] = int(row['version'])
            result = receiveEvent(db, source, jsonText(row).encode('utf-8'))
            results.append({'row': index, 'ok': True, 'result': result})
        except (HTTPException, IntegrityError) as error:
          status = error.status_code if isinstance(error, HTTPException) else 409
          detail = error.detail if isinstance(error, HTTPException) else '資料衝突，請依序重送'
          results.append({'row': index, 'ok': False, 'status': status, 'error': detail})
      if dryRun:
        db.rollback()
      else:
        audit(db, 'integration_csv', {'source': source, 'actor': request.state.user['username'],
          'accepted': sum(row['ok'] for row in results), 'failed': sum(not row['ok'] for row in results)})
        db.commit()
    return {'dryRun': dryRun, 'rows': results}
