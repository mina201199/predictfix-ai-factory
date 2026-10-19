"""用既有 llama.cpp CPU 執行環境與 Gemma 4 E2B Q8_0，對 v2 題庫的小樣本檢查準確度。

目的只是確認新題目不再是全對；不報告延遲（本機同時有其他工作，計時不可信）。
請求格式、JSON schema 與評分沿用 scripts/benchmark_local_llm.py 與 scripts/train_lora.py。
用法：
  .venv/Scripts/python.exe scripts/evaluate_selection_v2_sample.py --runtime-dir <主 checkout>/.runtime
"""
import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import benchmark_local_llm as bench
from train_lora import summarize

DATASET=ROOT/'training/selection-dataset-v2.json'
TARGET=ROOT/'artifacts/selection-v2-gemma-sample.json'
MODEL_KEY='gemma4-e2b-q8_0'
TIMING_FIELDS=['latency_seconds','prompt_ms','generation_ms']


def sampleRows(data,perSubtype,seed):
  # 只從 validation／test 抽，保留 train 給之後的微調；每種題型抽相同數量
  bySubtype=defaultdict(list)
  for split in ['validation','test']:
    for row in data['splits'][split]:
      bySubtype[row['subtype']].append((split,row))
  rng=random.Random(seed)
  return [pair for subtype in sorted(bySubtype) for pair in rng.sample(bySubtype[subtype],perSubtype)]


def tally(results,key):
  table={}
  for result in results:
    entry=table.setdefault(result[key],{'count':0,'exact':0})
    entry['count']+=1;entry['exact']+=int(result['exact'])
  return dict(sorted(table.items()))


def main():
  parser=argparse.ArgumentParser()
  parser.add_argument('--runtime-dir',required=True,help='含 llama/ 與 models/ 的 .runtime 目錄')
  parser.add_argument('--per-subtype',type=int,default=2)
  parser.add_argument('--threads',type=int,default=6)
  parser.add_argument('--seed',type=int,default=7)
  args=parser.parse_args()
  runtime=Path(args.runtime_dir).resolve()
  bench.MODELS_DIR=runtime/'models'
  bench.RUNTIMES['cpu']['dir']=runtime/'llama'
  # 日誌寫在本 worktree，避免覆蓋主 checkout 既有的基準測試日誌
  bench.LOG_DIR=ROOT/'.runtime/benchmark-logs'
  data=json.loads(DATASET.read_text(encoding='utf-8'))
  rows=sampleRows(data,args.per_subtype,args.seed)
  results=[]
  with bench.Server(MODEL_KEY,'cpu',args.threads):
    for split,row in rows:
      result=bench.ask(MODEL_KEY,row)
      for field in TIMING_FIELDS:result.pop(field,None)
      result.update(subtype=row['subtype'],difficulty=row['difficulty'],split=split)
      results.append(result)
      print(f"{row['id']}: exact={result['exact']} selected={result['selected']} expected={result['expected']}",flush=True)
  metrics=summarize([{**r,'latency_seconds':0} for r in results])
  metrics.pop('mean_latency_seconds')
  bySubtype=tally(results,'subtype')
  report={'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
          'purpose':'v2 題庫小樣本，只看準確度；刻意不記錄延遲。',
          'model':{'key':MODEL_KEY,**{k:bench.MODELS[MODEL_KEY][k] for k in ['repo','revision','file','sha256']}},
          'runtime':'llama.cpp b11491 CPU，-c 2048，JSON schema 限制段落 ID（與 benchmark_local_llm.py 相同）',
          'dataset':{'path':'training/selection-dataset-v2.json','sha256':hashlib.sha256(DATASET.read_bytes()).hexdigest()},
          'sample':{'splits':['validation','test'],'per_subtype':args.per_subtype,'seed':args.seed,'count':len(rows),
                    'kinds':dict(Counter(r['kind'] for r in results))},
          'metrics':metrics,'by_subtype':bySubtype,
          'by_difficulty':tally(results,'difficulty'),
          'max_prompt_tokens_seen':max((r['prompt_tokens'] or 0) for r in results),
          'results':results}
  TARGET.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  print(json.dumps({'metrics':metrics,'by_subtype':bySubtype},ensure_ascii=False,indent=2))


if __name__=='__main__':
  main()
