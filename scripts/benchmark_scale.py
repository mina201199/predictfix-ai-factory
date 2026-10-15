"""規模壓測：在隔離 SQLite 灌入大量手冊段落與工單，量測檢索與工單列表延遲、事件迴圈阻塞與記憶體。

用法：
  python scripts/benchmark_scale.py run --paragraphs 1000,10000,30000 --tickets 10000 --label before
資料全是程式產生的假資料，只用來量測效能，不代表檢索或模型準確度。
"""
import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT=Path(__file__).resolve().parents[1]
# 以檔案路徑執行時 sys.path 只有 scripts/，seed 需要專案根目錄才能匯入 backend
sys.path.insert(0,str(ROOT))
PORT=8095
BASE=f'http://127.0.0.1:{PORT}'
PASSWORD='Scale-Benchmark-Password-123456'
SECTIONS=50
MODELS=['SCALE-A','SCALE-B','SCALE-C','SCALE-D','SCALE-E']
PARTS=['主軸','刀庫','換刀臂','冷卻泵','潤滑系統','滾珠螺桿','線性滑軌','夾頭','刀套','伺服馬達','防護門','排屑機']
SYMPTOMS=['異音','溫升','振動升高','卡住','漏油','流量下降','定位誤差','壓力不足','間歇停機','警報']
ACTIONS=['記錄轉速與負載','核對刀位編號','檢查濾網與液位','量測背隙','確認氣壓','比對近期保養紀錄','拍照保存現況','依原廠程序停機隔離']
QUERIES=['換刀卡住 刀位警報','主軸異音 溫升','冷卻泵流量下降','滾珠螺桿定位誤差','防護門警報','潤滑系統漏油','夾頭振動升高','伺服馬達間歇停機','刀庫卡住怎麼查']


def paragraph(rng,index):
  parts=rng.sample(PARTS,2);symptom=rng.choice(SYMPTOMS);actions=rng.sample(ACTIONS,3)
  title=f'{parts[0]}{symptom}排查 {index}'
  text=(f'{parts[0]}{symptom}時，先{actions[0]}，再{actions[1]}；若{parts[1]}同時出現{rng.choice(SYMPTOMS)}，'
        f'應{actions[2]}並通知負責工程師。')*2
  return title,text,parts[0]


def seed(args):
  # 在獨立程序執行：backend.store 匯入時就會固定 DATABASE_URL
  from backend import maintenance_ai, store
  store.init()
  rng=random.Random(args.paragraphs)
  stamp=datetime.now(timezone.utc)
  documents=[]
  for d in range(args.paragraphs//SECTIONS):
    sections=[paragraph(rng,d*SECTIONS+s) for s in range(SECTIONS)]
    model=MODELS[d%len(MODELS)]
    data={'title':f'壓測手冊 {d:05d}','version':'1','machine_model':model,'controller':'','component':sections[0][2],
          'content':'\n'.join(f'## {title}\n{text}\n' for title,text,_ in sections),'is_synthetic':False,
          'source_label':'規模壓測假資料','rights_confirmed':True,'id':f'MAN-SCALE-{d:05d}','source_type':'imported_manual',
          'machine_models':[model],'source_sha256':'0'*64,'imported_by':'scale','imported_at':stamp.isoformat(),
          'source_url':f'/api/knowledge/manuals/MAN-SCALE-{d:05d}','category':'匯入手冊'}
    documents.append(store.KnowledgeDocument(id=data['id'],payload=json.dumps(data,ensure_ascii=False)))
  tickets=[store.Ticket(id=f'WO-SCALE-{i:06d}',machine='CNC-01',issue=f'壓測工單 {i}',engineer='待指派',status='待指派',
                        created_at=stamp-timedelta(seconds=i)) for i in range(args.tickets)]
  # 一半工單帶流程資料，讓工單列表讀到真實的 workflow 欄位
  workflows=[store.Workflow(id=f'WO-SCALE-{i:06d}',payload=json.dumps({'reviews':[],'note':f'流程 {i}'},ensure_ascii=False))
             for i in range(0,args.tickets,2)]
  with store.Session() as db:
    db.add_all(documents+tickets+workflows);db.commit()
  print(json.dumps({'documents':len(documents),'paragraphs':len(maintenance_ai.corpus()),'tickets':args.tickets}))


def peakMemoryMb(pid):
  # Windows 的 venv python.exe 只是啟動器，實際執行伺服器的是它的子程序
  command=(f'$child=Get-CimInstance Win32_Process -Filter "ParentProcessId={pid}" | Select-Object -First 1; '
           f'$target=if($child){{$child.ProcessId}}else{{{pid}}}; (Get-Process -Id $target).PeakWorkingSet64')
  value=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,text=True,timeout=60).stdout.strip()
  return round(int(value)/2**20) if value.isdigit() else None


def timedPost(client,path,body):
  start=time.perf_counter();response=client.post(path,json=body)
  return time.perf_counter()-start,response


def worstHealthDuring(client,body):
  # 查詢進行時另一條連線持續打 /healthz；若事件迴圈被同步運算卡住，這裡的延遲會跟著變長
  stop=threading.Event();worst=[0.0]
  def ping():
    with httpx.Client(base_url=BASE,timeout=120) as probe:
      while not stop.is_set():
        start=time.perf_counter();probe.get('/healthz');worst[0]=max(worst[0],time.perf_counter()-start)
        time.sleep(0.05)
  thread=threading.Thread(target=ping);thread.start();time.sleep(0.3)
  client.post('/api/assist',json=body);stop.set();thread.join()
  return round(worst[0],3)


def portBusy():
  try:
    httpx.get(BASE+'/healthz',timeout=1);return True
  except httpx.HTTPError:
    return False


def stopServer(server):
  # venv 的 python.exe 只是啟動器，只結束它時實際的伺服器子程序會晚一點才結束；關掉整個程序樹並等連接埠釋放
  subprocess.run(['taskkill','/PID',str(server.pid),'/T','/F'],capture_output=True)
  server.wait(timeout=30)
  for _ in range(60):
    if not portBusy():return
    time.sleep(0.5)
  raise RuntimeError(f'{PORT} 連接埠在 30 秒內未釋放')


def measure(paragraphs,tickets):
  if portBusy():
    # 若沿用到前一輪或其他程式的伺服器，量到的會是錯誤的資料庫
    raise SystemExit(f'{PORT} 已有服務在執行，請先關閉')
  (ROOT/'.runtime').mkdir(exist_ok=True)
  with tempfile.TemporaryDirectory(prefix='scale-',dir=ROOT/'.runtime',ignore_cleanup_errors=True) as temp:
    env={**os.environ,'APP_MODE':'production','DEMO_MODE':'0','DATABASE_URL':'sqlite:///'+str(Path(temp)/'scale.db'),
         'BOOTSTRAP_PASSWORD':PASSWORD,'LOCAL_LLM_MODEL':'','OLLAMA_MODEL':'','OPENAI_ENABLED':'0','OPENAI_API_KEY':'',
         'PYTHONDONTWRITEBYTECODE':'1'}
    seeded=subprocess.run([sys.executable,__file__,'seed','--paragraphs',str(paragraphs),'--tickets',str(tickets)],
                          cwd=ROOT,env=env,capture_output=True,text=True,timeout=1800,check=True)
    counts=json.loads(seeded.stdout.strip().splitlines()[-1])
    server=subprocess.Popen([sys.executable,'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(PORT)],
                            cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
      for _ in range(120):
        try:
          if httpx.get(BASE+'/healthz',timeout=2).status_code==200:break
        except httpx.HTTPError:
          time.sleep(0.5)
      client=httpx.Client(base_url=BASE,headers={'Origin':BASE},timeout=600)
      login=client.post('/api/auth/login',json={'username':'supervisor','password':PASSWORD})
      client.headers['x-csrf-token']=login.json()['csrf']
      idle=[]
      for _ in range(5):
        start=time.perf_counter();client.get('/healthz');idle.append(time.perf_counter()-start)
      body=lambda q:{'question':q,'use_llm':False}
      cold,first=timedPost(client,'/api/assist',body(QUERIES[0]))
      warm=[];citations=[]
      for query in QUERIES[1:]:
        seconds,response=timedPost(client,'/api/assist',body(query));warm.append(seconds)
        citations.append(len(response.json().get('citations',[])))
      blocked=[worstHealthDuring(client,body(q)) for q in QUERIES[:3]]
      listTimes=[];ticketCount=None
      for _ in range(3):
        start=time.perf_counter();response=client.get('/api/tickets');listTimes.append(time.perf_counter()-start)
        ticketCount=len(response.json())
      return {**counts,'assist_cold_seconds':round(cold,3),'assist_warm_median_seconds':round(statistics.median(warm),3),
              'assist_warm_max_seconds':round(max(warm),3),'citations_per_query':citations,
              'idle_healthz_median_seconds':round(statistics.median(idle),3),'healthz_worst_during_assist_seconds':blocked,
              'ticket_list_median_seconds':round(statistics.median(listTimes),3),'ticket_list_count':ticketCount,
              'server_peak_working_set_mb':peakMemoryMb(server.pid)}
    finally:
      stopServer(server)


def run(args):
  path=ROOT/args.output
  report=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'runs':{}}
  results={}
  for paragraphs in [int(n) for n in args.paragraphs.split(',')]:
    print(f'== {args.label}: {paragraphs} 段落、{args.tickets} 張工單',flush=True)
    results[str(paragraphs)]=measure(paragraphs,args.tickets)
    print(json.dumps(results[str(paragraphs)],ensure_ascii=False),flush=True)
  report['runs'][args.label]={'measured_at':datetime.now(timezone.utc).isoformat(),'tickets':args.tickets,'results':results}
  report['method']={'data':'程式產生的假手冊與工單，僅量測效能','assist':'POST /api/assist，use_llm=false，未指定機型（檢索全部段落）',
                    'blocking':'查詢期間另一條連線每 50ms 打 /healthz 的最長延遲','server':'uvicorn 單一 process，production 模式'}
  path.parent.mkdir(parents=True,exist_ok=True)
  path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
  parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
  commands=parser.add_subparsers(dest='command',required=True)
  seedParser=commands.add_parser('seed')
  seedParser.add_argument('--paragraphs',type=int,required=True)
  seedParser.add_argument('--tickets',type=int,required=True)
  runParser=commands.add_parser('run')
  runParser.add_argument('--paragraphs',default='1000,10000,30000')
  runParser.add_argument('--tickets',type=int,default=10000)
  runParser.add_argument('--label',required=True)
  runParser.add_argument('--output',default='artifacts/scale-benchmark.json')
  args=parser.parse_args()
  {'seed':seed,'run':run}[args.command](args)


if __name__=='__main__':main()
