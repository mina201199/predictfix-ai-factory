"""Consistent SQLite or PostgreSQL backup and restore to a NEW database; never overwrite live data."""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

CONTAINER_DUMP='/tmp/predictfix-backup.dump'
CONTAINER_RESTORE='/tmp/predictfix-restore.dump'
DATABASE_NAME=re.compile(r'^[a-z][a-z0-9_]{2,62}$')

def checksum(path):
    digest=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def connect_read(path):
    return sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)

def check(conn):
    if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Database integrity check failed')
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'users','tickets','machines','schema_versions'}<=tables:raise RuntimeError('Not a current PredictFix database')
    latest=conn.execute('SELECT MAX(version) FROM schema_versions').fetchone()[0]
    if latest!=1:raise RuntimeError('Unsupported schema version')

def backup(source, destination):
    source,destination=Path(source),Path(destination)
    if not source.is_file():raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive reservation prevents accidentally replacing a previous backup.
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    try:
        with connect_read(source) as original,sqlite3.connect(destination) as copy:
            original.backup(copy);check(copy)
        metadata={'created_at':datetime.now(timezone.utc).isoformat(),'schema':1,'sha256':checksum(destination),'bytes':destination.stat().st_size}
        manifest=destination.with_suffix(destination.suffix+'.json')
        with manifest.open('x',encoding='utf-8') as f:json.dump(metadata,f,indent=2)
        return metadata
    except Exception:
        destination.unlink(missing_ok=True)
        raise

def restore(source, destination):
    source,destination=Path(source),Path(destination)
    metadata=json.loads(source.with_suffix(source.suffix+'.json').read_text(encoding='utf-8'))
    if checksum(source)!=metadata['sha256']:raise RuntimeError('Backup checksum mismatch')
    with connect_read(source) as original:check(original)
    result=backup(source,destination)
    # A restored installation must require fresh authentication.
    with sqlite3.connect(destination) as db:
        db.execute('DELETE FROM login_sessions');db.commit();check(db)
    result['sha256']=checksum(destination)
    destination.with_suffix(destination.suffix+'.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return {'restored':True,'sessions_revoked':True,'schema':1}

def run_compose(compose, *args, check=True):
    return subprocess.run(['docker','compose',*compose,*args],capture_output=True,text=True,encoding='utf-8',check=check)

def backup_postgres(compose, destination, database='predictfix', user='predictfix'):
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    try:
        # pg_dump 必須和伺服器同版或更新；在 PostgreSQL 17 容器內執行，不依賴本機或 runner 的 client 版本
        run_compose(compose,'exec','-T','db','pg_dump','-U',user,'-d',database,'-Fc','-f',CONTAINER_DUMP)
        # 用 cp 取出檔案而非 stdout 重導向，Windows PowerShell 會改寫 binary 內容
        run_compose(compose,'cp','db:'+CONTAINER_DUMP,str(destination))
        run_compose(compose,'exec','-T','db','rm','-f',CONTAINER_DUMP,check=False)
        metadata={'created_at':datetime.now(timezone.utc).isoformat(),'format':'pg_custom','database':database,
                  'sha256':checksum(destination),'bytes':destination.stat().st_size}
        with destination.with_suffix(destination.suffix+'.json').open('x',encoding='utf-8') as f:json.dump(metadata,f,indent=2)
        return metadata
    except Exception:
        destination.unlink(missing_ok=True)
        raise

def restore_postgres(compose, source, target_database, user='predictfix'):
    source=Path(source)
    # 資料庫名稱會組進 SQL 與指令列，只接受安全字元避免注入
    if not DATABASE_NAME.match(target_database):raise ValueError('Unsafe database name')
    metadata=json.loads(source.with_suffix(source.suffix+'.json').read_text(encoding='utf-8'))
    if checksum(source)!=metadata['sha256']:raise RuntimeError('Backup checksum mismatch')
    found=run_compose(compose,'exec','-T','db','psql','-U',user,'-d','postgres','-tAc',
                      f"SELECT 1 FROM pg_database WHERE datname='{target_database}'").stdout.strip()
    if found=='1':raise FileExistsError(target_database)
    run_compose(compose,'cp',str(source),'db:'+CONTAINER_RESTORE)
    run_compose(compose,'exec','-T','db','createdb','-U',user,target_database)
    run_compose(compose,'exec','-T','db','pg_restore','-U',user,'-d',target_database,'--no-owner',CONTAINER_RESTORE)
    # 還原後的環境必須重新登入，與 SQLite 還原的行為一致
    run_compose(compose,'exec','-T','db','psql','-U',user,'-d',target_database,'-c','DELETE FROM login_sessions')
    run_compose(compose,'exec','-T','db','rm','-f',CONTAINER_RESTORE,check=False)
    return {'restored':True,'sessions_revoked':True,'database':target_database}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['backup','restore'])
    parser.add_argument('--source',type=Path)
    parser.add_argument('--destination',type=Path)
    parser.add_argument('--postgres',action='store_true',help='Use pg_dump/pg_restore inside the compose db service')
    parser.add_argument('--compose-file',action='append',default=[])
    parser.add_argument('--project')
    parser.add_argument('--env-file')
    parser.add_argument('--target-database')
    args=parser.parse_args()
    if not args.postgres:
        if not args.source or not args.destination:parser.error('--source and --destination are required')
        result=(backup if args.action=='backup' else restore)(args.source,args.destination)
    else:
        compose=(['-p',args.project] if args.project else [])+(['--env-file',args.env_file] if args.env_file else [])
        for path in args.compose_file or ['compose.production.yaml']:compose+=['-f',path]
        if args.action=='backup':
            if not args.destination:parser.error('--destination is required')
            result=backup_postgres(compose,args.destination)
        else:
            if not args.source or not args.target_database:parser.error('--source and --target-database are required')
            result=restore_postgres(compose,args.source,args.target_database)
    print(json.dumps(result))

if __name__=='__main__':main()
