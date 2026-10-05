"""Local demo smoke checks; never reports answer quality as a benchmark."""
import argparse
import http.cookiejar
import json
from pathlib import Path
import urllib.request
from urllib.parse import urlparse


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8082');args=parser.parse_args()
    if urlparse(args.url).hostname not in ['localhost','127.0.0.1']:raise SystemExit('Local demo only')
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    csrf=''
    def api(path,body=None):
        req=urllib.request.Request(args.url+'/api'+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
            headers={'Content-Type':'application/json','X-CSRF-Token':csrf})
        with opener.open(req,timeout=120) as r:return json.load(r)
    if not api('/auth/config')['demo_mode']:raise SystemExit('Enable demo mode first')
    csrf=api('/auth/demo',{'role':'supervisor'})['csrf']
    health=api('/health')
    checks=[]
    for question in ['換刀卡住只在某個刀位出現，應先記錄什麼？','冷卻液流量下降但液位正常，有哪些排查方向？','熱機後尺寸漂移，量測條件要如何記錄？']:
        result=api('/assist',{'question':question,'machine_model':'PF-VMC850-DEMO'})
        quote_valid=all(any(s['source_id']==c['id'] and s['quote'] in c['text'] for c in result['citations']) for s in result['steps'])
        checks.append({'question':question,'llm_used':result['llm_used'],'model':result.get('model'),
                       'answer_method':result['answer_method'],'source_ids':[c['id'] for c in result['citations']],
                       'selected_count':len(result['steps']),'quotes_exist':quote_valid,
                       'citation_checks':result.get('citation_checks'),'elapsed_ms':result['elapsed_ms'],
                       'reason':result.get('reason')})
        print(json.dumps(checks[-1],ensure_ascii=False),flush=True)
    report={'scope':'3-question local integration smoke; not answer-quality evaluation',
            'llm_available':health['llm']['available'],'checks':checks}
    (Path(__file__).resolve().parents[1]/'artifacts/knowledge-live-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(c['source_ids'] and c['quotes_exist'] for c in checks):raise SystemExit('Source or quote check failed')


if __name__=='__main__':main()
