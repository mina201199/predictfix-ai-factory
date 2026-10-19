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


def test_scenarios_run_in_production_mode_on_their_own_database(monkeypatch):
  seen=[]
  monkeypatch.setattr(verify_postgres,'connect',lambda url:FakeConnection([]))
  monkeypatch.setattr(verify_postgres,'launch',lambda script,env:seen.append((script,env)) or subprocess.CompletedProcess([script],0,'{}',''))
  assert verify_postgres.main(['scenarios','--admin-url',ADMIN])==0
  urls={env['DATABASE_URL'] for _,env in seen}
  assert len(urls)==len(seen)==len(verify_postgres.SCENARIOS)
  assert all(env['APP_MODE']=='production' and env['DEMO_MODE']=='0' for _,env in seen)
  assert all(env['DATABASE_URL'].startswith('postgresql+psycopg://') for _,env in seen)
