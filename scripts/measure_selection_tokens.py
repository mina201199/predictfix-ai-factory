"""用 Gemma 4 E2B 的 tokenizer 與 chat template 量測段落選取題庫的 token 長度。

只下載 tokenizer 相關小檔（約 32 MB），不下載模型權重。需在有 transformers 的環境執行，例如：
  .runtime/qlora-env/Scripts/python.exe scripts/measure_selection_tokens.py --runtime-dir <主 checkout>/.runtime
結果寫入 artifacts/selection-dataset-v2-token-stats.json，測試會核對它與目前題庫的 SHA-256 一致。
"""
import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from prepare_lora_data import prompt
from build_selection_dataset_v2 import LLAMA_CONTEXT, LLAMA_MAX_TOKENS, TRAIN_MAX_LENGTH

MODEL_ID='google/gemma-4-E2B-it'
MODEL_REVISION='3e22461f65e89153144f8adb70e3b8c2cc9845a7'
TOKENIZER_FILES=['tokenizer.json','tokenizer_config.json','chat_template.jinja','config.json']
DATASETS={'v1':'training/selection-dataset.json','v2':'training/selection-dataset-v2.json'}
TARGET=ROOT/'artifacts/selection-dataset-v2-token-stats.json'


def lengths(tokenizer,row):
  messages=[{'role':'user','content':prompt(row)}]
  answer=json.dumps({'selected':row['selected']},ensure_ascii=False,separators=(',',':'))
  promptIds=tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,return_dict=True)['input_ids']
  fullIds=tokenizer.apply_chat_template(messages+[{'role':'assistant','content':answer}],tokenize=True,
                                        return_dict=True)['input_ids']
  return len(promptIds),len(fullIds),len(prompt(row))


def summarize(values):
  ordered=sorted(values)
  return {'max':ordered[-1],'p95':ordered[max(0,round(0.95*len(ordered))-1)],'mean':round(statistics.mean(ordered),1)}


def main():
  parser=argparse.ArgumentParser()
  parser.add_argument('--runtime-dir',help='放 hf-cache 的 .runtime 目錄；預設為本專案 .runtime')
  args=parser.parse_args()
  from huggingface_hub import hf_hub_download
  from transformers import AutoTokenizer
  cache=(Path(args.runtime_dir) if args.runtime_dir else ROOT/'.runtime')/'hf-cache'
  for name in TOKENIZER_FILES:
    hf_hub_download(MODEL_ID,name,revision=MODEL_REVISION,cache_dir=cache)
  tokenizer=AutoTokenizer.from_pretrained(MODEL_ID,revision=MODEL_REVISION,cache_dir=cache,local_files_only=True)
  report={'tokenizer':{'model':MODEL_ID,'revision':MODEL_REVISION},
          'sha256_encoding':'UTF-8 text with LF line endings',
          'definition':'prompt_tokens = 使用者訊息套用 chat template 並加上 generation prompt；'
                       'train_tokens = 再加上金標 JSON 答案的完整訓練序列',
          'limits':{'llama_context':LLAMA_CONTEXT,'llama_max_tokens':LLAMA_MAX_TOKENS,
                    'max_prompt_tokens_for_llama':LLAMA_CONTEXT-LLAMA_MAX_TOKENS,'train_max_length':TRAIN_MAX_LENGTH},
          'datasets':{}}
  for version,relative in DATASETS.items():
    path=ROOT/relative
    data=json.loads(path.read_text(encoding='utf-8'))
    perSplit={};allPrompt=[];allTrain=[];ratios=[]
    for split,rows in data['splits'].items():
      measured=[lengths(tokenizer,row) for row in rows]
      perSplit[split]={'prompt_tokens':summarize([m[0] for m in measured]),'train_tokens':summarize([m[1] for m in measured])}
      allPrompt+=[m[0] for m in measured];allTrain+=[m[1] for m in measured]
      ratios+=[m[2]/m[0] for m in measured]
    report['datasets'][version]={'path':relative,'sha256':hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest(),
      'rows':len(allPrompt),'splits':perSplit,'max_prompt_tokens':max(allPrompt),'max_train_tokens':max(allTrain),
      'min_chars_per_prompt_token':round(min(ratios),3)}
  v2=report['datasets']['v2']
  report['passed']=(v2['max_prompt_tokens']<=LLAMA_CONTEXT-LLAMA_MAX_TOKENS and v2['max_train_tokens']<=TRAIN_MAX_LENGTH)
  TARGET.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
  main()
