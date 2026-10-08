"""Reproducible isolated security checks with optional real local-model probes."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Also probe the local llama.cpp model on port 8081')
    parser.add_argument('--output', default='artifacts/security-test-report.json')
    args=parser.parse_args()
    reports=[]
    runtime=ROOT/'.runtime'
    runtime.mkdir(exist_ok=True)
    for category in ['injection','access','leakage','hallucination']+(['live'] if args.live else []):
        print('Running '+category+' checks...',flush=True)
        with tempfile.TemporaryDirectory(prefix='security-',dir=runtime) as temp:
            env={**os.environ,'APP_MODE':'production','DEMO_MODE':'0',
                 'DATABASE_URL':'sqlite:///'+str(Path(temp)/'isolated.db'),
                 'BOOTSTRAP_PASSWORD':'Security-Fixture-Password-123456',
                 'SECURITY_ENV_CANARY':'ENV-CANARY-NOT-FOR-MODEL-789',
                 'LOCAL_LLM_MODEL':'Qwen3-0.6B-Q8_0' if category=='live' else '',
                 'OLLAMA_MODEL':'','LLM_PROVIDER':'llamacpp','LLM_URL':'http://127.0.0.1:8081'}
            result=subprocess.run([sys.executable,str(ROOT/'tests/security_scenario.py'),category],
                                  cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',
                                  timeout=700 if category=='live' else 90)
            try:
                report=json.loads(result.stdout)
            except ValueError:
                report={'category':category,'checks':{'scenario_completed':False},'error':'Scenario failed; see terminal diagnostics.'}
                print(result.stderr,file=sys.stderr)
            reports.append(report)
    checks=[v for r in reports for v in r['checks'].values()]
    report={'generated_at':datetime.now(timezone.utc).isoformat(),
            'environment':'isolated SQLite; synthetic adversarial fixtures; production mode',
            'passed':sum(checks),'total':len(checks),'categories':reports,
            'limits':['Finite application checks, not a penetration-test certification.',
                      'Live probes verify source mapping, secret isolation and state invariants; not diagnostic accuracy.',
                      'Authorized manual content, questions and operational records are not automatically redacted.',
                      'Shared factory operational data has no tenant or per-machine access isolation.']}
    target=ROOT/args.output
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{sum(checks)}/{len(checks)} checks passed. Report: {target}')
    if not checks or not all(checks):raise SystemExit(1)


if __name__=='__main__':main()
