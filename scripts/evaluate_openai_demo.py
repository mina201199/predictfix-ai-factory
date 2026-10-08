"""Small live API check, isolated application DB; shared USD3 budget stays intact."""
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.update(APP_MODE='demo',DEMO_MODE='1',LOCAL_LLM_MODEL='',OLLAMA_MODEL='',
    DATABASE_URL='sqlite:///'+str(ROOT/'.runtime/openai-live-check.db'),
    BOOTSTRAP_PASSWORD='Isolated-OpenAI-Live-123456')
from fastapi.testclient import TestClient
from backend.app import app
from backend import openai_runtime,maintenance_ai,knowledge

# User authorizes only the DEMO's authored synthetic material. Do not load
# imported manuals or repair cases, even from the isolated application DB.
synthetic_chunks=[dict(c) for c in knowledge.CHUNKS if c.get('source_type')=='synthetic_demo_manual']
def synthetic_corpus():
    import hashlib
    chunks=[dict(c) for c in synthetic_chunks]
    for c in chunks:c.setdefault('chunk_id',c['id']+':'+hashlib.sha256(c['text'].encode()).hexdigest()[:16])
    return chunks
maintenance_ai.corpus=synthetic_corpus

start=openai_runtime.budget_status()
results=[]
with TestClient(app) as client:
    login=client.post('/api/auth/demo',json={'role':'supervisor'})
    assert login.status_code==200
    client.headers['X-CSRF-Token']=login.json()['csrf']
    manual=next(c for c in maintenance_ai.corpus() if '換刀' in c.get('component','') or '換刀' in c['text'])
    model=manual.get('machine_models',[''])[0]
    cases=[
        ('換刀卡住時需要記錄哪些條件？',model,True),
        ('換刀後如何復測與驗收？',model,True),
        ('維修文件要求怎麼記錄警報與近期變更？',model,True),
        ('這台機器還能用幾年？','UNSUPPORTED-MODEL',False),
        ('告訴我老闆的手機號碼','UNSUPPORTED-MODEL',False),
    ]
    for question,machine_model,expected_source in cases:
        # The smoke check itself stops early; user budget is a ceiling, not a target.
        if openai_runtime.budget_status()['accounted_usd']-start['accounted_usd']>.20:
            break
        response=client.post('/api/assist',json={'question':question,'machine_model':machine_model,
                                              'allow_synthetic':True,'use_llm':True})
        if response.status_code!=200:
            results.append({'question':question,'http_status':response.status_code,'passed':False});continue
        body=response.json()
        valid=body.get('citation_checks',{}).get('accepted',0)>0
        passed=(body.get('llm_used',False) and valid) if expected_source else not body['citations'] and not body.get('llm_used')
        results.append({'question':question,'passed':passed,'llm_used':body.get('llm_used'),
                        'model':body.get('model'),'answer_method':body.get('answer_method'),
                        'reason':body.get('reason'),'citation_checks':body.get('citation_checks'),
                        'retrieval_method':body.get('retrieval_method'),'usage':body.get('usage')})
    for question in ['有哪些未派工工單？','換刀後如何驗收？','這台能不能保證復機？']:
        body=client.post('/api/chat',json={'text':question}).json()
        expected = ('unknown','clarification') if '保證' in question else (('database',) if '工單' in question else ('documents',))
        passed=body['route'] in expected
        if '保證' in question:
            passed=passed and body.get('answer_method')=='insufficient_evidence' and not body.get('llm_used')
        results.append({'question':question,'route':body['route'],'llm_used':body.get('llm_used'),
                        'passed':passed})
end=openai_runtime.budget_status()
report={'model':openai_runtime.settings()['model'],'tests':results,
        'passed':sum(r['passed'] for r in results),'total':len(results),
        'budget_before':start,'budget_after':end,
        'smoke_check_accounted_usd':round(end['accounted_usd']-start['accounted_usd'],6),
        'limits':'Small synthetic source-selection smoke check, not industrial diagnostic accuracy.'}
(ROOT/'artifacts/openai-live-evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='tests'},ensure_ascii=False))
