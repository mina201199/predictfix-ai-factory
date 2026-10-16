"""本機 GGUF 模型基準：段落選取準確度、延遲與記憶體，比較 CPU／GPU、量化程度與不同模型。

用法：
  python scripts/benchmark_local_llm.py download
  python scripts/benchmark_local_llm.py sweep --model gemma4-e2b-q4_0 --threads 4,6,8,12,14 --rows 8
  python scripts/benchmark_local_llm.py run --models all --runtimes cpu,cuda --threads 4,8 --security
  python scripts/benchmark_local_llm.py summary
"""
import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'.runtime'
MODELS_DIR=RUNTIME/'models'
LOG_DIR=RUNTIME/'benchmark-logs'
DATASET=ROOT/'training/selection-dataset.json'
sys.path.insert(0,str(ROOT/'scripts'))
from prepare_lora_data import prompt
from train_lora import score_output, summarize

# 固定 revision 與 SHA-256：重跑時下載到的必定是同一份檔案，被替換或損毀就直接失敗
MODELS={
  # 已淘汰的對照組（2026-10-15）：選對率只有 22.7%，且台灣案場對中國開發模型有合規疑慮；保留只為重現 docs/local-llm-benchmark.md 的比較
  'qwen3-0.6b-q8_0':{'family':'Qwen3-0.6B','origin':'Alibaba（中國）','license':'apache-2.0','quant':'Q8_0',
    'repo':'Qwen/Qwen3-0.6B-GGUF','revision':'23749fefcc72300e3a2ad315e1317431b06b590a',
    'file':'Qwen3-0.6B-Q8_0.gguf','size':639446688,
    'sha256':'9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031','qwen_no_think':True},
  'gemma4-e2b-q4_0':{'family':'Gemma 4 E2B','origin':'Google（美國）','license':'apache-2.0','quant':'Q4_0',
    'repo':'ggml-org/gemma-4-E2B-it-GGUF','revision':'b4243c156154b6dca9324415f8c7ccc098b4aed1',
    'file':'gemma-4-E2B-it-Q4_0.gguf','size':2841481184,
    'sha256':'8e30dff3ac4c8434c49a7036fa15564bdbb6044e42bf04550bf1a096ad7e6a52'},
  'gemma4-e2b-q8_0':{'family':'Gemma 4 E2B','origin':'Google（美國）','license':'apache-2.0','quant':'Q8_0',
    'repo':'ggml-org/gemma-4-E2B-it-GGUF','revision':'b4243c156154b6dca9324415f8c7ccc098b4aed1',
    'file':'gemma-4-E2B-it-Q8_0.gguf','size':4967497152,
    'sha256':'996d08777aadc6bfd3c7375ef70ba25a0f55240075860754fdb18d6d860aa63a'},
  'breeze2-3b-q4_k_m':{'family':'Llama-Breeze2-3B','origin':'聯發創新基地（台灣）','license':'llama3.2','quant':'Q4_K_M',
    'repo':'mradermacher/Llama-Breeze2-3B-Instruct-Text-GGUF','revision':'3d7b82b4386172f37791535edeea8bbdd71ba4a9',
    'file':'Llama-Breeze2-3B-Instruct-Text.Q4_K_M.gguf','size':2241004032,
    'sha256':'c6cc86eea1084ddc03b682f2c966a7a8fa8c03375178d2902c4e6cb560d073d4'},
  'breeze2-3b-q8_0':{'family':'Llama-Breeze2-3B','origin':'聯發創新基地（台灣）','license':'llama3.2','quant':'Q8_0',
    'repo':'mradermacher/Llama-Breeze2-3B-Instruct-Text-GGUF','revision':'3d7b82b4386172f37791535edeea8bbdd71ba4a9',
    'file':'Llama-Breeze2-3B-Instruct-Text.Q8_0.gguf','size':3840526848,
    'sha256':'d0ca62383b851a1bf18ad2bb76ea3ecf74e2d0ee31e85f8dc1f525a2d8e0d7cb'},
  'breeze-7b-q4_k_m':{'family':'Breeze-7B v1.0','origin':'聯發創新基地（台灣）','license':'apache-2.0','quant':'Q4_K_M',
    'repo':'second-state/Breeze-7B-Instruct-v1_0-GGUF','revision':'cceb8cd90f9ff3fff01d64992831a5e9c0a0faa4',
    'file':'Breeze-7B-Instruct-v1_0-Q4_K_M.gguf','size':4538717408,
    'sha256':'76826fa3dca8db91961ab1db236ac1219e1699a722bf3db082d74ef89e4da539'},
}
LLAMA_RELEASE='https://github.com/ggml-org/llama.cpp/releases/download/b11491/'
RUNTIMES={
  'cpu':{'dir':RUNTIME/'llama','archives':[
    ('llama-b11491-bin-win-cpu-x64.zip','dd73bb6652216f354a8786970cc50f6d90768cde2a6c47321976f7bd5b02447b')]},
  'cuda':{'dir':RUNTIME/'llama-cuda','archives':[
    ('llama-b11491-bin-win-cuda-12.4-x64.zip','128126e0fd59ea93c96dee2a9748df08c20b9f55a52d7a7a470a9b83276b6de7'),
    ('cudart-llama-bin-win-cuda-12.4-x64.zip','8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6')]},
}
PORT=8091


def sha256Of(path):
  digest=hashlib.sha256()
  with open(path,'rb') as handle:
    for block in iter(lambda:handle.read(8<<20),b''):digest.update(block)
  return digest.hexdigest()


def fetch(url,target,expectedSha256):
  if target.exists() and sha256Of(target)==expectedSha256:
    print(f'已存在且雜湊相符：{target.name}',flush=True);return
  partial=target.with_name(target.name+'.part')
  digest=hashlib.sha256();done=0
  request=urllib.request.Request(url,headers={'User-Agent':'PredictFix-benchmark'})
  with urllib.request.urlopen(request,timeout=60) as response, open(partial,'wb') as handle:
    total=int(response.headers.get('Content-Length') or 0);last=0
    for block in iter(lambda:response.read(8<<20),b''):
      handle.write(block);digest.update(block);done+=len(block)
      if done-last>=512<<20:
        last=done;print(f'  {target.name}: {done/1e9:.2f}/{total/1e9:.2f} GB',flush=True)
  if digest.hexdigest()!=expectedSha256:
    partial.unlink()
    raise SystemExit(f'SHA-256 不符，已刪除：{target.name}')
  partial.replace(target)
  print(f'下載完成並驗證：{target.name}',flush=True)


def download(args):
  MODELS_DIR.mkdir(parents=True,exist_ok=True)
  for key,model in MODELS.items():
    url=f'https://huggingface.co/{model["repo"]}/resolve/{model["revision"]}/{model["file"]}'
    fetch(url,MODELS_DIR/model['file'],model['sha256'])
  for name,runtime in RUNTIMES.items():
    if (runtime['dir']/'llama-server.exe').exists():
      print(f'{name} runtime 已安裝：{runtime["dir"]}',flush=True);continue
    runtime['dir'].mkdir(parents=True,exist_ok=True)
    for archive,expected in runtime['archives']:
      target=RUNTIME/archive
      fetch(LLAMA_RELEASE+archive,target,expected)
      with zipfile.ZipFile(target) as package:
        for member in package.namelist():
          # 解壓前檢查路徑，避免壓縮檔內的 ../ 寫到 runtime 目錄外
          resolved=(runtime['dir']/member).resolve()
          if runtime['dir'].resolve() not in resolved.parents and resolved!=runtime['dir'].resolve():
            raise SystemExit(f'壓縮檔路徑不安全：{member}')
        package.extractall(runtime['dir'])
      target.unlink()


def rowsOf(limit=None):
  data=json.loads(DATASET.read_text(encoding='utf-8'))
  rows=[row for split in ['train','validation','test'] for row in data['splits'][split]]
  return rows[:limit] if limit else rows


def payload(key,row):
  # 與 backend/maintenance_ai.generate_json 相同的請求；只有 Qwen 需要 /no_think 關閉思考模式，其他模型加了只是雜訊
  content=prompt(row)+('\n/no_think' if MODELS[key].get('qwen_no_think') else '')
  schema={'type':'object','properties':{'selected':{'type':'array','maxItems':4,
          'items':{'type':'string','enum':[p['id'] for p in row['paragraphs']]}}},
          'required':['selected'],'additionalProperties':False}
  return {'model':key,'messages':[{'role':'user','content':content}],'temperature':0,'max_tokens':650,
          'response_format':{'type':'json_object','schema':schema},
          'chat_template_kwargs':{'enable_thinking':False}}


def httpJson(url,body=None,timeout=300):
  data=None if body is None else json.dumps(body,ensure_ascii=False).encode('utf-8')
  request=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(request,timeout=timeout) as response:return json.load(response)


def powershell(command):
  result=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,text=True,timeout=60)
  return result.stdout.strip()


def gpuMemoryUsedMb():
  try:
    output=subprocess.run(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],
                          capture_output=True,text=True,timeout=30).stdout
    return int(output.strip().splitlines()[0])
  except (OSError,ValueError,IndexError,subprocess.SubprocessError):
    return None


class Server:
  def __init__(self,key,runtime,threads):
    self.key,self.runtime,self.threads=key,runtime,threads
    LOG_DIR.mkdir(parents=True,exist_ok=True)
    self.logPath=LOG_DIR/f'{key}-{runtime}-t{threads}.log'

  def __enter__(self):
    exe=RUNTIMES[self.runtime]['dir']/'llama-server.exe'
    # 參數與 start.ps1 相同；-np 1 讓每題延遲不受其他 slot 影響；-lv 4 才會記錄 GPU 實際載入的層數
    command=[str(exe),'-m',str(MODELS_DIR/MODELS[self.key]['file']),'--host','127.0.0.1','--port',str(PORT),
             '-c','2048','-t',str(self.threads),'-np','1','--reasoning','off','--reasoning-budget','0','-lv','4']
    self.gpuBaselineMb=gpuMemoryUsedMb() if self.runtime=='cuda' else None
    self.log=open(self.logPath,'w',encoding='utf-8',errors='replace')
    start=time.perf_counter()
    self.process=subprocess.Popen(command,stdout=self.log,stderr=subprocess.STDOUT)
    while True:
      if self.process.poll() is not None:
        raise RuntimeError(f'llama-server 啟動失敗，見 {self.logPath}')
      try:
        if httpJson(f'http://127.0.0.1:{PORT}/health',timeout=5).get('status')=='ok':break
      except (urllib.error.URLError,OSError,ValueError):
        pass
      if time.perf_counter()-start>600:raise RuntimeError('llama-server 10 分鐘內未就緒')
      time.sleep(1)
    self.loadSeconds=round(time.perf_counter()-start,2)
    return self

  def resources(self):
    peak=powershell(f'(Get-Process -Id {self.process.pid}).PeakWorkingSet64')
    used=gpuMemoryUsedMb()
    self.log.flush()
    logText=self.logPath.read_text(encoding='utf-8',errors='replace')
    offload=re.findall(r'offloaded (\d+)/(\d+) layers to GPU',logText)
    return {'peak_working_set_mb':round(int(peak)/2**20) if peak.isdigit() else None,
            'gpu_memory_delta_mb':(used-self.gpuBaselineMb) if used is not None and self.gpuBaselineMb is not None else None,
            # CPU 版沒有 GPU 後端，卻仍會印出「offloaded N/N layers to GPU」，實際緩衝區全是 CPU_Mapped
            'gpu_layers_offloaded':'0' if self.runtime=='cpu' else (f'{offload[-1][0]}/{offload[-1][1]}' if offload else 'unknown')}

  def __exit__(self,*_):
    self.process.terminate()
    try:self.process.wait(timeout=30)
    except subprocess.TimeoutExpired:self.process.kill()
    self.log.close()


def ask(key,row):
  start=time.perf_counter()
  try:
    body=httpJson(f'http://127.0.0.1:{PORT}/v1/chat/completions',payload(key,row))
    raw=body['choices'][0]['message']['content'];timings=body.get('timings',{})
  except (urllib.error.URLError,OSError,ValueError,KeyError) as error:
    raw='';timings={'error':type(error).__name__}
  latency=round(time.perf_counter()-start,4)
  return {**score_output(raw,row),'id':row['id'],'kind':row['kind'],'expected':row['selected'],
          'raw_output':raw,'latency_seconds':latency,
          'prompt_tokens':timings.get('prompt_n'),'prompt_ms':timings.get('prompt_ms'),
          'generated_tokens':timings.get('predicted_n'),'generation_ms':timings.get('predicted_ms')}


def measure(key,runtime,threads,rows,label):
  with Server(key,runtime,threads) as server:
    ask(key,rows[0])  # 暖機一次，排除第一次載入快取的干擾
    results=[]
    for row in rows:
      result=ask(key,row);results.append(result)
      print(f'  [{label}] {row["id"]}: exact={result["exact"]} {result["latency_seconds"]:.2f}s',flush=True)
    resources=server.resources();loadSeconds=server.loadSeconds
  latencies=sorted(r['latency_seconds'] for r in results)
  promptTokens=sum(r['prompt_tokens'] or 0 for r in results);promptMs=sum(r['prompt_ms'] or 0 for r in results)
  generated=sum(r['generated_tokens'] or 0 for r in results);generationMs=sum(r['generation_ms'] or 0 for r in results)
  metrics=summarize(results) if len(rows)==len(rowsOf()) else {'count':len(results),
          'exact_match':sum(r['exact'] for r in results)/len(results),'mean_latency_seconds':statistics.mean(latencies)}
  metrics.update(p50_latency_seconds=statistics.median(latencies),
                 p95_latency_seconds=latencies[max(0,round(0.95*len(latencies))-1)],
                 prompt_tokens_per_second=round(promptTokens/promptMs*1000,1) if promptMs else None,
                 generation_tokens_per_second=round(generated/generationMs*1000,1) if generationMs else None)
  return {'model':key,'runtime':runtime,'threads':threads,'load_seconds':loadSeconds,**resources,
          'metrics':metrics,'results':results}


def security(key,runtime,threads):
  with Server(key,runtime,threads):
    with tempfile.TemporaryDirectory(prefix='bench-security-',dir=RUNTIME) as temp:
      # 與 run_security_checks.py --live 相同的隔離環境，只把模型服務指向基準用的連接埠
      env={**os.environ,'APP_MODE':'production','DEMO_MODE':'0','DATABASE_URL':'sqlite:///'+str(Path(temp)/'isolated.db'),
           'BOOTSTRAP_PASSWORD':'Security-Fixture-Password-123456','SECURITY_ENV_CANARY':'ENV-CANARY-NOT-FOR-MODEL-789',
           'LOCAL_LLM_MODEL':key,'OLLAMA_MODEL':'','LLM_PROVIDER':'llamacpp','LLM_URL':f'http://127.0.0.1:{PORT}',
           'OPENAI_ENABLED':'0','OPENAI_API_KEY':''}
      result=subprocess.run([sys.executable,str(ROOT/'tests/security_scenario.py'),'live'],cwd=ROOT,env=env,
                            capture_output=True,text=True,encoding='utf-8',timeout=1800)
  try:
    report=json.loads(result.stdout)
  except ValueError:
    return {'completed':False,'stderr_tail':result.stderr[-2000:]}
  checks=report.get('checks',{})
  return {'completed':True,'passed':sum(checks.values()),'total':len(checks),'checks':checks}


def machine():
  cpu=powershell('(Get-CimInstance Win32_Processor | Select-Object -First 1).Name')
  cores=powershell('(Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfCores -Sum).Sum')
  logical=powershell('(Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum')
  ram=powershell('(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory')
  try:
    gpu=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],
                       capture_output=True,text=True,timeout=30).stdout.strip()
  except OSError:
    gpu=None
  return {'cpu':cpu,'cores':int(cores),'logical_processors':int(logical),
          'ram_gb':round(int(ram)/2**30,1),'nvidia_gpu':gpu,'os':powershell('(Get-CimInstance Win32_OperatingSystem).Caption')}


def loadReport(path):
  if path.exists():return json.loads(path.read_text(encoding='utf-8'))
  return {'runs':[],'security':{},'sweeps':[]}


def saveReport(path,report):
  report['generated_at']=datetime.now(timezone.utc).isoformat()
  report['machine']=report.get('machine') or machine()
  report['llama_cpp']='b11491（官方 Windows CPU 版與 CUDA 12.4 版）'
  report['models']={k:{f:v for f,v in m.items() if f!='qwen_no_think'} for k,m in MODELS.items()}
  data=json.loads(DATASET.read_text(encoding='utf-8'))
  report['dataset']={'path':'training/selection-dataset.json','version':data.get('version'),'count':len(rowsOf()),
                     'note':'44 題原創虛構段落選取題，全部用於評估；本基準不訓練模型，因此不受訓練／測試切分影響'}
  report['request']={'temperature':0,'max_tokens':650,'context':2048,'parallel_slots':1,
                     'json_schema_grammar':True,'qwen_only_suffix':'/no_think'}
  report['limits']=['單一台電腦、單次執行；延遲會受背景程式影響。',
                    '題目是合成的段落選取題，不代表維修診斷正確率。',
                    '安全情境是有限的攻擊樣本，不等於完整滲透測試。']
  path.parent.mkdir(parents=True,exist_ok=True)
  path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def run(args):
  path=ROOT/args.output;report=loadReport(path)
  keys=list(MODELS) if args.models=='all' else args.models.split(',')
  rows=rowsOf()
  for key in keys:
    for runtime in args.runtimes.split(','):
      for threads in [int(t) for t in args.threads.split(',')]:
        label=f'{key}/{runtime}/t{threads}'
        print(f'== {label}',flush=True)
        try:
          entry=measure(key,runtime,threads,rows,label)
        except RuntimeError as error:
          entry={'model':key,'runtime':runtime,'threads':threads,'error':str(error)}
        report['runs']=[r for r in report['runs'] if (r['model'],r['runtime'],r['threads'])!=(key,runtime,threads)]+[entry]
        saveReport(path,report)
    if args.security:
      print(f'== security {key}',flush=True)
      report['security'][key]=security(key,'cpu',int(args.threads.split(',')[-1]))
      saveReport(path,report)


def sweep(args):
  path=ROOT/args.output;report=loadReport(path)
  rows=rowsOf(args.rows)
  for threads in [int(t) for t in args.threads.split(',')]:
    print(f'== sweep {args.model} t{threads}',flush=True)
    entry=measure(args.model,'cpu',threads,rows,f'sweep t{threads}')
    entry.pop('results')
    report['sweeps']=[s for s in report['sweeps'] if (s['model'],s['threads'])!=(args.model,threads)]+[entry]
    saveReport(path,report)


def summary(args):
  report=loadReport(ROOT/args.output)
  print('| 模型 | 量化 | 執行 | 執行緒 | GPU 層數 | 選對率 | 合法輸出 | 資料不足拒答 | 注入題 | 延遲中位數 | 延遲 P95 | 生成 tok/s | 記憶體峰值 | GPU 顯存 |')
  print('|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
  for r in sorted(report['runs'],key=lambda r:(list(MODELS).index(r['model']),r['runtime'],r['threads'])):
    m=MODELS[r['model']]
    if 'error' in r:
      print(f'| {m["family"]} | {m["quant"]} | {r["runtime"]} | {r["threads"]} | — | 失敗：{r["error"]} |||||||||');continue
    x=r['metrics']
    print(f'| {m["family"]} | {m["quant"]} | {r["runtime"].upper()} | {r["threads"]} | {r["gpu_layers_offloaded"]} '
          f'| {x["exact_match"]:.1%} | {x["valid_output_rate"]:.1%} | {x["no_answer_accuracy"]:.1%} | {x["injection_exact_match"]:.1%} '
          f'| {x["p50_latency_seconds"]:.2f}s | {x["p95_latency_seconds"]:.2f}s | {x["generation_tokens_per_second"]} '
          f'| {r["peak_working_set_mb"]} MB | {r["gpu_memory_delta_mb"] if r["gpu_memory_delta_mb"] is not None else "—"} MB |')
  for key,s in report.get('security',{}).items():
    print(f'安全情境 {key}: '+(f'{s["passed"]}/{s["total"]}' if s.get('completed') else '未完成'))
  for s in sorted(report.get('sweeps',[]),key=lambda s:s['threads']):
    print(f'執行緒 {s["threads"]}: 延遲中位數 {s["metrics"]["p50_latency_seconds"]:.2f}s，生成 {s["metrics"]["generation_tokens_per_second"]} tok/s')


def main():
  parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('--output',default='artifacts/local-llm-benchmark.json')
  commands=parser.add_subparsers(dest='command',required=True)
  commands.add_parser('download')
  sweepParser=commands.add_parser('sweep')
  sweepParser.add_argument('--model',default='gemma4-e2b-q4_0')
  sweepParser.add_argument('--threads',default='4,6,8,12,14')
  sweepParser.add_argument('--rows',type=int,default=8)
  runParser=commands.add_parser('run')
  runParser.add_argument('--models',default='all')
  runParser.add_argument('--runtimes',default='cpu,cuda')
  runParser.add_argument('--threads',default='4')
  runParser.add_argument('--security',action='store_true')
  commands.add_parser('summary')
  args=parser.parse_args()
  {'download':download,'sweep':sweep,'run':run,'summary':summary}[args.command](args)


if __name__=='__main__':main()
