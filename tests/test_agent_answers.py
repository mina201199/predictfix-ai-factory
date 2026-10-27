import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_plain_language_answers_are_grounded_and_fast_queries_use_one_call(tmp_path):
  env = {**os.environ, 'APP_MODE': 'demo', 'DEMO_MODE': '1', 'OPENAI_ENABLED': '0',
    'BOOTSTRAP_PASSWORD': 'Isolated-Plain-Agent-123456', 'PYTHONUTF8': '1',
    'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'answers.db'),
    'LOCAL_LLM_MODEL': '', 'OLLAMA_MODEL': ''}
  script = '''
import asyncio,json
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import app
from backend import agent, agent_answers as answers, maintenance_ai as ai, store

source = {'id': 'MAN-TEST', 'chunk_id': 'MAN-TEST:1', 'title': '換刀手冊',
  'text': '虛構情境：換刀卡住時，先記錄刀位與警報，核對刀具主檔。', 'version': '1',
  'machine_models': ['TEST-ATC'], 'is_synthetic': True, 'source_url': '/api/knowledge/manuals/MAN-TEST'}
output = {'answerable': True, 'advice': [{'text': '先記下卡住的刀位和警報，再核對刀具資料。', 'source': 'S1'}],
  'followUp': '卡住時有出現什麼警報？'}
calls = []
async def model(prompt, schema, **kwargs):
  calls.append((prompt, kwargs))
  assert '刀具主檔' in prompt
  assert kwargs['maxTokens'] <= 260
  return output, {'llm_used': True, 'model': 'isolated-model'}
def search(query, **kwargs):
  assert kwargs['machine_model'] == 'TEST-ATC'
  return [source, {**source, 'id': 'DUPLICATE', 'chunk_id': 'DUPLICATE:1'}]

with TestClient(app) as client, patch.object(ai, 'generate_json', model), patch.object(ai, 'search', search):
  login = client.post('/api/auth/demo', json={'role': 'supervisor'}).json()
  headers = {'X-CSRF-Token': login['csrf']}
  with store.Session() as db:
    machine = db.get(store.Machine, 'CNC-01')
    data = json.loads(machine.payload)
    data['machine_model'] = 'TEST-ATC'
    machine.payload = json.dumps(data)
    db.commit()
  def chat(message, history=[]):
    response = client.post('/api/agent/chat', headers=headers, json={'message': message, 'history': history})
    assert response.status_code == 200, response.text
    return response.json()
  missing = chat('換刀卡住怎麼辦')
  assert '機型' in missing['reply'] and len(calls) == 0, missing
  result = chat('TEST-ATC 換刀卡住怎麼查？')
  assert len(calls) == 1, calls
  assert '先記下卡住' in result['reply'] and '[S1]' in result['reply'], result
  assert source['text'] not in result['reply']
  assert result['rag']['answer_method'] == 'grounded_paraphrase'
  assert len(result['rag']['citations']) == 1
  assert result['rag']['steps'] == []
  assert result['rag']['follow_up'] == ['卡住時有出現什麼警報？']
  factual = chat('TEST-ATC 新增刀具後，換刀卡住怎麼查？')
  assert len(calls) == 2 and factual['rag']['answer_method'] == 'grounded_paraphrase'
  follow = chat('那警報要記錄什麼？', [{'role': 'user', 'content': 'TEST-ATC 換刀卡住'},
    {'role': 'assistant', 'content': result['reply']}])
  assert len(calls) == 3 and follow['rag']['answer_method'] == 'grounded_paraphrase'
  assert '那警報要記錄什麼' in calls[-1][0]
  assert '先記下卡住' not in calls[-1][0]
  output['answerable'] = False
  unsupported = chat('那要核對哪些欄位？', [{'role': 'user', 'content': 'TEST-ATC 換刀卡住'}])
  assert unsupported['rag']['answer_method'] == 'insufficient_evidence'
  assert '先記下卡住' not in unsupported['reply']
  assert '不足以回答' in unsupported['reply']
  assert len(calls) == 3
  source['text'] += '欄位清單請見另一份手冊。'
  insufficient = chat('TEST-ATC 欄位有哪些？')
  assert insufficient['rag']['answer_method'] == 'insufficient_evidence'
  assert '先記下卡住' not in insufficient['reply']
  source['text'] = source['text'].replace('欄位清單請見另一份手冊。', '')
  output['answerable'] = True
  mismatch = chat('CNC-01 機型 PF-VMC850-DEMO，換刀卡住')
  assert '不一致' in mismatch['reply'] and len(calls) == 4
  ambiguous = chat('CNC-01 和 CNC-02 換刀卡住')
  assert ambiguous.get('rag') is None and len(calls) == 4
  # 同一次查找不能把模型自創的引用顯示為可信來源。
  output['advice'][0]['source'] = 'S999'
  invalid = chat('TEST-ATC 換刀卡住怎麼查？')
  assert invalid['rag']['answer_method'] == 'retrieval_only' and '先記下卡住' not in invalid['reply']
  output['advice'][0] = {'text': '把壓力升到999 bar。', 'source': 'S1'}
  invented = chat('TEST-ATC 換刀卡住怎麼查？')
  assert invented['rag']['answer_method'] == 'retrieval_only' and '999' not in invented['reply']
  count = len(calls)
  with patch.object(ai, 'search', return_value=[]):
    empty = chat('TEST-ATC 換刀卡住怎麼查？')
  assert len(calls) == count and empty['rag']['answer_method'] == 'insufficient_evidence'
  # 動作與尚未完成的動作追問，不可被快速查詢截走。
  context = agent.readContext({'role': 'supervisor'})
  assert asyncio.run(agent.fastKnowledge(agent.ChatInput(message='幫 CNC-01 建立換刀工單'), context)) is None
  assert asyncio.run(agent.fastKnowledge(agent.ChatInput(message='CNC-01', history=[
    agent.Turn(role='user', content='幫我建立報修工單'),
    agent.Turn(role='assistant', content='這張工單要報修哪台設備？')]), context)) is None
  assert asyncio.run(agent.fastKnowledge(agent.ChatInput(message='換刀卡住', history=[
    agent.Turn(role='user', content='幫 CNC-01 報修'),
    agent.Turn(role='assistant', content='請問設備有什麼異常？')]), context)) is None
  for message in ['CNC-01 機型是 OTHER-MODEL，換刀怎麼查', '不是 TEST-ATC，改成 OTHER-MODEL，換刀怎麼查']:
    assert asyncio.run(agent.fastKnowledge(agent.ChatInput(message=message), context)) is None
print('plain_agent_passed')
'''
  result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env,
    capture_output=True, text=True, encoding='utf-8', timeout=90)
  assert result.returncode == 0, result.stdout + result.stderr
  assert 'plain_agent_passed' in result.stdout
