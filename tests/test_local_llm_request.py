import json
import os
import subprocess
import sys


def test_local_llm_prompts_are_sent_without_qwen_only_suffix(tmp_path):
  # 匯入 backend 會固定 DATABASE_URL，必須在子程序執行，避免影響 test_api 的隔離資料庫
  code='''
import asyncio,json
import httpx
from backend import copilot, maintenance_ai
sent=[]
class Reply:
    def raise_for_status(self):pass
    def json(self):return {'choices':[{'message':{'content':json.dumps({'selected':[],'machine_id':None,'symptoms':[],'temperature_c':None,'error_code':None,'answer':'x'})}}]}
async def post(self,url,json=None,**kwargs):
    sent.append(json['messages'][0]['content']);return Reply()
httpx.AsyncClient.post=post
asyncio.run(maintenance_ai.generate_json('PROMPT',{'type':'object'}))
asyncio.run(copilot.analyze('CNC-03 主軸異音，振動升高'))
print(json.dumps(sent))
'''
  env={**os.environ,'DATABASE_URL':'sqlite:///'+str(tmp_path/'isolated.db'),'APP_MODE':'demo','DEMO_MODE':'1',
       'LLM_PROVIDER':'llamacpp','LOCAL_LLM_MODEL':'gemma-4-E2B-it-Q8_0','OPENAI_ENABLED':'0','OPENAI_API_KEY':''}
  result=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True,timeout=120)
  assert result.returncode==0,result.stderr
  sent=json.loads(result.stdout.strip().splitlines()[-1])
  # 兩條本機模型路徑都要被呼叫到，否則這個測試沒有檢查到 copilot
  assert len(sent)==2
  # /no_think 只對 Qwen3 有意義，對其他模型只是混進 prompt 的雜訊
  assert sent[0]=='PROMPT' and not any('/no_think' in prompt for prompt in sent)
