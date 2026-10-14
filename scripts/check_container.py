"""Standard-library smoke check, usable on a clean CI runner."""
import argparse
import json
import re
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
    # 容器剛啟動時連線可能被直接 reset 而非拒絕；OSError 同時涵蓋 URLError、ConnectionResetError 與逾時
    except OSError:time.sleep(1)
assert ready and ready['mode']=='production',ready
assets=set()
for page in ['/','/workflow.html','/knowledge.html']:
    with urllib.request.urlopen(args.url+page,timeout=5) as response:
        assert response.status==200,page
        # 從頁面實際引用的檔案取得清單，Dockerfile 漏複製新資產時才會在這裡失敗
        assets.update(re.findall(r'(?:src|href)="([\w.-]+\.(?:js|css))"',response.read().decode()))
assert assets,'No page assets found'
for path in ['/'+asset for asset in sorted(assets)]+['/docs']:
    with urllib.request.urlopen(args.url+path,timeout=5) as response:
        assert response.status==200,path
with urllib.request.urlopen(args.url+'/api/auth/config') as response:
    assert json.load(response)['demo_mode'] is False
try:
    urllib.request.urlopen(args.url+'/api/tickets')
    raise AssertionError('Anonymous operational access must fail')
except urllib.error.HTTPError as exc:assert exc.code==401
print('Production service, workflow assets, API docs and authentication boundary passed.')
