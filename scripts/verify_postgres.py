"""Verify PredictFix on PostgreSQL 17 in two layers, without touching any real database.

scenarios: run the in-process scenarios, each on its own throwaway database, in the mode
           their own pytest wrapper uses (production, or demo for the graph scenarios).
container: run the production compose stack (API image + PostgreSQL), exercise the knowledge
           graph and work-order integration, restart it, then back up with pg_dump and
           restore into a NEW database.
"""
import argparse
import hashlib
import hmac
import http.cookiejar
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.backup_database import backup_postgres, restore_postgres, run_compose

# 這些是既有測試檔已使用的隔離測試值，只存在於用完即丟的驗證資料庫；
# 圖譜情境以展示登入取得主管身分，沿用其 pytest 包裝檔的 demo 模式
SCENARIOS={
  'dispatch_concurrency':('dispatch_concurrency_scenario.py','production','Isolated-Test-Password-123456'),
  'production':('production_scenario.py','production','Isolated-Test-Password-123456'),
  'repair_flow':('repair_flow_scenario.py','production','Isolated-Flow-Password-123456'),
  'graph':('graph_scenario.py','demo','Isolated-Graph-Fixture-123456'),
  'graph_entity':('graph_entity_scenario.py','demo','Isolated-Graph-Entity-Fixture-123456'),
  'integration_production':('integration_scenario.py','production','Isolated-Integration-Password-123456'),
  'integration_demo':('integration_scenario.py','demo','Isolated-Integration-Password-123456'),
}
# pytest 模組直接執行只會載入、不會跑任何測試，必須交給 pytest
PYTEST_SCENARIOS={'integration_scenario.py'}
API='http://127.0.0.1:18084'
RESTORE_DATABASE='pf_restore_check'
INBOUND='/api/integrations/work-orders'
SOURCE='pfverify'
KEY_ID='k1'


def require_local(url):
  # 驗證會建立與刪除資料庫，只允許本機目標，避免誤連到真實環境
  host=urlparse(url).hostname
  if host not in ('127.0.0.1','localhost'):
    raise SystemExit('只允許驗證本機的 PostgreSQL，收到的主機是：'+str(host))


def database_url(adminUrl,name):
  return urlparse(adminUrl)._replace(path='/'+name).geturl()


def connect(adminUrl):
  import psycopg
  return psycopg.connect(adminUrl.replace('postgresql+psycopg://','postgresql://',1),autocommit=True)


def launch(script,env):
  if script not in PYTEST_SCENARIOS:
    return subprocess.run([sys.executable,str(ROOT/'tests'/script)],env=env,cwd=ROOT,capture_output=True,
                          text=True,encoding='utf-8',timeout=300)
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
    report=Path(folder)/'report.xml'
    result=subprocess.run([sys.executable,'-m','pytest','--confcutdir=.','--rootdir=.','tests/'+script,'-q',
                           '-p','no:cacheprovider','--basetemp='+str(Path(folder)/'tmp'),'--junitxml='+str(report)],
                          env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=600)
    if result.returncode==0:
      suites=list(ElementTree.parse(report).getroot().iter('testsuite'))
      # 沒收集到測試或以 skip 掩蓋缺測都不算通過，與 tests/test_integrations.py 的守門一致
      if not sum(int(s.get('tests',0)) for s in suites) or sum(int(s.get('skipped',0)) for s in suites):
        result.returncode=1
        result.stderr+='\n'+script+' 沒有執行任何測試或有跳過的測試'
    return result


def run_scenario(adminUrl,script,mode,password):
  name='pf_verify_'+Path(script).stem+'_'+secrets.token_hex(3)
  with connect(adminUrl) as conn:
    conn.execute(f'CREATE DATABASE "{name}"')
  try:
    env={**os.environ,'APP_MODE':mode,'DEMO_MODE':'1' if mode=='demo' else '0','BOOTSTRAP_PASSWORD':password,
         'DATABASE_URL':database_url(adminUrl,name),'OLLAMA_MODEL':'','LOCAL_LLM_MODEL':'',
         'OPENAI_ENABLED':'0','PYTHONIOENCODING':'utf-8'}
    return launch(script,env)
  finally:
    # 情境失敗也要清掉暫存資料庫；FORCE 會中斷殘留連線，避免 DROP 卡住
    with connect(adminUrl) as conn:
      conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def scenarios(adminUrl):
  require_local(adminUrl)
  results={}
  for label,(script,mode,password) in SCENARIOS.items():
    result=run_scenario(adminUrl,script,mode,password)
    results[label]=result.returncode==0
    if result.returncode:
      print('情境失敗：'+label+'\n'+result.stdout[-2000:]+result.stderr[-4000:],file=sys.stderr)
  print(json.dumps(results))
  return 0 if all(results.values()) else 1


def compose_args(project):
  return ['-p',project,'-f','compose.production.yaml','-f','deploy/compose.verify.yaml']


class Client:
  def __init__(self):
    self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    self.csrf=''

  def request(self,method,path,body=None,raw=None,headers=None):
    data=raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    request=urllib.request.Request(API+path,data=data,method=method,
                                   headers={'Content-Type':'application/json','X-CSRF-Token':self.csrf,**(headers or {})})
    with self.opener.open(request,timeout=10) as response:
      return json.load(response)

  def login(self,password):
    self.csrf=self.request('POST','/api/auth/login',{'username':'supervisor','password':password})['csrf']

  def send_order(self,secret,order):
    # 簽章格式與 backend/integration_service.py 相同；不 import backend，避免固定 DATABASE_URL
    raw=json.dumps(order,ensure_ascii=False,separators=(',',':')).encode()
    stamp=str(int(time.time()))
    prefix=f'v1\nPOST\n{INBOUND}\n{SOURCE}\n{KEY_ID}\n{stamp}\n{order["eventId"]}\n'.encode()
    return self.request('POST',INBOUND,raw=raw,headers={'X-Integration-Source':SOURCE,'X-Integration-Key':KEY_ID,
      'X-Integration-Timestamp':stamp,'X-Integration-Event':order['eventId'],
      'X-Integration-Signature':hmac.new(secret.encode(),prefix+raw,hashlib.sha256).hexdigest()})


def wait_healthy(seconds=90):
  for _ in range(seconds):
    try:
      with urllib.request.urlopen(API+'/healthz',timeout=2) as response:
        if json.load(response).get('mode')=='production':return
    # 容器重啟期間連線可能被 reset 或逾時，OSError 都涵蓋
    except OSError:pass
    time.sleep(1)
  raise RuntimeError('API 在 '+str(seconds)+' 秒內沒有恢復健康')


def psql_value(compose,sql):
  return run_compose(compose,'exec','-T','db','psql','-U','predictfix','-d',RESTORE_DATABASE,'-tAc',sql).stdout.strip()


def graph_paths(client,model):
  result=client.request('POST','/api/graph/query',{'machineModel':model,'query':model,'maxHops':3})
  return [path['nodes'][-1]['label'] for path in result['paths']]


def graph_checks(client):
  template=client.request('POST','/api/equipment-templates',{'name':'PostgreSQL 驗證模板','asset_type':'CNC 加工中心',
    'kind':'mill','parts':['主軸軸承','冷卻泵'],
    'steps':[{'label':'檢查主軸異音與溫升','kind':'inspect','criterion':'記錄轉速、溫度與異音位置'},
             {'label':'復測主軸溫升','kind':'verify','criterion':'連續運轉並記錄溫升'}]})
  model=template['id']
  created=client.request('POST','/api/graph/rebuild')['created']
  rows=[row for row in client.request('GET','/api/graph/candidates') if row['machineModel']==model]
  part=next(row for row in rows if row['relation']=='has_part' and row['tail']['label']=='主軸軸承')
  approved=client.request('POST','/api/graph/relations/'+part['id']+'/review',
                          {'revision':part['revision'],'action':'approve','note':'PostgreSQL 驗證人工核對'})
  return model,created>=4 and len(rows)==4 and approved['effective'] and graph_paths(client,model)==['主軸軸承']


def integration_checks(client,secret):
  client.request('PUT','/api/integrations/mappings',{'source':SOURCE,'machineCode':'PGV-MILL-01','machineId':'VERIFY-01'})
  order={'externalId':'EXT-VERIFY-1','eventId':'EVT-VERIFY-1','version':1,'machineCode':'PGV-MILL-01','alarm':'AL-2041',
         'symptoms':'主軸異音且溫度升高','occurredAt':'2026-10-20T08:00:00+08:00'}
  first=client.send_order(secret,order)
  again=client.send_order(secret,order)
  issues=[ticket['issue'] for ticket in client.request('GET','/api/tickets')]
  return first['ticketId'],first['state']=='linked' and again==first and issues==['主軸異音且溫度升高']


def container(project='pf-verify'):
  if not shutil.which('docker'):
    print('找不到 Docker，請先安裝並啟動 Docker Desktop。',file=sys.stderr)
    return 1
  if subprocess.run(['docker','info'],capture_output=True).returncode:
    print('無法連線到 Docker，請先啟動 Docker Desktop。',file=sys.stderr)
    return 1
  compose=compose_args(project)
  postgresPassword=secrets.token_urlsafe(24)
  bootstrapPassword=secrets.token_urlsafe(24)
  integrationSecret=secrets.token_urlsafe(32)
  # 密碼只在本次執行產生並經環境變數交給 compose，不寫進任何檔案
  os.environ.update({'POSTGRES_PASSWORD':postgresPassword,'BOOTSTRAP_PASSWORD':bootstrapPassword,
                     'DATABASE_URL':f'postgresql+psycopg://predictfix:{postgresPassword}@db/predictfix',
                     # compose.production.yaml 對 proxy 的 APP_DOMAIN 做必填檢查；驗證不啟動 proxy
                     'APP_DOMAIN':'verify.localhost',
                     # 容器內沒有接收端，回寫目的地固定為連不上的位址，只驗證失敗後排程重試、不送出資料
                     'INTEGRATION_SOURCES':json.dumps({SOURCE:{'keys':{KEY_ID:integrationSecret},
                       'outboundUrl':'http://127.0.0.1:9/events','allowHttp':True}})})
  summary={}
  try:
    run_compose(compose,'up','-d','--build','--wait','db','api')
    check=subprocess.run([sys.executable,str(ROOT/'scripts'/'check_container.py'),'--url',API],capture_output=True,text=True,encoding='utf-8')
    if check.returncode:raise RuntimeError('check_container 失敗：'+check.stdout+check.stderr)
    summary['container_smoke']=True
    client=Client();client.login(bootstrapPassword)
    client.request('POST','/api/machines',{'id':'VERIFY-01','name':'PostgreSQL 驗證設備','kind':'mill'})
    model,summary['graph_review_query']=graph_checks(client)
    ticketId,summary['integration_inbound']=integration_checks(client,integrationSecret)
    # worker 的 claim 使用 FOR UPDATE SKIP LOCKED，只有在容器內連 PostgreSQL 才實際走到
    worker=run_compose(compose,'exec','-T','api','python','-m','backend.integration_worker','--once')
    outbox=client.request('GET','/api/integrations/outbox')
    summary['integration_worker_retry']=('"processed": true' in worker.stdout and len(outbox)==1 and outbox[0]['attempts']==1
                                         and outbox[0]['state']=='pending' and outbox[0]['lastError']=='destination_or_transport_error')
    run_compose(compose,'restart','db','api')
    wait_healthy()
    client=Client();client.login(bootstrapPassword)
    summary['restart_persistence']=any(m['id']=='VERIFY-01' for m in client.request('GET','/api/machines'))
    summary['restart_graph_integration']=(graph_paths(client,model)==['主軸軸承'] and
      any(o['ticketId']==ticketId for o in client.request('GET','/api/integrations/records')['orders']))
    with tempfile.TemporaryDirectory() as folder:
      dump=Path(folder)/'pf-verify.dump'
      backup_postgres(compose,dump)
      restore_postgres(compose,dump,RESTORE_DATABASE)
    summary['restore_machines']=psql_value(compose,"SELECT count(*) FROM machines WHERE id='VERIFY-01'")=='1'
    summary['restore_sessions_revoked']=psql_value(compose,'SELECT count(*) FROM login_sessions')=='0'
    summary['restore_graph']=(psql_value(compose,"SELECT count(*) FROM graph_relations WHERE status='approved'")=='1'
                              and psql_value(compose,"SELECT count(*) FROM graph_nodes WHERE label='主軸軸承'")=='1')
    summary['restore_integration']=psql_value(compose,"SELECT (SELECT count(*) FROM integration_orders)||','||"
      "(SELECT count(*) FROM integration_inbound_events)||','||(SELECT count(*) FROM integration_outbox)")=='1,1,1'
  except (RuntimeError,OSError,subprocess.CalledProcessError,urllib.error.HTTPError,KeyError,StopIteration) as exc:
    detail=getattr(exc,'stderr',None) or repr(exc)
    print('容器驗證失敗：'+detail[-4000:],file=sys.stderr)
    summary['error']=True
  finally:
    logs=run_compose(compose,'logs','--tail','60','api',check=False).stdout if summary.get('error') else ''
    if logs:print(logs,file=sys.stderr)
    run_compose(compose,'down','-v','--remove-orphans',check=False)
  print(json.dumps(summary))
  return 0 if summary and not summary.get('error') and all(summary.values()) else 1


def main(argv=None):
  parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
  sub=parser.add_subparsers(dest='command',required=True)
  layer=sub.add_parser('scenarios',help='password comes from the PGPASSWORD environment variable')
  layer.add_argument('--admin-url',required=True)
  layer=sub.add_parser('container')
  # 與其他平行驗證共用 Docker 時，可指定獨立的 compose 專案名稱避免互相覆蓋
  layer.add_argument('--project',default='pf-verify',help='docker compose project name')
  args=parser.parse_args(argv)
  return scenarios(args.admin_url) if args.command=='scenarios' else container(args.project)


if __name__=='__main__':
  sys.exit(main())
