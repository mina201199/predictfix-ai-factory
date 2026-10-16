import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import backup_database

COMPOSE=['-p','pf-test','-f','compose.production.yaml']


def fakeCompose(calls,existingDatabase=False):
  def run(compose,*args,check=True):
    calls.append(args)
    stdout=''
    if args[0]=='cp' and args[1].startswith('db:'):
      # 模擬 docker compose cp 把容器內的 dump 複製到本機
      Path(args[2]).write_bytes(b'PGDMP fake archive')
    if 'psql' in args and any('pg_database' in a for a in args):
      stdout='1\n' if existingDatabase else ''
    return subprocess.CompletedProcess(args,0,stdout,'')
  return run


def writeDump(tmp_path,content=b'PGDMP fake archive',sha=None):
  dump=tmp_path/'predictfix.dump'
  dump.write_bytes(content)
  manifest={'format':'pg_custom','sha256':sha or hashlib.sha256(content).hexdigest(),'bytes':len(content)}
  dump.with_suffix('.dump.json').write_text(json.dumps(manifest),encoding='utf-8')
  return dump


def test_backup_postgres_uses_container_cp(monkeypatch,tmp_path):
  calls=[]
  monkeypatch.setattr(backup_database,'run_compose',fakeCompose(calls))
  destination=tmp_path/'backups'/'predictfix.dump'
  result=backup_database.backup_postgres(COMPOSE,destination)
  assert any(c[0]=='exec' and 'db' in c and 'pg_dump' in c and '-Fc' in c for c in calls)
  assert any(c[0]=='cp' and c[1].startswith('db:') for c in calls)
  manifest=json.loads(destination.with_suffix('.dump.json').read_text(encoding='utf-8'))
  assert manifest['format']=='pg_custom'
  assert manifest['sha256']==hashlib.sha256(destination.read_bytes()).hexdigest()==result['sha256']


def test_backup_postgres_never_overwrites(monkeypatch,tmp_path):
  calls=[]
  monkeypatch.setattr(backup_database,'run_compose',fakeCompose(calls))
  destination=tmp_path/'predictfix.dump'
  destination.write_bytes(b'previous backup')
  with pytest.raises(FileExistsError):
    backup_database.backup_postgres(COMPOSE,destination)
  assert calls==[] and destination.read_bytes()==b'previous backup'


def test_restore_refuses_existing_database(monkeypatch,tmp_path):
  calls=[]
  monkeypatch.setattr(backup_database,'run_compose',fakeCompose(calls,existingDatabase=True))
  dump=writeDump(tmp_path)
  with pytest.raises(FileExistsError):
    backup_database.restore_postgres(COMPOSE,dump,'pf_restore_check')
  assert not any('createdb' in c or 'pg_restore' in c for c in calls)


def test_restore_rejects_checksum_mismatch(monkeypatch,tmp_path):
  calls=[]
  monkeypatch.setattr(backup_database,'run_compose',fakeCompose(calls))
  dump=writeDump(tmp_path,sha='0'*64)
  with pytest.raises(RuntimeError,match='Backup checksum mismatch'):
    backup_database.restore_postgres(COMPOSE,dump,'pf_restore_check')
  assert calls==[]


def test_restore_rejects_unsafe_database_name(monkeypatch,tmp_path):
  calls=[]
  monkeypatch.setattr(backup_database,'run_compose',fakeCompose(calls))
  dump=writeDump(tmp_path)
  with pytest.raises(ValueError):
    backup_database.restore_postgres(COMPOSE,dump,"x'; DROP DATABASE predictfix; --")
  assert calls==[]


def test_restore_creates_new_database_and_revokes_sessions(monkeypatch,tmp_path):
  calls=[]
  monkeypatch.setattr(backup_database,'run_compose',fakeCompose(calls))
  dump=writeDump(tmp_path)
  result=backup_database.restore_postgres(COMPOSE,dump,'pf_restore_check')
  order=[next(i for i,c in enumerate(calls) if word in c) for word in ['createdb','pg_restore']]
  assert order[0]<order[1]
  assert any('DELETE FROM login_sessions' in ' '.join(c) for c in calls)
  assert result=={'restored':True,'sessions_revoked':True,'database':'pf_restore_check'}
