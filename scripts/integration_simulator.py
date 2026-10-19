"""本機外部工單模擬器；金鑰只讀取部署環境，不送入瀏覽器。"""
import argparse
import csv
import hashlib
import hmac
import io
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ReceiverInbox:
  def __init__(self, path, failFirst=0):
    self.path = str(path)
    self.failFirst = failFirst
    with sqlite3.connect(self.path) as db:
      db.execute('CREATE TABLE IF NOT EXISTS received (source TEXT, eventId TEXT, digest TEXT, payload BLOB, PRIMARY KEY(source,eventId))')
      db.execute('CREATE TABLE IF NOT EXISTS attempts (source TEXT, eventId TEXT, count INTEGER, PRIMARY KEY(source,eventId))')

  def accept(self, source, eventId, rawBody):
    digest = hashlib.sha256(rawBody).hexdigest()
    with sqlite3.connect(self.path) as db:
      db.execute('BEGIN IMMEDIATE')
      old = db.execute('SELECT digest FROM received WHERE source=? AND eventId=?', (source, eventId)).fetchone()
      if old:
        return 200 if hmac.compare_digest(old[0], digest) else 409
      db.execute('INSERT INTO attempts VALUES (?,?,1) ON CONFLICT(source,eventId) DO UPDATE SET count=count+1', (source, eventId))
      count = db.execute('SELECT count FROM attempts WHERE source=? AND eventId=?', (source, eventId)).fetchone()[0]
      if count <= self.failFirst:
        return 503
      db.execute('INSERT INTO received VALUES (?,?,?,?)', (source, eventId, digest, rawBody))
      return 200

  def count(self):
    with sqlite3.connect(self.path) as db:
      return db.execute('SELECT COUNT(*) FROM received').fetchone()[0]


def receiverHandler(inbox, allowedSource):
  from backend.integration_service import IDENTIFIER, signature, sourceConfig

  class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
      return

    def do_POST(self):
      if self.path != '/events':
        self.send_error(404)
        return
      try:
        length = int(self.headers.get('Content-Length', '0'))
        if not 1 <= length <= 16384:
          self.send_error(413)
          return
        self.connection.settimeout(5)
        rawBody = self.rfile.read(length)
        source = self.headers.get('X-Integration-Source', '')
        keyId = self.headers.get('X-Integration-Key', '')
        eventId = self.headers.get('X-Integration-Event', '')
        timestamp = self.headers.get('X-Integration-Timestamp', '')
        if (source != allowedSource or not all(re.fullmatch(IDENTIFIER, part) for part in [source, keyId, eventId])
            or not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > 12
            or abs(time.time() - int(timestamp)) > 300):
          raise ValueError()
        secret = sourceConfig(source)['keys'].get(keyId)
        if not isinstance(secret, str) or len(secret) < 32:
          raise ValueError()
        expected = signature(rawBody, source, keyId, timestamp, eventId, secret, path='/events')
        supplied = self.headers.get('X-Integration-Signature', '')
        if not re.fullmatch(r'[a-f0-9]{64}', supplied) or not hmac.compare_digest(expected, supplied):
          raise ValueError()
        if json.loads(rawBody).get('eventId') != eventId:
          raise ValueError()
        status = inbox.accept(source, eventId, rawBody)
      except Exception:
        status = 401
      response = json.dumps({'status': status}).encode()
      self.send_response(status)
      self.send_header('Content-Type', 'application/json')
      self.send_header('Content-Length', str(len(response)))
      self.end_headers()
      self.wfile.write(response)

  return Handler


def samplePayload(externalId, eventId, machineCode):
  return {'externalId': externalId, 'eventId': eventId, 'version': 1, 'machineCode': machineCode,
    'alarm': 'SIM-ALARM', 'symptoms': '模擬工單：主軸異音待檢查',
    'occurredAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat()}


def runSend(args):
  import httpx
  from backend.integration_service import INBOUND_PATH, jsonText, signature, sourceConfig
  target = urlparse(args.target)
  if (target.scheme != 'http' or target.hostname not in ['127.0.0.1', 'localhost', '::1']
      or target.path not in ['', '/'] or target.username or target.password or target.query or target.fragment):
    raise SystemExit('Simulator target must be an explicit localhost HTTP origin')
  config = sourceConfig(args.source)
  keyId = args.key or next(iter(config['keys']))
  secret = config['keys'][keyId]
  data = samplePayload(args.external_id, args.event_id, args.machine_code)
  if args.scenario == 'unknown':
    data['machineCode'] = 'UNKNOWN-' + hashlib.sha256(args.external_id.encode()).hexdigest()[:16]
  if args.scenario == 'missing':
    del data['symptoms']
  if args.scenario == 'out-of-order':
    data['version'] = 3
  events = [data]
  if args.scenario == 'update':
    events += [{**data, 'eventId': args.event_id + '-v2', 'version': 2, 'symptoms': '模擬更新：異音持續'}]
  if args.scenario == 'replay':
    events += [data]
  with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
    for event in events:
      rawBody = jsonText(event).encode('utf-8')
      timestamp = str(int(time.time()) - (600 if args.scenario == 'expired' else 0))
      digest = signature(rawBody, args.source, keyId, timestamp, event['eventId'], secret)
      if args.scenario == 'bad-signature':
        digest = '0' * 64
      headers = {'Content-Type': 'application/json', 'X-Integration-Source': args.source,
        'X-Integration-Key': keyId, 'X-Integration-Timestamp': timestamp, 'X-Integration-Event': event['eventId'],
        'X-Integration-Signature': digest}
      response = client.post(args.target.rstrip('/') + INBOUND_PATH, content=rawBody, headers=headers)
      print(json.dumps({'scenario': args.scenario, 'eventId': event['eventId'], 'httpStatus': response.status_code,
        'result': response.json()}, ensure_ascii=True))


def main():
  parser = argparse.ArgumentParser(description='Local external work order simulator')
  commands = parser.add_subparsers(dest='command', required=True)
  send = commands.add_parser('send')
  send.add_argument('--target', required=True)
  send.add_argument('--source', required=True)
  send.add_argument('--key')
  send.add_argument('--external-id', default='SIM-001')
  send.add_argument('--event-id', default='SIM-EVENT-001')
  send.add_argument('--machine-code', default='SIM-CNC-01')
  send.add_argument('--scenario', choices=['normal', 'replay', 'update', 'out-of-order', 'missing', 'bad-signature', 'expired', 'unknown'], default='normal')
  receiver = commands.add_parser('receiver')
  receiver.add_argument('--source', required=True)
  receiver.add_argument('--port', type=int, default=8097)
  receiver.add_argument('--db', type=Path, required=True)
  receiver.add_argument('--fail-first', type=int, default=0)
  csvCommand = commands.add_parser('csv')
  csvCommand.add_argument('--external-id', default='SIM-CSV-001')
  csvCommand.add_argument('--event-id', default='SIM-CSV-EVENT-001')
  csvCommand.add_argument('--machine-code', default='SIM-CNC-01')
  args = parser.parse_args()
  if args.command == 'send':
    runSend(args)
  elif args.command == 'receiver':
    if not 1024 <= args.port <= 65535 or not 0 <= args.fail_first <= 100:
      parser.error('port must be 1024..65535 and fail-first must be 0..100')
    args.db.parent.mkdir(parents=True, exist_ok=True)
    inbox = ReceiverInbox(args.db, args.fail_first)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), receiverHandler(inbox, args.source))
    print('Local receiver ready on 127.0.0.1:' + str(args.port), flush=True)
    try:
      server.serve_forever()
    except KeyboardInterrupt:
      pass
    finally:
      server.server_close()
  else:
    data = samplePayload(args.external_id, args.event_id, args.machine_code)
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=list(data))
    writer.writeheader()
    writer.writerows([data, data])
    sys.stdout.buffer.write(buffer.getvalue().encode('utf-8-sig'))


if __name__ == '__main__':
  main()
