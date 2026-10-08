"""Consistent SQLite backup and restore to a NEW database; never overwrite live data."""
import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

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

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['backup','restore'])
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--destination',required=True,type=Path)
    args=parser.parse_args()
    result=(backup if args.action=='backup' else restore)(args.source,args.destination)
    print(json.dumps(result))

if __name__=='__main__':main()
