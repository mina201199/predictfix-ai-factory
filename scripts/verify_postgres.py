"""Verify Vulkrion on PostgreSQL 17 in two layers, without touching any real database.

scenarios: run the in-process production scenarios, each on its own throwaway database.
container: run the production compose stack (API image + PostgreSQL), restart it, then
           back up with pg_dump and restore into a NEW database.
"""
import argparse
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.backup_database import backup_postgres, restore_postgres, run_compose

# 這些是既有測試檔已使用的隔離測試值，只存在於用完即丟的驗證資料庫
SCENARIOS={
  'dispatch_concurrency_scenario.py':'Isolated-Test-Password-123456',
  'production_scenario.py':'Isolated-Test-Password-123456',
  'repair_flow_scenario.py':'Isolated-Flow-Password-123456',
}
COMPOSE=['-p','pf-verify','-f','compose.production.yaml','-f','deploy/compose.verify.yaml']
API='http://127.0.0.1:18084'
RESTORE_DATABASE='pf_restore_check'


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
  return subprocess.run([sys.executable,str(ROOT/'tests'/script)],env=env,cwd=ROOT,capture_output=True,
                        text=True,encoding='utf-8',timeout=300)


def run_scenario(adminUrl,script,password):
  name='pf_verify_'+Path(script).stem+'_'+secrets.token_hex(3)
  with connect(adminUrl) as conn:
    conn.execute(f'CREATE DATABASE "{name}"')
  try:
    env={**os.environ,'APP_MODE':'production','DEMO_MODE':'0','BOOTSTRAP_PASSWORD':password,
         'DATABASE_URL':database_url(adminUrl,name),'OLLAMA_MODEL':'','LOCAL_LLM_MODEL':''}
    return launch(script,env)
  finally:
    # 情境失敗也要清掉暫存資料庫；FORCE 會中斷殘留連線，避免 DROP 卡住
    with connect(adminUrl) as conn:
      conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def scenarios(adminUrl):
  require_local(adminUrl)
  results={}
  for script,password in SCENARIOS.items():
    result=run_scenario(adminUrl,script,password)
    results[script]=result.returncode==0
    if result.returncode:
      print('情境失敗：'+script+'\n'+result.stdout[-2000:]+result.stderr[-4000:],file=sys.stderr)
  print(json.dumps(results))
  return 0 if all(results.values()) else 1


class Client:
  def __init__(self):
    self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    self.csrf=''

  def request(self,method,path,body=None):
    data=json.dumps(body).encode() if body is not None else None
    request=urllib.request.Request(API+path,data=data,method=method,headers={'Content-Type':'application/json','X-CSRF-Token':self.csrf})
    with self.opener.open(request,timeout=10) as response:
      return json.load(response)

  def login(self,password):
    self.csrf=self.request('POST','/api/auth/login',{'username':'supervisor','password':password})['csrf']


def wait_healthy(seconds=90):
  for _ in range(seconds):
    try:
      with urllib.request.urlopen(API+'/healthz',timeout=2) as response:
        if json.load(response).get('mode')=='production':return
    # 容器重啟期間連線可能被 reset 或逾時，OSError 都涵蓋
    except OSError:pass
    time.sleep(1)
  raise RuntimeError('API 在 '+str(seconds)+' 秒內沒有恢復健康')


def psql_value(sql):
  return run_compose(COMPOSE,'exec','-T','db','psql','-U','predictfix','-d',RESTORE_DATABASE,'-tAc',sql).stdout.strip()


def container():
  if not shutil.which('docker'):
    print('找不到 Docker，請先安裝並啟動 Docker Desktop。',file=sys.stderr)
    return 1
  if subprocess.run(['docker','info'],capture_output=True).returncode:
    print('無法連線到 Docker，請先啟動 Docker Desktop。',file=sys.stderr)
    return 1
  postgresPassword=secrets.token_urlsafe(24)
  bootstrapPassword=secrets.token_urlsafe(24)
  # 密碼只在本次執行產生並經環境變數交給 compose，不寫進任何檔案
  os.environ.update({'POSTGRES_PASSWORD':postgresPassword,'BOOTSTRAP_PASSWORD':bootstrapPassword,
                     'DATABASE_URL':f'postgresql+psycopg://predictfix:{postgresPassword}@db/predictfix',
                     # compose.production.yaml 對 proxy 的 APP_DOMAIN 做必填檢查；驗證不啟動 proxy
                     'APP_DOMAIN':'verify.localhost'})
  summary={}
  try:
    run_compose(COMPOSE,'up','-d','--build','--wait','db','api')
    check=subprocess.run([sys.executable,str(ROOT/'scripts'/'check_container.py'),'--url',API],capture_output=True,text=True,encoding='utf-8')
    if check.returncode:raise RuntimeError('check_container 失敗：'+check.stdout+check.stderr)
    summary['container_smoke']=True
    client=Client();client.login(bootstrapPassword)
    client.request('POST','/api/machines',{'id':'VERIFY-01','name':'PostgreSQL 驗證設備','kind':'mill'})
    run_compose(COMPOSE,'restart','db','api')
    wait_healthy()
    client=Client();client.login(bootstrapPassword)
    summary['restart_persistence']=any(m['id']=='VERIFY-01' for m in client.request('GET','/api/machines'))
    with tempfile.TemporaryDirectory() as folder:
      dump=Path(folder)/'pf-verify.dump'
      backup_postgres(COMPOSE,dump)
      restore_postgres(COMPOSE,dump,RESTORE_DATABASE)
    summary['restore_machines']=psql_value("SELECT count(*) FROM machines WHERE id='VERIFY-01'")=='1'
    summary['restore_sessions_revoked']=psql_value('SELECT count(*) FROM login_sessions')=='0'
  except (RuntimeError,OSError,subprocess.CalledProcessError,urllib.error.HTTPError) as exc:
    detail=getattr(exc,'stderr',None) or str(exc)
    print('容器驗證失敗：'+detail[-4000:],file=sys.stderr)
    summary['error']=True
  finally:
    logs=run_compose(COMPOSE,'logs','--tail','60','api',check=False).stdout if summary.get('error') else ''
    if logs:print(logs,file=sys.stderr)
    run_compose(COMPOSE,'down','-v','--remove-orphans',check=False)
  print(json.dumps(summary))
  return 0 if summary and not summary.get('error') and all(summary.values()) else 1


def main(argv=None):
  parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
  sub=parser.add_subparsers(dest='command',required=True)
  layer=sub.add_parser('scenarios',help='password comes from the PGPASSWORD environment variable')
  layer.add_argument('--admin-url',required=True)
  sub.add_parser('container')
  args=parser.parse_args(argv)
  return scenarios(args.admin_url) if args.command=='scenarios' else container()


if __name__=='__main__':
  sys.exit(main())
