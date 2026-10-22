import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_streaming_delivers_checked_advice_before_completion_and_cancels(tmp_path):
  code = r'''
import asyncio,json
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from backend import agent, agent_answers as answers, maintenance_ai as ai
from backend.app import app

async def verify():
  delivered=[]
  first='{"answerable":true,"advice":[{"text":"先核對刀位資料。","source":"S1"}'
  last='],"followUp":"有什麼警報？"}'
  class Chunks(httpx.AsyncByteStream):
    async def __aiter__(self):
      yield ('data: '+json.dumps({'choices':[{'delta':{'content':first}}]})+'\n\n').encode()
      assert delivered == [first], '第一段必須在模型完成前送出'
      yield ('data: '+json.dumps({'choices':[{'delta':{'content':last}}]})+'\n\n').encode()
      yield b'data: [DONE]\n\n'
  def handle(request):
    body=json.loads(request.content)
    assert body['stream'] is True
    return httpx.Response(200,stream=Chunks())
  realClient=httpx.AsyncClient
  async def delta(text): delivered.append(text)
  with patch.object(ai.httpx,'AsyncClient',lambda **kw:realClient(transport=httpx.MockTransport(handle),**kw)):
    result,execution=await ai.generate_json('test',answers.Answer.model_json_schema(),onDelta=delta)
  assert result['advice'][0]['text']=='先核對刀位資料。' and execution['llm_used']
  sources={'S1':'核對刀位資料。'}
  assert answers.previewAnswer(first,sources)=='1. 先核對刀位資料。 [S1]'
  assert answers.previewAnswer(first.replace('S1','S999'),sources)==''
  assert answers.previewAnswer(first.replace('先核對','先調整999，再核對'),sources)==''
  assert answers.previewAnswer(first.replace('true','false'),sources)==''
  assert answers.previewAnswer(first[:-2],sources)==''
  assert answers.previewAnswer('{"advice":[{"text":"先核對刀位資料。","source":"S1"}],"answerable":true,',sources)
  stopped=asyncio.Event()
  async def waiting(body,request,onEvent=None):
    try:
      await onEvent({'type':'partial','text':'first'})
      await asyncio.Event().wait()
    finally: stopped.set()
  with patch.object(agent,'chat',waiting):
    stream=agent.streamChat(None,None)
    assert json.loads(await anext(stream))['type']=='status'
    assert json.loads(await anext(stream))['text']=='first'
    await stream.aclose()
    assert stopped.is_set(), '瀏覽器中斷必須取消上游工作'
  async def failing(body,request,onEvent=None): raise RuntimeError('private detail')
  with patch.object(agent,'chat',failing):
    events=[json.loads(item) async for item in agent.streamChat(None,None)]
    assert events[-1]['type']=='error' and 'private detail' not in str(events)

asyncio.run(verify())
with TestClient(app) as client:
  body={'message':'換刀卡住怎麼辦'}
  assert client.post('/api/agent/chat',json=body,headers={'Accept':'application/x-ndjson'}).status_code==401
  login=client.post('/api/auth/demo',json={'role':'engineer'}).json()
  assert client.post('/api/agent/chat',json=body,headers={'Accept':'application/x-ndjson'}).status_code==403
  headers={'Accept':'application/x-ndjson','X-CSRF-Token':login['csrf']}
  response=client.post('/api/agent/chat',json=body,headers=headers)
  assert response.headers['content-type'].startswith('application/x-ndjson')
  events=[json.loads(line) for line in response.text.splitlines()]
  assert events[-1]['type']=='result' and '機型' in events[-1]['result']['reply']
  assert events[-1]['result'].get('proposal') is None
  initial=len(client.get('/api/tickets').json())
  async def planner(prompt,schema,**kwargs):
    return {'tool':'create_ticket','machine':'CNC-01','symptoms':'換刀卡住'}, {'llm_used':True,'model':'test'}
  with patch.object(ai,'generate_json',planner):
    response=client.post('/api/agent/chat',json={'message':'幫 CNC-01 建立換刀卡住工單'},headers=headers)
  events=[json.loads(line) for line in response.text.splitlines()]
  assert [event['type'] for event in events]==['status','result']
  assert events[-1]['result']['proposal']['tool']=='create_ticket'
  assert len(client.get('/api/tickets').json())==initial, '串流不能提前執行草稿'
  async def disconnectScenario():
    disconnected=asyncio.Event()
    closed=asyncio.Event()
    sent=[]
    source={'id':'TEST','chunk_id':'TEST:1','title':'test','text':'核對刀位資料。',
      'machine_models':['TEST-MODEL'],'is_synthetic':True}
    class LiveChunks(httpx.AsyncByteStream):
      async def __aiter__(self):
        first='{"answerable":true,"advice":[{"text":"先核對刀位資料。","source":"S1"}'
        yield ('data: '+json.dumps({'choices':[{'delta':{'content':first}}]})+'\n\n').encode()
        await asyncio.Event().wait()
      async def aclose(self): closed.set()
    realClient=httpx.AsyncClient
    transport=httpx.MockTransport(lambda request:httpx.Response(200,stream=LiveChunks()))
    delivered=False
    async def receive():
      nonlocal delivered
      if not delivered:
        delivered=True
        return {'type':'http.request','body':json.dumps({'message':'TEST-MODEL 換刀卡住怎麼查'}).encode(),'more_body':False}
      await disconnected.wait()
      return {'type':'http.disconnect'}
    async def send(event):
      sent.append(event)
      if event['type']=='http.response.body' and b'"type": "partial"' in event.get('body',b''):
        disconnected.set()
    cookie='; '.join(key+'='+value for key,value in client.cookies.items())
    scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.3'},'http_version':'1.1',
      'method':'POST','scheme':'http','path':'/api/agent/chat','raw_path':b'/api/agent/chat',
      'root_path':'','query_string':b'','server':('testserver',80),'client':('127.0.0.1',1234),
      'headers':[(b'host',b'testserver'),(b'content-type',b'application/json'),
        (b'accept',b'application/x-ndjson'),(b'cookie',cookie.encode()),
        (b'x-csrf-token',login['csrf'].encode())]}
    with patch.object(ai,'corpus',return_value=[source]), patch.object(ai,'search',return_value=[source]), patch.object(ai.httpx,'AsyncClient',lambda **kw:realClient(transport=transport,**kw)):
      await asyncio.wait_for(app(scope,receive,send),timeout=10)
    assert disconnected.is_set() and closed.is_set(), 'ASGI 斷線必須關閉上游 HTTP 串流'
    wire=b''.join(event.get('body',b'') for event in sent)
    assert b'"type": "partial"' in wire and b'"type": "result"' not in wire
  asyncio.run(disconnectScenario())
print('streaming_passed')
'''
  env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'APP_MODE': 'demo', 'DEMO_MODE': '1',
    'OPENAI_ENABLED': '0', 'LLM_PROVIDER': 'llamacpp', 'LOCAL_LLM_MODEL': 'isolated-model',
    'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'stream.db'),
    'BOOTSTRAP_PASSWORD': 'Isolated-Stream-123456'}
  result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
    capture_output=True, text=True, encoding='utf-8', timeout=90)
  assert result.returncode == 0, result.stdout + result.stderr
  assert 'streaming_passed' in result.stdout
