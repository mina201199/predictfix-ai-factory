"""Standard-library smoke check, usable on a clean CI runner."""
import argparse
import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

parser=argparse.ArgumentParser()
parser.add_argument('--url',default='http://127.0.0.1:18083')
args=parser.parse_args()
if urlparse(args.url).hostname not in ['127.0.0.1','localhost']:raise SystemExit('Local smoke checks only')
ready=None
for _ in range(45):
    try:
        with urllib.request.urlopen(args.url+'/healthz',timeout=2) as response:ready=json.load(response)
        break
    except (urllib.error.URLError,TimeoutError):time.sleep(1)
assert ready and ready['mode']=='production',ready
for path in ['/','/console.js','/workflow.html','/workflow.js','/workflow.css','/knowledge.html','/docs']:
    with urllib.request.urlopen(args.url+path,timeout=5) as response:
        assert response.status==200,path
with urllib.request.urlopen(args.url+'/api/auth/config') as response:
    assert json.load(response)['demo_mode'] is False
try:
    urllib.request.urlopen(args.url+'/api/tickets')
    raise AssertionError('Anonymous operational access must fail')
except urllib.error.HTTPError as exc:assert exc.code==401
print('Production service, workflow assets, API docs and authentication boundary passed.')
