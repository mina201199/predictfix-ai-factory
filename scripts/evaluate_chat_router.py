"""Compare the baseline and trained router through the real guarded chat API."""
import os,json,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.update(APP_MODE='demo',DEMO_MODE='1',DATABASE_URL='sqlite:///'+str(ROOT/'.runtime/router-evaluation.db'),BOOTSTRAP_PASSWORD='Isolated-Router-Evaluation-2026',LOCAL_LLM_MODEL='',OLLAMA_MODEL='')
import joblib
from fastapi.testclient import TestClient
from backend import chat
from backend.app import app
data=json.loads((ROOT/'artifacts/chat-router-dataset.json').read_text(encoding='utf-8'))['test']
def matches(label,result):
    if label=='unknown':return result['route'] in ['unknown','clarification']
    if label.startswith('GUIDE-'):return result['route']=='documents' and result.get('citations',[{}])[0].get('id')==label
    if label=='documents':return result['route']=='documents'
    kind={'machine_attention':'machines','person_tasks':'person_tasks','open_tickets':'tickets','history':'tickets','review':'tickets','unassigned':'tickets','workload':'workload','idle_people':'idle_people'}[label]
    return result.get('query_kind')==kind
reports={}
with TestClient(app) as client:
    login=client.post('/api/auth/demo',json={'role':'supervisor'});login.raise_for_status()
    client.headers['X-CSRF-Token']=login.json()['csrf']
    for name,filename in [('baseline','intent-model.joblib'),('candidate','chat-router-v2.joblib')]:
        chat.INTENT_MODEL=joblib.load(ROOT/'artifacts'/filename)
        cases=[]
        for row in data:
            result=client.post('/api/chat',json={'text':row['text']}).json()
            cases.append({**row,'route':result['route'],'query_kind':result.get('query_kind'),'source_id':(result.get('citations') or [{}])[0].get('id'),'router_method':result.get('router_method'),'correct':matches(row['intent'],result)})
        reports[name]={'accuracy':sum(c['correct'] for c in cases)/len(cases),'cases':cases}
ready=reports['candidate']['accuracy']>=reports['baseline']['accuracy'] and all(c['correct'] for c in reports['candidate']['cases'] if c['intent']=='unknown')
report={'test_count':len(data),'promotable':ready,'model_sha256':hashlib.sha256((ROOT/'artifacts/chat-router-v2.joblib').read_bytes()).hexdigest(),'evaluation_scope':'Response route and procedure source selection, not expert validation of maintenance procedures.',**reports}
(ROOT/'artifacts/chat-router-api-evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'test_count':len(data),'promotable':ready,'baseline':reports['baseline']['accuracy'],'candidate':reports['candidate']['accuracy'],'learned_procedure_cases':sum(c['router_method']=='trained_classifier_with_topic_guard' for c in reports['candidate']['cases'])}))
if not ready:raise SystemExit('Guarded API evaluation failed; do not deploy')
