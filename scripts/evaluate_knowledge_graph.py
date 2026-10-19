"""重跑固定合成圖譜評估；只使用新建的隔離 SQLite，不連線模型。"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def seedSnapshot(client, snapshot):
  from backend import store, maintenance_ai
  from backend.knowledge_graph import CandidateInput, createCandidate, ReviewInput, reviewRelation
  sources = {}
  for manual in snapshot['manuals']:
    doc = {'id': manual['id'], 'title': '合成測試 ' + manual['section'], 'version': '1',
      'machine_models': [manual['model']], 'component': '', 'source_type': 'synthetic_graph_fixture',
      'content': '## ' + manual['section'] + '\n' + manual['text'], 'is_synthetic': True}
    with store.Session() as db:
      db.add(store.KnowledgeDocument(id=manual['id'], active=1, payload=json.dumps(doc, ensure_ascii=False)))
      db.commit()
    sources[manual['id']] = next(c for c in maintenance_ai.buildCorpus() if c['id'] == manual['id'])
  for relation in snapshot['relations']:
    source = sources[relation['source']]
    body = CandidateInput(sourceChunkId=source['chunk_id'], machineModel=source['machine_models'][0],
      head={'kind': relation['headKind'], 'label': relation['head']},
      tail={'kind': relation['tailKind'], 'label': relation['tail']},
      relation=relation['relation'], quote=source['text'])
    with store.Session() as db:
      row, _ = createCandidate(db, body, 'supervisor')
      reviewRelation(db, row.id, ReviewInput(revision=1, action='approve', note='合成金標明示關係'), 'supervisor')
      db.commit()
  case = snapshot['draftCase']
  fields = {'title': case['title'], 'machine_model': case['model'], 'component': '合成零件',
    'symptoms': case['symptom'], 'conditions': '合成條件', 'findings': '合成發現',
    'cause_status': 'unknown', 'root_cause': '未知', 'actions': case['action'],
    'verification': '合成復測', 'is_synthetic': True}
  with store.Session() as db:
    db.add(store.RepairCase(id=case['id'], ticket_id='WO-KG-SYNTH', status='published', revision=1,
      payload=json.dumps({'fields': fields, 'source_sha256': 'synthetic-fixture',
        'published_by': 'supervisor', 'published_at': '2026-10-19T00:00:00Z'})))
    db.commit()
  for entity in snapshot.get('entityCases', []):
    entityFields = {'title': entity['title'], 'machine_model': entity['model'], 'component': '合成零件',
      'symptoms': entity['alarm'], 'conditions': '合成條件', 'findings': '合成發現',
      'cause_status': 'unknown', 'root_cause': '未知', 'actions': entity['action'],
      'verification': '合成復測', 'is_synthetic': True}
    with store.Session() as db:
      db.add(store.RepairCase(id=entity['id'], ticket_id='WO-' + entity['id'], status='published', revision=1,
        payload=json.dumps({'fields': entityFields, 'source_sha256': 'synthetic-entity-fixture',
          'published_by': 'supervisor', 'published_at': '2026-10-19T00:00:00Z'})))
      db.commit()
    entitySource = next(c for c in maintenance_ai.buildCorpus() if c['id'] == entity['id'])
    entityCandidates = [CandidateInput(sourceChunkId=entitySource['chunk_id'], machineModel=entity['model'],
      head={'kind': 'alarm', 'label': entity['alarm']}, tail={'kind': 'case', 'label': entity['title']},
      relation='references', quote=entitySource['text'])]
    if entity.get('spare'):
      entityCandidates.append(CandidateInput(sourceChunkId=entitySource['chunk_id'], machineModel=entity['model'],
        head={'kind': 'case', 'label': entity['title']}, tail={'kind': 'spare', 'label': entity['spare']},
        relation='requires_spare', quote=entitySource['text']))
    with store.Session() as db:
      for candidate in entityCandidates:
        createCandidate(db, candidate, 'supervisor')
      db.commit()
  client.post('/api/graph/rebuild').raise_for_status()
  from backend.graph_models import GraphRelation
  from sqlalchemy import select
  with store.Session() as db:
    for row in db.scalars(select(GraphRelation).where(GraphRelation.status == 'candidate')).all():
      reviewRelation(db, row.id, ReviewInput(revision=row.revision, action='approve', note='合成固定案例核對'), 'supervisor')
    for manual in snapshot['manuals']:
      if manual.get('state') == 'withdrawn':
        db.get(store.KnowledgeDocument, manual['id']).active = 0
    db.get(store.RepairCase, case['id']).status = 'draft'
    db.commit()


def evaluate(client, questions):
  from backend.graph_sources import currentSources, sourceHash
  activeSources = currentSources()
  rows = []
  for question in questions:
    if question['category'] == 'authorization':
      from fastapi.testclient import TestClient
      from backend.app import app
      with TestClient(app) as other:
        if question['role'] == 'engineer':
          login = other.post('/api/auth/demo', json={'role': 'engineer'}).json()
          other.headers['X-CSRF-Token'] = login['csrf']
        response = other.post(question['endpoint'], json=question['body']) if 'body' in question else other.get(question['endpoint'])
        rows.append({'id': question['id'], 'category': question['category'], 'expectedStatus': question['status'],
          'actualStatus': response.status_code, 'passed': response.status_code == question['status']})
      continue
    row = {'id': question['id'], 'category': question['category'], 'gold': question, 'modes': {}}
    for mode in ['keyword', 'keyword_plus_graph']:
      response = client.post('/api/graph/assist', json={'machineModel': question['model'],
        'query': question['query'], 'useGraph': mode != 'keyword', 'limit': 50})
      response.raise_for_status()
      result = response.json()
      found = list(dict.fromkeys(item['id'] for item in result['retrieval']))
      if mode != 'keyword':
        found = list(dict.fromkeys(found + [edge['citation']['sourceId']
          for path in result['paths'] for edge in path['relations']]))
      relevant = set(question['relevant'])
      matched = len(set(found) & relevant)
      precision = matched / len(found) if found else 1.0
      recall = matched / len(relevant) if relevant else None
      answerable = bool(question['required']) and set(question['required']).issubset(found)
      pathTargets = [path['nodes'][-1]['label'] for path in result['paths']]
      row['modes'][mode] = {'retrieved': found, 'precision': precision, 'recall': recall,
        'answerableFromSources': answerable, 'answerabilityCorrect': answerable == question['answerable'],
        'allSourcesRelevant': set(found).issubset(relevant), 'pathTargets': pathTargets,
        'pathTargetFound': question.get('target') in pathTargets if 'target' in question else None,
        'directionCorrect': not result['paths'] if question.get('noPath') else None,
        'forbiddenTargetsAbsent': not set(question.get('forbiddenTargets', [])) & set(pathTargets),
        'noAutomaticActions': result['automaticActions'] == [], 'llmUsed': result['llmUsed'],
        'sourceValidityCorrect': all(item['chunk_id'] in activeSources and
          question['model'] in activeSources[item['chunk_id']]['machineModels'] and
          str(item['version']) == activeSources[item['chunk_id']]['version'] and
          item['text'] == activeSources[item['chunk_id']]['text'] for item in result['retrieval']) and
          all(edge['sourceChunkId'] in activeSources and
            question['model'] in activeSources[edge['sourceChunkId']]['machineModels'] and
            edge['sourceHash'] == sourceHash(activeSources[edge['sourceChunkId']]) and
            edge['citation']['version'] == activeSources[edge['sourceChunkId']]['version'] and
            edge['citation']['quote'] in activeSources[edge['sourceChunkId']]['text']
            for path in result['paths'] for edge in path['relations']),
        'unknown': result['unknown'], 'paths': result['paths']}
    rows.append(row)
  summary = {}
  normal = [row for row in rows if 'modes' in row]
  for mode in ['keyword', 'keyword_plus_graph']:
    values = [row['modes'][mode] for row in normal]
    recalls = [value['recall'] for value in values if value['recall'] is not None]
    positives = [row['modes'][mode] for row in normal if row['gold']['answerable']]
    summary[mode] = {'macroPrecision': sum(v['precision'] for v in values) / len(values),
      'macroRecallOnRelevantQuestions': sum(recalls) / len(recalls),
      'answerableRateOnPositiveQuestions': sum(v['answerableFromSources'] for v in positives) / len(positives),
      'answerabilityAccuracy': sum(v['answerabilityCorrect'] for v in values) / len(values),
      'allSourcesRelevantRate': sum(v['allSourcesRelevant'] for v in values) / len(values)}
  return {'summary': summary, 'questions': rows,
    'evaluatedSourceIds': sorted({source['sourceId'] for source in activeSources.values()}),
    'authorizationPassed': all(row['passed'] for row in rows if 'passed' in row)}


def qualityFailures(report):
  failures = []
  if not report['authorizationPassed']:
    failures.append('authorization')
  for row in report['questions']:
    for mode, value in row.get('modes', {}).items():
      for key in ['noAutomaticActions', 'sourceValidityCorrect', 'forbiddenTargetsAbsent']:
        if not value[key]:
          failures.append(row['id'] + ':' + mode + ':' + key)
      if value['llmUsed']:
        failures.append(row['id'] + ':unexpected_llm')
      if mode == 'keyword_plus_graph' and (value['directionCorrect'] is False or value['pathTargetFound'] is False):
        failures.append(row['id'] + ':path_gold_mismatch')
  baseline, graph = report['summary']['keyword'], report['summary']['keyword_plus_graph']
  for metric in ['macroPrecision', 'macroRecallOnRelevantQuestions', 'answerableRateOnPositiveQuestions', 'answerabilityAccuracy']:
    if graph[metric] < baseline[metric]:
      failures.append('regression:' + metric)
  return failures


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--demo-db', type=Path, help='保存合成展示資料庫；路徑必須不存在')
  parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/knowledge-graph-evaluation.json')
  args = parser.parse_args()
  runtime = ROOT / '.runtime'
  runtime.mkdir(exist_ok=True)
  temporary = None
  if args.demo_db:
    database = args.demo_db.resolve()
    if database.exists():
      raise SystemExit('拒絕覆寫既有資料庫，請指定新的 --demo-db 路徑。')
    database.parent.mkdir(parents=True, exist_ok=True)
  else:
    temporary = tempfile.TemporaryDirectory(prefix='knowledge-graph-eval-', dir=runtime)
    database = Path(temporary.name) / 'evaluation.db'
  # 此密碼只用於新建的合成隔離 fixture，不是使用者或正式環境憑證。
  os.environ.update(APP_MODE='demo', DEMO_MODE='1', DATABASE_URL='sqlite:///' + str(database),
    BOOTSTRAP_PASSWORD='Isolated-KG-Synthetic-Fixture-123456', OPENAI_ENABLED='0',
    LOCAL_LLM_MODEL='', OLLAMA_MODEL='', OLLAMA_URL='http://127.0.0.1:9')
  from fastapi.testclient import TestClient
  from backend.app import app
  from backend import knowledge
  fixturePath = ROOT / 'evals/knowledge-graph/snapshot.json'
  questionPath = ROOT / 'evals/knowledge-graph/questions.json'
  snapshot = json.loads(fixturePath.read_text(encoding='utf-8'))
  # 評估語料只取固定快照，避免展示模式日後新增手冊改變 IDF 與排名。
  with patch.object(knowledge, 'CHUNKS', []), patch.object(knowledge, 'manual_documents', []), TestClient(app) as client:
    login = client.post('/api/auth/demo', json={'role': 'supervisor'}).json()
    client.headers['X-CSRF-Token'] = login['csrf']
    seedSnapshot(client, snapshot)
    report = evaluate(client, json.loads(questionPath.read_text(encoding='utf-8')))
  report['qualityFailures'] = qualityFailures(report)
  report['qualityGatePassed'] = not report['qualityFailures']
  report.update(datasetVersion=snapshot['version'], provenance=snapshot['provenance'],
    sourceScope='fixed_snapshot_only',
    sourceSha256=hashlib.sha256(fixturePath.read_bytes()).hexdigest(),
    questionsSha256=hashlib.sha256(questionPath.read_bytes()).hexdigest(),
    database='SQLite', postgresql='not tested', gpuUsed=False,
    metrics='文件 ID 集合；純檢索 top-5，擴展為相同 top-5 加有界有效路徑來源。空結果 precision 定義 1；無相關來源時 recall 不計；非排名指標。可答需取得所有 required 金標來源，不能代表診斷正確。')
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
  print(json.dumps({'output': str(args.output), 'summary': report['summary'],
    'authorizationPassed': report['authorizationPassed'],
    'qualityGatePassed': report['qualityGatePassed'],
    'demoDatabase': str(database) if args.demo_db else None}, ensure_ascii=False))
  if temporary:
    from backend import store
    store.engine.dispose()
    temporary.cleanup()
  if not report['qualityGatePassed']:
    raise SystemExit(1)


if __name__ == '__main__':
  main()
