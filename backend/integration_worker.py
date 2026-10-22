"""可重新啟動的至少一次傳遞 worker：python -m backend.integration_worker --once。"""
import argparse
import json
import time
import uuid
from urllib.parse import urlparse

import httpx
from sqlalchemy import exists, select, update
from sqlalchemy.orm import aliased

from . import store
from .integration_models import Outbox
from .integration_service import audit, lockTransaction, signature, sourceConfig


def claimNext(now):
  with store.Session() as db:
    lockTransaction(db)
    prior = aliased(Outbox)
    blocked = exists(select(prior.id).where(prior.ticketId == Outbox.ticketId,
      prior.id < Outbox.id, prior.state != 'sent'))
    row = db.scalar(select(Outbox).where(Outbox.state.in_(['pending', 'sending']),
      Outbox.nextAttempt <= now, Outbox.leaseUntil <= now, ~blocked)
      .order_by(Outbox.id).with_for_update(skip_locked=True).limit(1))
    if row is None:
      return None
    if row.attempts >= 5:
      row.state, row.leaseToken, row.leaseUntil = 'dead', '', 0
      row.lastError = 'lease_exhausted'
      audit(db, 'integration_delivery', {'outboxId': row.id, 'eventId': row.eventId,
        'attempts': row.attempts, 'result': 'lease_exhausted'})
      db.commit()
      return {'exhausted': True}
    row.state = 'sending'
    row.leaseToken = uuid.uuid4().hex
    row.leaseUntil = now + 60
    row.attempts += 1
    db.commit()
    return {'id': row.id, 'source': row.source, 'eventId': row.eventId, 'payload': row.payload,
      'leaseToken': row.leaseToken, 'attempts': row.attempts}


def destination(config):
  url = config.get('outboundUrl', '')
  if not isinstance(url, str):
    raise ValueError()
  parsed = urlparse(url)
  if (parsed.scheme not in ['https', 'http'] or not parsed.hostname or parsed.username or parsed.password
      or parsed.fragment or parsed.query or (parsed.scheme == 'http' and config.get('allowHttp') is not True)):
    raise ValueError()
  return url, parsed.path or '/'


def runOnce(now=None, transport=None):
  timestamp = time.time() if now is None else now
  row = claimNext(timestamp)
  if row is None:
    return False
  if row.get('exhausted'):
    return True
  error = ''
  try:
    config = sourceConfig(row['source'])
    url, path = destination(config)
    keyId = config.get('outboundKeyId') or next(iter(config['keys']))
    secret = config['keys'][keyId]
    if not isinstance(secret, str) or len(secret) < 32:
      raise ValueError()
    rawBody = row['payload'].encode('utf-8')
    stamp = str(int(timestamp))
    headers = {'Content-Type': 'application/json', 'X-Integration-Source': row['source'],
      'X-Integration-Key': keyId, 'X-Integration-Timestamp': stamp, 'X-Integration-Event': row['eventId'],
      'X-Integration-Signature': signature(rawBody, row['source'], keyId, stamp, row['eventId'], secret, path=path)}
    # claim 已提交，避免外部故障把工單資料庫長時間鎖住。
    with httpx.Client(timeout=5, follow_redirects=False, trust_env=False, transport=transport) as client:
      response = client.post(url, content=rawBody, headers=headers)
      if not 200 <= response.status_code < 300:
        error = 'http_status_' + str(response.status_code)
  except Exception:
    # HTTP 回應與例外訊息可能含目的地、憑證或外部資料，只保存固定錯誤代號。
    error = 'destination_or_transport_error'
  with store.Session() as db:
    result = db.execute(update(Outbox).where(Outbox.id == row['id'], Outbox.leaseToken == row['leaseToken'],
      Outbox.state == 'sending').values(state=('dead' if row['attempts'] >= 5 else 'pending') if error else 'sent',
      nextAttempt=timestamp + min(3600, 10 * 2 ** min(9, row['attempts'] - 1)) if error else 0,
      leaseToken='', leaseUntil=0, lastError=error))
    if result.rowcount:
      audit(db, 'integration_delivery', {'outboxId': row['id'], 'eventId': row['eventId'],
        'attempts': row['attempts'], 'result': error or 'sent'})
    db.commit()
  return True


def main():
  parser = argparse.ArgumentParser(description='Vulkrion integration outbox worker')
  parser.add_argument('--once', action='store_true')
  args = parser.parse_args()
  store.init()
  if args.once:
    print(json.dumps({'processed': runOnce()}))
    return
  try:
    while True:
      if not runOnce():
        time.sleep(1)
  except KeyboardInterrupt:
    return


if __name__ == '__main__':
  main()
