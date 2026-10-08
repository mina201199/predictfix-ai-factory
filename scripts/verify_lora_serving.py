"""Check the persisted adapter serves the same output as the recorded experiment."""
from datetime import datetime,timezone
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:8085'


def main():
    health=None
    for _ in range(45):
        try:
            with urllib.request.urlopen(URL+'/healthz',timeout=2) as response:health=json.load(response)
            break
        except (urllib.error.URLError,TimeoutError):time.sleep(1)
    assert health and health['mode']=='isolated_lora_experiment'
    training=json.loads((ROOT/'artifacts/lora-training-report.json').read_text(encoding='utf-8'))
    assert health['adapter_sha256']==training['adapter_sha256']
    row=json.loads((ROOT/'training/selection-dataset.json').read_text(encoding='utf-8'))['splits']['test'][0]
    body={'question':row['question'],'paragraphs':row['paragraphs']}
    request=urllib.request.Request(URL+'/predict',data=json.dumps(body,ensure_ascii=False).encode('utf-8'),
                                   headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=90) as response:result=json.load(response)
    recorded=next(r for r in training['lora_test']['results'] if r['id']==row['id'])
    assert result['raw_output']==recorded['raw_output'], 'Reloaded adapter output differs from recorded experiment'
    bad=urllib.request.Request(URL+'/predict',data=b'{"question":"test","paragraphs":[]}',headers={'Content-Type':'application/json'})
    try:
        urllib.request.urlopen(bad,timeout=5)
        raise AssertionError('Empty candidates must be rejected')
    except urllib.error.HTTPError as exc:assert exc.code==400
    report={'verified_at':datetime.now(timezone.utc).isoformat(),'status':'deployed','url':URL,
            'scope':'Isolated localhost CPU experiment; not production LLM replacement',
            'health':health,'saved_adapter_reload':'passed','recorded_output_match':'passed',
            'invalid_input_rejected':'passed','sample_id':row['id'],'expected':row['selected'],'response':result}
    (ROOT/'artifacts/lora-serving-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
