"""A small integration smoke test, not a model-quality benchmark."""
import json
import urllib.request
from pathlib import Path

root=Path(__file__).resolve().parents[1]
tests=[('CNC03 主軸震動，溫度92度，E102，昨天換過刀。','CNC-03'),
       ('CNC01 的冷卻泵應該檢查什麼？','CNC-01'),
       ('有人說機台異常，但沒有告訴我機台編號。',None)]
results=[]
for text,expected in tests:
    request=urllib.request.Request('http://127.0.0.1:8080/api/copilot',
        data=json.dumps({'text':text}).encode('utf-8'),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=180) as response:
        body=json.load(response)
    raw=body.get('generated_fields',{})
    results.append({'input':text,'expected_machine':expected,
                    'llm_machine_correct':raw.get('machine_id')==expected,
                    'response':body})
    print(json.dumps({'llm_used':body['llm_used'],'machine_correct':results[-1]['llm_machine_correct'],
                      'elapsed_ms':body['elapsed_ms']},ensure_ascii=False),flush=True)
report={'scope':'3-case integration smoke test, not a held-out benchmark','cases':results}
(root/'artifacts'/'llm-smoke-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
if not all(r['response']['llm_used'] and r['llm_machine_correct'] for r in results):
    raise SystemExit('One or more LLM calls did not produce valid results')
