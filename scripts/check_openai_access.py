"""Check credentials/model access without exposing keys or making paid requests."""
import asyncio
import json
import sys
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import openai_runtime as runtime

async def main():
    s=runtime.settings()
    report={'key_configured':bool(s['key']),'requested_model':s['model']}
    if not s['key']:
        print(json.dumps(report));return
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r=await c.get('https://api.openai.com/v1/models',headers={'Authorization':'Bearer '+s['key']})
        report['http_status']=r.status_code
        if r.status_code==200:
            ids={item['id'] for item in r.json()['data']}
            report.update(requested_model_available=s['model'] in ids,
                supported_available=[m for m in runtime.PRICES if m in ids],paid_requests=0)
    except (httpx.HTTPError,ValueError,KeyError):report['error']='access_check_failed'
    print(json.dumps(report))

asyncio.run(main())
