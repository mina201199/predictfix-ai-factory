import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from backend import agent, agent_answers as answers, maintenance_ai as ai


def test_citation_label_is_not_a_new_maintenance_number():
  sources = {'S1': '記錄刀位、警報及近期變更。'}
  valid = answers.Advice(text='來源S1提到應記錄刀位、警報及近期變更。', source='S1')
  assert answers.checkedAdvice(valid, sources)
  assert answers.checkedAdvice(answers.Advice(text='記錄刀位、警報及近期變更。[S1]', source='S1'), sources)
  for text in ['來源S1要求調整1毫米。', '來源S10要求檢查。', '檢查XS1部件。', '檢查S1部件。', '轉速增加100。']:
    assert not answers.checkedAdvice(answers.Advice(text=text, source='S1'), sources)


def test_explicit_question_after_assignment_uses_one_model_call():
  context = {'machines': [
    {'id': 'CNC-01', 'name': '測試設備', 'model': 'TEST-ATC'},
    {'id': 'CNC-02', 'name': '另一設備', 'model': 'TEST-OTHER'}],
    'engineers': [], 'tickets': [{'id': 'WO-test123', 'machine': 'CNC-01'}]}
  history = [
    {'role': 'user', 'content': '建立工單：CNC-01 換刀卡住'},
    {'role': 'assistant', 'content': '請確認草稿'},
    {'role': 'assistant', 'content': '已建立工單 WO-test123'},
    {'role': 'user', 'content': '請派工 WO-test123 給測試工程師'},
    {'role': 'assistant', 'content': '請確認派工草稿'},
    {'role': 'assistant', 'content': '已完成派工 WO-test123'}]
  calls = []
  source = {'id': 'manual', 'text': '記錄刀位、警報及近期變更。', 'machine_models': ['TEST-ATC']}

  async def model(prompt, schema, **kwargs):
    calls.append(schema['title'])
    if schema['title'] == 'Decision':
      return {'tool': 'knowledge', 'machine': 'CNC-01', 'question': '那現場要記錄哪些資訊？'}, {'llm_used': True}
    return {'answerable': True, 'advice': [{'text': '記錄刀位、警報及近期變更。', 'source': 'S1'}]}, {'llm_used': True}

  def search(query, **kwargs):
    assert kwargs['machine_model'] == 'TEST-ATC'
    return [source]

  async def run():
    request = SimpleNamespace(state=SimpleNamespace(user={'role': 'supervisor'}))
    body = agent.ChatInput(message='那現場要記錄哪些資訊？', history=history)
    result = await agent.chat(body, request)
    assert calls == ['Answer'], calls
    assert 'CNC-01 · TEST-ATC' in result['reply']
    assert 'proposal' not in result
    for message in ['CNC-01', '換刀卡住', '請派工 WO-test123', '取消草稿', '要怎麼確認？', '哪一位工程師？']:
      assert await agent.fastKnowledge(agent.ChatInput(message=message, history=history), context) is None
    unknown = history[:3] + [{'role': 'user', 'content': '請派工 WO-unknown'}]
    assert await agent.fastKnowledge(agent.ChatInput(message=body.message, history=unknown), context) is None
    changed = history + []
    changed[-1] = {'role': 'user', 'content': '換成 UNKNOWN-99'}
    assert await agent.fastKnowledge(agent.ChatInput(message=body.message, history=changed), context) is None
    ambiguous = history[:3] + [{'role': 'user', 'content': 'CNC-02 和 WO-test123'}]
    result = await agent.fastKnowledge(agent.ChatInput(message=body.message, history=ambiguous), context)
    assert result['execution']['reason'] == 'needs_context'

  with patch.object(agent, 'readContext', return_value=context), patch.object(agent.openai_runtime, 'configured', return_value=False), \
      patch.object(ai, 'corpus', return_value=[source]), patch.object(ai, 'search', search), patch.object(ai, 'generate_json', model):
    asyncio.run(run())
