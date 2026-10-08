"""Read-only local production checks (login/logout mutate sessions only)."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import httpx

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8083')
    parser.add_argument('--credentials',type=Path,default=ROOT/'data/production-access.json')
    args=parser.parse_args()
    if urlparse(args.url).hostname not in ('127.0.0.1','localhost','::1'):raise SystemExit('Local checks only')
    credentials=json.loads(args.credentials.read_text(encoding='utf-8-sig'))
    with httpx.Client(base_url=args.url,timeout=10) as client:
        ready=client.get('/healthz');ready.raise_for_status()
        assert ready.json()['mode']=='production'
        assert client.get('/api/auth/config').json()['demo_mode'] is False
        response=client.post('/api/auth/login',json={k:credentials[k] for k in ['username','password']});response.raise_for_status()
        client.headers['X-CSRF-Token']=response.json()['csrf']
        health=client.get('/api/health').json()
        assert health['app_mode']=='production' and health['component_health']=='not_connected'
        counts={name:len(client.get('/api/'+path).json()) for name,path in [('machines','machines'),('tickets','tickets'),('engineers','personnel'),('manuals','knowledge/manuals'),('cases','cases')]}
        assert client.get('/api/replay').status_code==404
        assert 'console.js' in client.get('/').text
        assert client.post('/api/auth/demo',json={'role':'supervisor'}).status_code==403
        client.post('/api/auth/logout').raise_for_status()
        assert client.get('/api/auth/me').status_code==401
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'url':args.url,'mode':'production','quick_login_disabled':True,
            'demo_replay_disabled':True,'operational_console':True,'database':health['database'],'counts':counts,
            'llm_available':health['llm']['available'],'sensors_connected':False,
            'scope':'Local production-mode integration check; no enterprise acceptance or cloud deployment claim'}
    (ROOT/'artifacts/production-live-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
