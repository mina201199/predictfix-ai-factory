"""Caddy 後方的登入節流：只採信固定 Caddy 位址送來的 X-Forwarded-For。"""
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import yaml

ROOT=Path(__file__).resolve().parents[1]
PASSWORD='Proxy-Client-Fixture-Password-123456'
DEFAULT=re.compile(r'^\$\{(\w+):-([^}]+)\}$')


def composeDefault(value):
  # 部署可用 env 覆寫，測試檢查的是沒有覆寫時實際生效的預設值
  match=DEFAULT.match(str(value))
  assert match,value
  return match.group(1),match.group(2)


def productionNetwork():
  compose=yaml.safe_load((ROOT/'compose.production.yaml').read_text(encoding='utf-8'))
  services=compose['services']
  trusted=composeDefault(services['api']['environment']['FORWARDED_ALLOW_IPS'])
  proxy=composeDefault(services['proxy']['networks']['default']['ipv4_address'])
  subnet=composeDefault(compose['networks']['default']['ipam']['config'][0]['subnet'])
  return compose,trusted,proxy,subnet


def test_api_trusts_only_the_fixed_proxy_address():
  compose,trusted,proxy,subnet=productionNetwork()
  # 同一個變數同時決定 Caddy 的 IP 與 uvicorn 的信任清單，兩者才不會分開漂移
  assert trusted==proxy and trusted[0]=='PROXY_IP'
  address=ipaddress.ip_address(trusted[1])
  network=ipaddress.ip_network(subnet[1])
  assert address in network
  # Docker 把第一個主機位址當 gateway；主機經公開埠連進來就是這個來源，不能被信任
  assert address!=next(network.hosts())
  assert 'ports' not in compose['services']['api']
  # Caddy 沒設定 trusted_proxies 時會丟掉客戶端自帶的 XFF，改填真實連線 IP
  assert 'trusted_proxies' not in (ROOT/'deploy/Caddyfile').read_text(encoding='utf-8').lower()


def test_env_example_documents_the_same_defaults():
  _,_,proxy,subnet=productionNetwork()
  example=(ROOT/'deploy/production.env.example').read_text(encoding='utf-8')
  for name,value in [proxy,subnet]:
    assert re.search(r'^#\s*'+name+'='+re.escape(value)+r'\s*$',example,re.M),name


SCENARIO='''import json, os
from fastapi.testclient import TestClient
from uvicorn.config import Config
from backend.app import app
# 與容器相同：uvicorn 從 FORWARDED_ALLOW_IPS 決定要採信哪個來源的 XFF
config=Config(app)
config.load()
served=config.loaded_app
proxy=os.environ['FORWARDED_ALLOW_IPS']
gateway=os.environ['TEST_GATEWAY']
attacker,victim='10.20.0.5','10.20.0.6'
results={}
def attempt(label,source,password,count=1,xff=None,headers=None):
  client=TestClient(served,client=(source,40000),raise_server_exceptions=False)
  statuses=[]
  for n in range(count):
    sent=dict(headers or {})
    if xff:sent['X-Forwarded-For']=xff.format(n=n+1)
    statuses.append(client.post('/api/auth/login',json={'username':'supervisor','password':password},headers=sent).status_code)
  results[label]=statuses
wrong='not-the-password'
right=os.environ['BOOTSTRAP_PASSWORD']
with TestClient(served,client=(proxy,40000)):
  attempt('attackerWrong',proxy,wrong,5,attacker)
  attempt('attackerLocked',proxy,wrong,1,attacker)
  attempt('victimViaProxy',proxy,right,1,victim,{'X-Forwarded-Proto':'https','Origin':'https://testserver'})
  attempt('forgedLeftPart',proxy,right,3,'198.51.100.{n}, '+attacker)
  attempt('untrustedSpoofsVictim',gateway,wrong,5,victim)
  attempt('untrustedRotatesXff',gateway,wrong,2,'203.0.113.{n}')
  attempt('victimAfterSpoof',proxy,right,1,victim)
  attempt('foreignOrigin',proxy,right,1,victim,{'X-Forwarded-Proto':'https','Origin':'https://evil.example'})
print(json.dumps(results))
'''


def test_lockout_is_per_client_behind_proxy_and_ignores_forged_xff(tmp_path):
  _,trusted,_,subnet=productionNetwork()
  gateway=str(next(ipaddress.ip_network(subnet[1]).hosts()))
  env={**os.environ,'APP_MODE':'production','DEMO_MODE':'0','LAN_MODE':'0',
       'BOOTSTRAP_PASSWORD':PASSWORD,'DATABASE_URL':'sqlite:///'+str(tmp_path/'proxy.db'),
       'OLLAMA_MODEL':'','LOCAL_LLM_MODEL':'','PYTHONUTF8':'1',
       'FORWARDED_ALLOW_IPS':trusted[1],'TEST_GATEWAY':gateway}
  result=subprocess.run([sys.executable,'-c',SCENARIO],env=env,cwd=ROOT,capture_output=True,
                        text=True,encoding='utf-8',timeout=120)
  assert result.returncode==0,result.stdout+result.stderr
  report=json.loads(result.stdout.strip().splitlines()[-1])
  assert report['attackerWrong']==[401]*5
  assert report['attackerLocked']==[429]
  # 修正前所有人共用 Caddy 的 IP，這裡會是 429
  assert report['victimViaProxy']==[200]
  # Caddy 若改成附加 XFF，左側偽造段也換不到新的 key
  assert report['forgedLeftPart']==[429]*3
  # 非 Caddy 來源的 XFF 一律忽略：冒用受害者 IP 只會鎖到自己，換 XFF 也繞不過
  assert report['untrustedSpoofsVictim']==[401]*5
  assert report['untrustedRotatesXff']==[429]*2
  assert report['victimAfterSpoof']==[200]
  assert report['foreignOrigin']==[403]
