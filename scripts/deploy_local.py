"""Deploy a hashed release snapshot on localhost, with isolated operational data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8084)
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('port must be 1024..65535')
    url=f'http://127.0.0.1:{args.port}'
    try:
        urllib.request.urlopen(url+'/healthz',timeout=2)
    except urllib.error.URLError:pass
    else:raise SystemExit('Port already serves an application; no existing service will be replaced.')
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    release=ROOT/'.runtime/local-deploy/releases'/run_id
    release.mkdir(parents=True,exist_ok=False)
    files=[p for p in ROOT.iterdir() if p.suffix in ['.html','.js','.css'] or p.name=='requirements.txt']
    files += [p for p in (ROOT/'backend').rglob('*.py')]
    files += [p for p in (ROOT/'docs/manuals').rglob('*') if p.is_file()]
    # Only public experiment artifacts needed for application startup; never copy local credentials.
    for name in ['model-report.json','intent-model.joblib','bearing-model.joblib','intent-dataset.json']:
        p=ROOT/'artifacts'/name
        if p.exists():files.append(p)
    manifest={}
    for source in files:
        relative=source.relative_to(ROOT)
        dest=release/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dest)
        manifest[str(relative).replace('\\','/')]=hashlib.sha256(dest.read_bytes()).hexdigest()
    (release/'release-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    data=ROOT/'.runtime/local-deploy/data';data.mkdir(exist_ok=True)
    access=data/'initial-access.json'
    if access.exists():credential=json.loads(access.read_text(encoding='utf-8'))
    else:
        credential={'username':'supervisor','password':secrets.token_urlsafe(32)}
        access.write_text(json.dumps(credential),encoding='utf-8')
    env={**os.environ,'APP_MODE':'production','DEMO_MODE':'0','DATABASE_URL':'sqlite:///'+str(data/'factory.db'),
         'BOOTSTRAP_PASSWORD':credential['password'],'LOCAL_LLM_MODEL':'','OLLAMA_MODEL':'','PYTHONUTF8':'1'}
    logs=ROOT/'.runtime/local-deploy/logs';logs.mkdir(exist_ok=True)
    with (logs/(run_id+'.log')).open('w',encoding='utf-8') as log:
        process=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),'-m','uvicorn','backend.app:app',
            '--host','127.0.0.1','--port',str(args.port)],cwd=release,env=env,stdout=log,stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    report={'deployed_at':datetime.now(timezone.utc).isoformat(),'release_id':run_id,'url':url,
            'hosting':'Localhost native Python; not Docker, not publicly reachable',
            'database':'Isolated persistent SQLite under ignored .runtime/local-deploy/data',
            'release_manifest_sha256':hashlib.sha256((release/'release-manifest.json').read_bytes()).hexdigest(),
            'file_count':len(manifest),'launcher_pid':process.pid,'status':'starting',
            'llm':'Disabled in isolated deployment; candidate-source fallback. Existing demo model unchanged.',
            'docker_status':'Engine unavailable: dockerDesktopLinuxEngine named pipe missing',
            'postgresql_verified':False,'https_verified':False}
    target=ROOT/'artifacts/local-deployment-report.json'
    try:
        result=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'scripts/check_container.py'),
                               '--url',url],timeout=60,check=True,capture_output=True,text=True)
        with urllib.request.urlopen(url+'/healthz',timeout=5) as response:report['health']=json.load(response)
        report['checks']={'workflow_assets':'passed','api_docs':'passed','anonymous_tickets_blocked':'passed',
                          'demo_quick_login_disabled':'passed'}
        report['status']='deployed'
    except Exception as exc:
        report.update(status='failed',error_type=type(exc).__name__,error=str(exc)[:500])
        raise
    finally:target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
