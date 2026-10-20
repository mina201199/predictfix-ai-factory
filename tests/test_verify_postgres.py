import subprocess
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import verify_postgres

ADMIN='postgresql+psycopg://postgres@127.0.0.1:55432/postgres'


class FakeConnection:
  def __init__(self,log):self.log=log
  def execute(self,sql):self.log.append(sql)
  def __enter__(self):return self
  def __exit__(self,*exc):return False


def test_rejects_non_local_admin_url():
  with pytest.raises(SystemExit):
    verify_postgres.require_local('postgresql+psycopg://postgres@10.0.0.5:5432/postgres')
  verify_postgres.require_local(ADMIN)


def test_database_url_points_at_scenario_database():
  assert verify_postgres.database_url(ADMIN,'pf_verify_x_abc123')=='postgresql+psycopg://postgres@127.0.0.1:55432/pf_verify_x_abc123'


def test_docker_missing_message(monkeypatch,capsys):
  monkeypatch.setattr(verify_postgres.shutil,'which',lambda name:None)
  assert verify_postgres.main(['container'])==1
  assert '找不到 Docker' in capsys.readouterr().err


def test_cleanup_runs_on_failure(monkeypatch):
  sql=[]
  monkeypatch.setattr(verify_postgres,'connect',lambda url:FakeConnection(sql))
  monkeypatch.setattr(verify_postgres,'launch',lambda script,env:subprocess.CompletedProcess([script],1,'','boom'))
  assert verify_postgres.main(['scenarios','--admin-url',ADMIN])==1
  created=[s for s in sql if s.startswith('CREATE DATABASE')]
  dropped=[s for s in sql if s.startswith('DROP DATABASE')]
  assert len(created)==len(verify_postgres.SCENARIOS)==len(dropped)
  assert all('WITH (FORCE)' in s for s in dropped)


def test_scenarios_run_in_declared_mode_on_their_own_database(monkeypatch):
  seen=[]
  monkeypatch.setattr(verify_postgres,'connect',lambda url:FakeConnection([]))
  monkeypatch.setattr(verify_postgres,'launch',lambda script,env:seen.append((script,env)) or subprocess.CompletedProcess([script],0,'{}',''))
  assert verify_postgres.main(['scenarios','--admin-url',ADMIN])==0
  urls={env['DATABASE_URL'] for _,env in seen}
  assert len(urls)==len(seen)==len(verify_postgres.SCENARIOS)
  declared=[(script,mode,'1' if mode=='demo' else '0') for script,mode,_ in verify_postgres.SCENARIOS.values()]
  assert [(script,env['APP_MODE'],env['DEMO_MODE']) for script,env in seen]==declared
  assert all(env['DATABASE_URL'].startswith('postgresql+psycopg://') for _,env in seen)


def test_new_feature_scenarios_are_included():
  scripts={(script,mode) for script,mode,_ in verify_postgres.SCENARIOS.values()}
  # 第二波新功能必須在 PostgreSQL 實跑；介接沿用 tests/test_integrations.py 兩種模式都跑的涵蓋範圍
  assert {('graph_scenario.py','demo'),('graph_entity_scenario.py','demo'),
          ('integration_scenario.py','production'),('integration_scenario.py','demo')}<=scripts
  assert {('dispatch_concurrency_scenario.py','production'),('production_scenario.py','production'),
          ('repair_flow_scenario.py','production')}<=scripts


@pytest.mark.parametrize('suite,code',[('tests="3" skipped="0"',0),('tests="3" skipped="1"',1),('tests="0" skipped="0"',1)])
def test_pytest_scenario_runs_through_pytest_and_rejects_skips(monkeypatch,suite,code):
  calls=[]
  def fake_run(args,**kwargs):
    calls.append(args)
    report=next(arg for arg in args if arg.startswith('--junitxml=')).split('=',1)[1]
    Path(report).write_text(f'<testsuites><testsuite {suite}/></testsuites>',encoding='utf-8')
    return subprocess.CompletedProcess(args,0,'','')
  monkeypatch.setattr(verify_postgres.subprocess,'run',fake_run)
  assert verify_postgres.launch('integration_scenario.py',{}).returncode==code
  assert calls[0][1:3]==['-m','pytest']


def test_container_project_name_is_configurable():
  assert verify_postgres.compose_args('pf-pg-verify')[:2]==['-p','pf-pg-verify']
  assert verify_postgres.compose_args('pf-verify')[2:]==['-f','compose.production.yaml','-f','deploy/compose.verify.yaml']
