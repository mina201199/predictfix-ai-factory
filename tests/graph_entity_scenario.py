"""隔離合成來源實體；同名不可視為同一案例或段落。"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend import store, knowledge_graph as graph
from backend.graph_models import GraphNode, GraphRelation
from backend.graph_sources import currentSources, sourceHash
from backend.app import app

MODEL = 'SYNTH-ENTITY-M'
passed = 0


def check(condition):
  global passed
  assert condition
  passed += 1


def body(source, headKind, head, tailKind, tail, relation='references'):
  return {'sourceChunkId': source['chunkId'], 'machineModel': MODEL,
    'head': {'kind': headKind, 'label': head}, 'tail': {'kind': tailKind, 'label': tail},
    'relation': relation, 'quote': source['text']}


def approve(client, candidate):
  result = client.post('/api/graph/candidates', json=candidate)
  assert result.status_code == 200, result.text
  row = result.json()
  result = client.post('/api/graph/relations/' + row['id'] + '/review',
    json={'revision': row['revision'], 'action': 'approve', 'note': '合成實體來源核對'})
  assert result.status_code == 200, result.text
  return result.json()


def paths(client, query):
  result = client.post('/api/graph/query', json={'machineModel': MODEL, 'query': query})
  assert result.status_code == 200, result.text
  return result.json()['paths']


with TestClient(app) as client:
  login = client.post('/api/auth/demo', json={'role': 'supervisor'}).json()
  client.headers['X-CSRF-Token'] = login['csrf']
  for caseId, alarm, spare in [('CASE-A', 'E-A', 'SPARE-A'), ('CASE-B', 'E-B', 'SPARE-B')]:
    fields = {'title': '相同案例標題', 'machine_model': MODEL, 'component': '合成零件',
      'symptoms': alarm, 'conditions': '合成條件', 'findings': '合成發現',
      'cause_status': 'unknown', 'root_cause': '未知', 'actions': spare,
      'verification': '合成復測', 'is_synthetic': True}
    with store.Session() as db:
      db.add(store.RepairCase(id=caseId, ticket_id='WO-' + caseId, status='published', revision=1,
        payload=json.dumps({'fields': fields, 'source_sha256': 'synthetic-fixture',
          'published_by': 'supervisor', 'published_at': '2026-10-19T00:00:00Z'})))
      db.commit()
  sources = currentSources()
  caseA = next(s for s in sources.values() if s['sourceId'] == 'CASE-A')
  caseB = next(s for s in sources.values() if s['sourceId'] == 'CASE-B')
  alarmA = approve(client, body(caseA, 'alarm', 'E-A', 'case', '相同案例標題'))
  spareB = approve(client, body(caseB, 'case', '相同案例標題', 'spare', 'SPARE-B', 'requires_spare'))
  check(not any(p['nodes'][-1]['label'] == 'SPARE-B' for p in paths(client, 'E-A')))
  check(alarmA['tail']['id'] != spareB['head']['id'])
  approve(client, body(caseB, 'alarm', 'E-B', 'case', '相同案例標題'))
  check(any(p['nodes'][-1]['label'] == 'SPARE-B' for p in paths(client, 'E-B')))
  # 同一案例的不同段落仍須能連接；段落內容屬合成固定 fixture。
  otherChunk = {**caseA, 'chunkId': caseA['chunkId'] + ':second', 'text': '同一案例另一段記載 SPARE-A。'}
  with patch.object(graph, 'currentSources', return_value={**sources, otherChunk['chunkId']: otherChunk}):
    spareA = approve(client, body(otherChunk, 'case', '相同案例標題', 'spare', 'SPARE-A', 'requires_spare'))
    check(alarmA['tail']['id'] == spareA['head']['id'])
    check(any(p['nodes'][-1]['label'] == 'SPARE-A' and len(p['relations']) == 2 for p in paths(client, 'E-A')))

  # 段落標題同名：不同手冊，以及同一手冊的不同段落，都不應合併。
  for mid in ['MAN-A', 'MAN-B']:
    content = ('## 相同段落\n相同段落記載 ALARM-' + mid + ' 與 PART-' + mid + '\n'
      '## 相同段落\n相同段落記載 SECOND-' + mid + ' 與 TOOL-' + mid)
    with store.Session() as db:
      db.add(store.KnowledgeDocument(id=mid, active=1, payload=json.dumps({'id': mid,
        'title': '相同手冊標題', 'version': '1', 'machine_models': [MODEL], 'is_synthetic': True,
        'source_type': 'synthetic_entity_fixture', 'content': content})))
      db.commit()
  sources = currentSources()
  manualA = next(s for s in sources.values() if s['sourceId'] == 'MAN-A' and 'ALARM-MAN-A' in s['text'])
  manualB = next(s for s in sources.values() if s['sourceId'] == 'MAN-B' and 'ALARM-MAN-B' in s['text'])
  secondA = next(s for s in sources.values() if s['sourceId'] == 'MAN-A' and 'SECOND-MAN-A' in s['text'])
  sectionA = approve(client, body(manualA, 'alarm', 'ALARM-MAN-A', 'manual_section', '相同段落'))
  sectionB = approve(client, body(manualB, 'manual_section', '相同段落', 'part', 'PART-MAN-B'))
  sectionSecond = approve(client, body(secondA, 'manual_section', '相同段落', 'part', 'TOOL-MAN-A'))
  check(sectionA['tail']['id'] != sectionB['head']['id'])
  check(sectionA['tail']['id'] != sectionSecond['head']['id'])
  check(not any(p['nodes'][-1]['label'] in ['PART-MAN-B', 'TOOL-MAN-A'] for p in paths(client, 'ALARM-MAN-A')))
  approve(client, body(manualA, 'manual_section', '相同段落', 'part', 'PART-MAN-A'))
  check(any(p['nodes'][-1]['label'] == 'PART-MAN-A' for p in paths(client, 'ALARM-MAN-A')))

  # 舊資料以原本無作用域 ID 建立；來源 hash 仍正確也不得恢復有效。
  legacyIds = []
  with store.Session() as db:
    for index, candidate in enumerate([body(caseA, 'alarm', 'E-A', 'case', '相同案例標題'),
      body(caseB, 'case', '相同案例標題', 'spare', 'SPARE-B', 'requires_spare'),
      body(manualA, 'alarm', 'ALARM-MAN-A', 'manual_section', '相同段落'),
      body(caseA, 'case', '相同案例標題', 'symptom', 'E-A')]):
      ids = []
      for node in [candidate['head'], candidate['tail']]:
        nodeId = 'GN-' + graph.maintenance_ai.digest([MODEL, node['kind'], node['label']])
        if not db.get(GraphNode, nodeId):
          db.add(GraphNode(id=nodeId, kind=node['kind'], label=node['label'], machineModel=MODEL))
          db.flush()
        ids.append(nodeId)
      source = sources[candidate['sourceChunkId']]
      relationId = 'GR-' + graph.maintenance_ai.digest([candidate, sourceHash(source)])
      legacyIds.append(relationId)
      db.add(GraphRelation(id=relationId, headId=ids[0], tailId=ids[1], kind=candidate['relation'],
        machineModel=MODEL, status='approved', revision=1, payload=json.dumps({
          'sourceChunkId': source['chunkId'], 'sourceHash': sourceHash(source), 'history': [],
          'citation': {'sourceId': source['sourceId'], 'quote': candidate['quote'], 'version': source['version']}})))
    db.commit()
  current = client.get('/api/graph/candidates').json()
  for relationId in legacyIds:
    relation = next(r for r in current if r['id'] == relationId)
    check(relation['sourceValid'] and not relation['effective'] and not relation['identityValid'])
    response = client.post('/api/graph/relations/' + relationId + '/review',
      json={'revision': 1, 'action': 'approve', 'note': '不得核准歧義舊資料'})
    check(response.status_code == 409)
  check(not any(p['nodes'][-1]['label'] == 'SPARE-B' for p in paths(client, 'E-A')))
  duplicate = client.post('/api/graph/candidates', json=body(caseA, 'alarm', 'E-A', 'case', '相同案例標題')).json()
  check(duplicate['id'] == alarmA['id'] and duplicate['id'] not in legacyIds)
  rebuilt = client.post('/api/graph/rebuild').json()
  check(rebuilt['created'] > 0)
  rebuiltRows = client.get('/api/graph/candidates').json()
  replacement = next(r for r in rebuiltRows if r['head']['kind'] == 'case' and
    r['tail']['kind'] == 'symptom' and r['tail']['label'] == 'E-A' and r['identityValid'])
  check(replacement['id'] not in legacyIds and replacement['status'] == 'candidate' and not replacement['effective'])
  check(client.post('/api/graph/rebuild').json()['created'] == 0)
  check(client.post('/api/graph/relations/' + legacyIds[0] + '/review',
    json={'revision': 1, 'action': 'withdraw', 'note': '保留歧義舊關係的撤回紀錄'}).status_code == 200)
  check(client.post('/api/graph/candidates', json=body(manualA, 'case', '相同案例標題', 'part', 'PART-MAN-A')).status_code == 422)
  check(client.post('/api/graph/candidates', json=body(caseA, 'manual_section', caseA['section'], 'alarm', 'E-A')).status_code == 422)
  with store.Session() as db:
    db.get(store.RepairCase, 'CASE-B').status = 'withdrawn'
    db.commit()
  check(not paths(client, 'E-B'))
  check(bool(paths(client, 'E-A')))
  engineer = client.post('/api/auth/demo', json={'role': 'engineer'}).json()
  client.headers['X-CSRF-Token'] = engineer['csrf']
  check(client.get('/api/graph/candidates').status_code == 403)
  check(not any(p['nodes'][-1]['label'] == 'SPARE-B' for p in paths(client, 'E-A')))
  print(json.dumps({'passed': passed}))
