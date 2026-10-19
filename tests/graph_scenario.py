"""隔離合成來源；不呼叫 LLM、不連線實際工廠。"""
import json
import sys
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import app
from backend import store, maintenance_ai

passed = 0


def check(condition):
  global passed
  assert condition
  passed += 1


def seedManual(mid='SYNTH-MAN', model='SYNTH-M1'):
  doc = {'id': mid, 'title': '合成圖譜測試', 'version': '1',
    'machine_models': [model], 'component': '主軸', 'is_synthetic': True,
    'content': '## 合成段落\nE01 指向濾芯；濾芯排查需要壓差確認；壓差確認需要備品 FILTER-A；壓差確認需要資格 LOTO。',
    'source_type': 'synthetic_fixture', 'source_url': '/api/knowledge/manuals/' + mid}
  with store.Session() as db:
    db.add(store.KnowledgeDocument(id=mid, payload=json.dumps(doc), active=1))
    db.commit()
  return next(c for c in maintenance_ai.buildCorpus() if c['id'] == mid)


def candidate(source, headKind='alarm', head='E01', tailKind='part', tail='濾芯', relation='references'):
  return {'sourceChunkId': source['chunk_id'], 'machineModel': source['machine_models'][0],
    'head': {'kind': headKind, 'label': head}, 'tail': {'kind': tailKind, 'label': tail},
    'relation': relation, 'quote': source['text']}


def create(client, body):
  response = client.post('/api/graph/candidates', json=body)
  assert response.status_code == 200, response.text
  return response.json()


def review(client, edge, action='approve'):
  response = client.post('/api/graph/relations/' + edge['id'] + '/review',
    json={'revision': edge['revision'], 'action': action, 'note': '合成來源人工核對'})
  assert response.status_code == 200, response.text
  return response.json()

with TestClient(app) as client:
  login = client.post('/api/auth/demo', json={'role': 'supervisor'}).json()
  client.headers['X-CSRF-Token'] = login['csrf']
  response = client.post('/api/graph/query', json={'machineModel': 'SYNTH-M1', 'query': 'E01'})
  assert response.status_code == 200, response.text
  source = seedManual()
  body = candidate(source)
  edge = create(client, body)
  check(create(client, body)['id'] == edge['id'])
  query = {'machineModel': 'SYNTH-M1', 'query': 'E01', 'maxHops': 3}
  check(client.post('/api/graph/query', json=query).json()['paths'] == [])
  edge = review(client, edge)
  check(edge['approvedBy'] == 'supervisor' and edge['status'] == 'approved')
  from backend import knowledge_graph as graph
  from backend.graph_sources import currentSources
  from backend.graph_models import GraphRelation
  from fastapi import HTTPException
  current = currentSources()
  def concurrentReview():
    with store.Session() as other:
      row = other.get(GraphRelation, edge['id'])
      row.revision += 1
      data = json.loads(row.payload)
      data['history'].append({'note': '另一主管剛保存的紀錄'})
      row.payload = json.dumps(data)
      other.commit()
    return current
  rejected = False
  with store.Session() as db, patch.object(graph, 'currentSources', concurrentReview):
    try:
      graph.reviewRelation(db, edge['id'], graph.ReviewInput(revision=edge['revision'] + 1,
        action='approve', note='預送未讀取的未來版號'), 'supervisor')
      db.commit()
    except HTTPException as error:
      rejected = error.status_code == 409
      db.rollback()
  check(rejected)
  with store.Session() as db, patch.object(graph, 'currentSources', concurrentReview):
    try:
      graph.reviewRelation(db, edge['id'], graph.ReviewInput(revision=edge['revision'],
        action='approve', note='與另一主管同時審查'), 'supervisor')
      db.commit()
      raise AssertionError('並行審查應拒絕舊版號')
    except HTTPException as error:
      check(error.status_code == 409)
      db.rollback()
  with store.Session() as db:
    saved = db.get(GraphRelation, edge['id'])
    check(json.loads(saved.payload)['history'][-1]['note'] == '另一主管剛保存的紀錄')
    edge['revision'] = saved.revision
  stale = client.post('/api/graph/relations/' + edge['id'] + '/review',
    json={'revision': 1, 'action': 'withdraw', 'note': '過期版本'})
  check(stale.status_code == 409)
  step = review(client, create(client, candidate(source, 'part', '濾芯', 'inspect_step', '壓差確認', 'inspect')))
  spare = review(client, create(client, candidate(source, 'inspect_step', '壓差確認', 'spare', 'FILTER-A', 'requires_spare')))
  qualification = review(client, create(client, candidate(source, 'inspect_step', '壓差確認', 'qualification', 'LOTO', 'requires_qualification')))
  paths = client.post('/api/graph/query', json=query).json()['paths']
  check(any(len(p['relations']) == 3 and p['nodes'][-1]['label'] == 'FILTER-A' for p in paths))
  check(any(p['nodes'][-1]['label'] == 'LOTO' for p in paths))
  check(all(r['citation']['sourceId'] == source['id'] and r['citation']['quote'] in source['text']
    for p in paths for r in p['relations']))
  check(client.post('/api/graph/query', json={**query, 'maxHops': 1}).json()['paths'] and
    all(len(p['relations']) == 1 for p in client.post('/api/graph/query', json={**query, 'maxHops': 1}).json()['paths']))
  check(client.post('/api/graph/query', json={**query, 'maxHops': 4}).status_code == 422)
  check(client.post('/api/graph/query', json={**query, 'machineModel': 'OTHER'}).json()['paths'] == [])
  check(client.post('/api/graph/query', json={**query, 'query': 'E0'}).json()['paths'] == [])
  check(client.post('/api/graph/query', json={**query, 'query': 'FILTER-A'}).json()['paths'] == [])
  check(client.post('/api/graph/candidates', json={**body, 'quote': '假引文'}).status_code == 422)
  check(client.post('/api/graph/candidates', json={**body, 'machineModel': 'OTHER'}).status_code == 422)
  check(client.post('/api/graph/candidates', json={**body, 'relation': 'automatically_restart'}).status_code == 422)
  check(client.post('/api/graph/candidates', json={**body, 'approvedBy': 'supervisor'}).status_code == 422)
  check(client.post('/api/graph/query', json={**query, 'relations': ['requires_spare']}).json()['paths'] == [])
  check(client.post('/api/graph/query', json={**query, 'limit': 1}).json()['truncated'])
  with patch.dict(graph.LIMITS, {'maxExpansions': 1}):
    bounded = client.post('/api/graph/query', json=query).json()
    check(bounded['truncated'] and len(bounded['paths']) <= 1)
  review(client, create(client, candidate(source, 'part', '濾芯', 'alarm', 'E01', 'references')))
  check(all(len({node['id'] for node in path['nodes']}) == len(path['nodes'])
    for path in client.post('/api/graph/query', json=query).json()['paths']))
  assisted = client.post('/api/graph/assist', json={**query, 'useGraph': True}).json()
  check(assisted['paths'] and assisted['retrieval'] and assisted['automaticActions'] == [])
  check(client.post('/api/graph/assist', json={**query, 'useGraph': False}).json()['paths'] == [])
  with store.Session() as db:
    from backend.graph_models import GraphRelation
    check(db.get(GraphRelation, edge['id']).status == 'approved')
    row = db.get(store.KnowledgeDocument, source['id'])
    row.active = 0
    db.commit()
  check(client.post('/api/graph/query', json=query).json()['paths'] == [])
  check(client.post('/api/graph/relations/' + step['id'] + '/review',
    json={'revision': step['revision'], 'action': 'approve', 'note': '撤回來源'}).status_code == 409)
  with store.Session() as db:
    row = db.get(store.KnowledgeDocument, source['id'])
    row.active = 1
    doc = json.loads(row.payload)
    doc['version'] = '2'
    row.payload = json.dumps(doc)
    db.commit()
  check(client.post('/api/graph/query', json=query).json()['paths'] == [])
  with store.Session() as db:
    from sqlalchemy import select
    for index, row in enumerate(db.scalars(select(GraphRelation)).all()):
      for savedRelation in [edge, step, spare, qualification]:
        if savedRelation['id'] == row.id:
          savedRelation['id'] = 'GR-000-stale-' + str(index)
      row.id = 'GR-000-stale-' + str(index)
    db.commit()
  newSource = seedManual('SYNTH-FRESH')
  review(client, create(client, candidate(newSource)))
  with patch.dict(graph.LIMITS, {'maxEdges': 2, 'maxRowsScanned': 20}):
    check(client.post('/api/graph/query', json=query).json()['paths'])
  with patch.dict(graph.LIMITS, {'maxRowsScanned': 1}):
    check(client.post('/api/graph/query', json=query).json()['truncated'])
  template = {'name': '合成模板', 'parts': ['合成零件', '1/2"接頭'], 'steps': [
    {'label': '檢查合成零件\\標記', 'kind': 'inspect', 'criterion': '記錄'},
    {'label': '驗收合成零件', 'kind': 'verify', 'criterion': '記錄'}]}
  with store.Session() as db:
    db.add(store.EquipmentTemplate(id='SYNTH-TPL', revision=1, payload=json.dumps(template)))
    db.add(store.StockItem(id='SYNTH-STOCK', name='合成備品', unit='個', quantity=1, minimum=0))
    db.add(store.EngineerProfile(username='isolated-fixture', payload=json.dumps({'qualifications': ['合成資格']})))
    db.commit()
  first = client.post('/api/graph/rebuild').json()
  second = client.post('/api/graph/rebuild').json()
  check(first['created'] > 0 and second['created'] == 0)
  with store.Session() as db:
    from backend.graph_models import GraphNode
    check(db.scalar(select(GraphNode).where(GraphNode.kind == 'spare', GraphNode.label == '合成備品')) is not None)
    check(db.scalar(select(GraphNode).where(GraphNode.kind == 'qualification', GraphNode.label == '合成資格')) is not None)
  check(not client.post('/api/graph/query', json={**query, 'query': '合成備品'}).json()['paths'])
  check(any(r['tail']['label'] == '1/2"接頭' for r in client.get('/api/graph/candidates').json()))
  templateEdges = [r for r in client.get('/api/graph/candidates').json() if r['machineModel'] == 'SYNTH-TPL']
  for relation in templateEdges:
    review(client, relation)
  check(client.post('/api/graph/query', json={'machineModel': 'SYNTH-TPL', 'query': 'SYNTH-TPL'}).json()['paths'])
  with store.Session() as db:
    row = db.get(store.EquipmentTemplate, 'SYNTH-TPL')
    row.revision += 1
    db.commit()
  check(not client.post('/api/graph/query', json={'machineModel': 'SYNTH-TPL', 'query': 'SYNTH-TPL'}).json()['paths'])
  caseFields = {'title': '合成案例圖譜', 'machine_model': 'SYNTH-CASE-M', 'component': '主軸',
    'symptoms': '異音', 'conditions': '合成條件', 'findings': '合成發現',
    'cause_status': 'unknown', 'root_cause': '尚未確認', 'actions': '核對主軸',
    'verification': '保存復測', 'is_synthetic': True}
  with store.Session() as db:
    db.add(store.RepairCase(id='SYNTH-CASE', ticket_id='SYNTH-TICKET', status='published', revision=1,
      payload=json.dumps({'fields': caseFields, 'source_sha256': 'fixture', 'published_by': 'supervisor',
        'published_at': '2026-10-19T00:00:00Z'})))
    db.commit()
  client.post('/api/graph/rebuild')
  for relation in client.get('/api/graph/candidates').json():
    if relation['machineModel'] == 'SYNTH-CASE-M':
      review(client, relation)
  caseQuery = {'machineModel': 'SYNTH-CASE-M', 'query': 'SYNTH-CASE-M'}
  check(client.post('/api/graph/query', json=caseQuery).json()['paths'])
  with store.Session() as db:
    row = db.get(store.RepairCase, 'SYNTH-CASE')
    row.status = 'draft'
    db.commit()
  check(not client.post('/api/graph/query', json=caseQuery).json()['paths'])
  with store.Session() as db:
    row = db.get(store.RepairCase, 'SYNTH-CASE')
    row.status = 'published'
    data = json.loads(row.payload)
    data['published_at'] = '2026-10-19T01:00:00Z'
    row.payload = json.dumps(data)
    db.commit()
  check(not client.post('/api/graph/query', json=caseQuery).json()['paths'])
  check(any(s['sourceType'] == 'equipment_template' for s in client.get('/api/graph/sources').json()))
  page = client.get('/graph.html')
  check(page.status_code == 200 and "script-src 'self'" in page.headers['content-security-policy'])
  withdrawn = review(client, spare, 'withdraw')
  check(withdrawn['status'] == 'withdrawn' and withdrawn['reviewedBy'] == 'supervisor')
  engineer = client.post('/api/auth/demo', json={'role': 'engineer'}).json()
  client.headers['X-CSRF-Token'] = engineer['csrf']
  check(client.get('/api/graph/candidates').status_code == 403)
  check(client.get('/api/graph/sources').status_code == 403)
  check(client.post('/api/graph/rebuild').status_code == 403)
  check(client.post('/api/graph/candidates', json=body).status_code == 403)
  check(client.post('/api/graph/relations/' + edge['id'] + '/review',
    json={'revision': edge['revision'], 'action': 'withdraw', 'note': '偽裝主管'}).status_code == 403)
  check(client.post('/api/graph/query', json=query).status_code == 200)
  with store.Session() as db:
    db.get(store.RepairCase, 'SYNTH-CASE').status = 'draft'
    db.commit()
  check('合成案例圖譜' not in client.post('/api/graph/assist', json=caseQuery).text)
  client.cookies.clear()
  check(client.post('/api/graph/query', json=query).status_code == 401)
  print(json.dumps({'passed': passed}))
