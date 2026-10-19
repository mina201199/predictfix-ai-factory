"""有來源且需人工核准的唯讀擴展；不產生維修診斷或工單動作。"""
import json
import re
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Literal
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from . import auth, maintenance_ai, store
from .graph_models import GraphNode, GraphRelation
from .graph_sources import currentSources, sourceHash, structuredCandidates

NodeKind = Literal['machine_model', 'part', 'alarm', 'symptom', 'fault', 'cause',
  'inspect_step', 'verify_step', 'manual_section', 'case', 'spare', 'qualification']
RelationKind = Literal['has_part', 'references', 'possible_cause', 'inspect', 'verify',
  'requires_spare', 'requires_qualification']
LIMITS = {'maxHops': 3, 'maxResults': 50, 'maxExpansions': 1000, 'maxEdges': 5000, 'maxRowsScanned': 20000}
NOTICE = '路徑只表示來源中經人工核對的關係，不代表診斷正確或原廠認證；不得自動派工、結案或核准復機。'


def now():
  return datetime.now(timezone.utc).isoformat()


class Input(BaseModel):
  model_config = ConfigDict(extra='forbid')


class NodeInput(Input):
  kind: NodeKind
  label: str = Field(min_length=1, max_length=500)

  @field_validator('label')
  @classmethod
  def clean(cls, value):
    if not value.strip():
      raise ValueError('節點不可空白')
    return value.strip()


class CandidateInput(Input):
  sourceChunkId: str = Field(min_length=1, max_length=200)
  machineModel: str = Field(min_length=1, max_length=100)
  head: NodeInput
  tail: NodeInput
  relation: RelationKind
  quote: str = Field(min_length=2, max_length=60000)

  @model_validator(mode='after')
  def typedRelation(self):
    targetKinds = {'has_part': {'part'}, 'possible_cause': {'cause'},
      'inspect': {'inspect_step'}, 'verify': {'verify_step'},
      'requires_spare': {'spare'}, 'requires_qualification': {'qualification'}}
    if self.relation in targetKinds and self.tail.kind not in targetKinds[self.relation]:
      raise ValueError('關係與目標型別不符')
    if self.relation == 'has_part' and self.head.kind != 'machine_model':
      raise ValueError('零件適用性必須來自機型')
    if self.head == self.tail:
      raise ValueError('不接受自我關係')
    return self


class ReviewInput(Input):
  revision: int = Field(ge=1)
  action: Literal['approve', 'withdraw']
  note: str = Field(min_length=3, max_length=1000)

  @field_validator('note')
  @classmethod
  def clean(cls, value):
    if len(value.strip()) < 3:
      raise ValueError('需填寫核對註記')
    return value.strip()


class QueryInput(Input):
  machineModel: str = Field(min_length=1, max_length=100)
  query: str = Field(min_length=1, max_length=500)
  maxHops: int = Field(default=3, ge=1, le=3)
  limit: int = Field(default=20, ge=1, le=50)
  relations: list[RelationKind] = Field(default_factory=lambda: [
    'has_part', 'references', 'possible_cause', 'inspect', 'verify', 'requires_spare', 'requires_qualification'], max_length=7)

  @field_validator('machineModel', 'query')
  @classmethod
  def clean(cls, value):
    if not value.strip():
      raise ValueError('請確認機型與起點文字')
    return value.strip()


class AssistInput(QueryInput):
  useGraph: bool = True


def nodeDict(node):
  result = {'id': node.id, 'kind': node.kind, 'label': node.label}
  if node.kind == 'spare':
    result['catalogUrl'] = '/api/stock'
  if node.kind == 'qualification':
    result['catalogUrl'] = '/workflow.html'
  return result


def relationDict(row, sources, db):
  data = json.loads(row.payload)
  source = sources.get(data['sourceChunkId'])
  valid = bool(source and sourceHash(source) == data['sourceHash'])
  return {'id': row.id, 'head': nodeDict(db.get(GraphNode, row.headId)),
    'tail': nodeDict(db.get(GraphNode, row.tailId)), 'relation': row.kind,
    'machineModel': row.machineModel, 'status': row.status, 'revision': row.revision,
    'createdAt': row.createdAt.isoformat(), **data, 'sourceValid': valid,
    'effective': valid and row.status == 'approved'}


def ensureNode(db, node, model):
  nodeId = 'GN-' + maintenance_ai.digest([model, node.kind, node.label])
  if not db.get(GraphNode, nodeId):
    db.add(GraphNode(id=nodeId, kind=node.kind, label=node.label, machineModel=model))
    db.flush()
  return nodeId


def createCandidate(db, body, actor, sources=None):
  sources = currentSources() if sources is None else sources
  source = sources.get(body.sourceChunkId)
  if not source:
    raise HTTPException(409, '來源已失效或不在可用範圍')
  if body.machineModel not in source['machineModels'] or body.quote not in source['text']:
    raise HTTPException(422, '適用機型或逐字引文不符')
  for node in [body.head, body.tail]:
    metadataMatch = (node.kind == 'machine_model' and node.label == body.machineModel) or (
      node.kind == 'case' and source['sourceType'] == 'reviewed_repair_case' and node.label == source['title'])
    if not metadataMatch and node.label not in body.quote:
      raise HTTPException(422, '節點文字必須逐字出現在引文')
  fingerprint = sourceHash(source)
  relationId = 'GR-' + maintenance_ai.digest([body.model_dump(), fingerprint])
  existing = db.get(GraphRelation, relationId)
  if existing:
    return existing, False
  headId = ensureNode(db, body.head, body.machineModel)
  tailId = ensureNode(db, body.tail, body.machineModel)
  data = {'sourceChunkId': body.sourceChunkId, 'sourceHash': fingerprint,
    'createdBy': actor, 'approvedBy': None, 'approvedAt': None,
    'reviewedBy': None, 'reviewedAt': None, 'reviewNote': '', 'history': [],
    'citation': {'sourceId': source['sourceId'], 'chunkId': source['chunkId'],
      'version': source['version'], 'section': source['section'], 'quote': body.quote,
      'url': source['url'], 'isSynthetic': source['isSynthetic'],
      'lineStart': source.get('lineStart'), 'lineEnd': source.get('lineEnd')}}
  row = GraphRelation(id=relationId, headId=headId, tailId=tailId, kind=body.relation,
    machineModel=body.machineModel, status='candidate', revision=1,
    payload=json.dumps(data, ensure_ascii=False))
  db.add(row)
  db.flush()
  maintenance_ai.record(db, 'graph_candidate', {'username': actor}, {'id': row.id})
  return row, True


def reviewRelation(db, relationId, body, actor):
  row = db.get(GraphRelation, relationId)
  if not row:
    raise HTTPException(404, '關係不存在')
  if row.revision != body.revision:
    raise HTTPException(409, '關係版本已變更，請重新載入')
  data = json.loads(row.payload)
  sources = currentSources()
  source = sources.get(data['sourceChunkId'])
  if body.action == 'approve' and (not source or sourceHash(source) != data['sourceHash']):
    raise HTTPException(409, '來源已撤回或改版，請重新建立候選')
  timestamp = now()
  data.update(reviewedBy=actor, reviewedAt=timestamp, reviewNote=body.note)
  if body.action == 'approve':
    data.update(approvedBy=actor, approvedAt=timestamp)
  data['history'].append({'action': body.action, 'actor': actor, 'at': timestamp, 'note': body.note})
  result = db.execute(update(GraphRelation).where(GraphRelation.id == relationId,
    GraphRelation.revision == body.revision).values(revision=body.revision + 1,
      status='approved' if body.action == 'approve' else 'withdrawn',
      payload=json.dumps(data, ensure_ascii=False)))
  if result.rowcount != 1:
    raise HTTPException(409, '關係版本已變更，請重新載入')
  maintenance_ai.record(db, 'graph_review', {'username': actor},
    {'id': relationId, 'action': body.action, 'revision': body.revision + 1})
  db.flush()
  db.expire_all()
  return relationDict(db.get(GraphRelation, relationId), sources, db)


def queryGraph(db, body, sources=None):
  sources = currentSources() if sources is None else sources
  rows = db.scalars(select(GraphRelation).where(GraphRelation.status == 'approved',
    GraphRelation.machineModel == body.machineModel, GraphRelation.kind.in_(body.relations))
    .order_by(GraphRelation.id).limit(LIMITS['maxRowsScanned'] + 1)).yield_per(200)
  truncated, effectiveCount = False, 0
  adjacency, nodes = defaultdict(list), {}
  for scanned, row in enumerate(rows, start=1):
    if scanned > LIMITS['maxRowsScanned']:
      truncated = True
      break
    data = json.loads(row.payload)
    source = sources.get(data['sourceChunkId'])
    if not source or sourceHash(source) != data['sourceHash']:
      continue
    effectiveCount += 1
    if effectiveCount > LIMITS['maxEdges']:
      truncated = True
      break
    relation = relationDict(row, sources, db)
    adjacency[row.headId].append(relation)
    nodes[row.headId], nodes[row.tailId] = relation['head'], relation['tail']
  needle = body.query.casefold()
  # 只接受原文字詞命中；不以警報號相似或語意猜測另一個機型。
  def matches(node):
    label = node['label'].casefold()
    if node['kind'] == 'alarm':
      return bool(re.search(r'(?<![a-z0-9_-])' + re.escape(label) + r'(?![a-z0-9_-])', needle))
    return label in needle or needle in label
  starts = [node for node in nodes.values() if matches(node)]
  queue = deque(([node], []) for node in starts)
  paths, expansions, seen = [], 0, set()
  while queue:
    pathNodes, pathRelations = queue.popleft()
    if len(pathRelations) >= body.maxHops:
      continue
    for relation in adjacency[pathNodes[-1]['id']]:
      expansions += 1
      if expansions > LIMITS['maxExpansions']:
        truncated = True
        queue.clear()
        break
      if relation['tail']['id'] in {node['id'] for node in pathNodes}:
        continue
      nextRelations = pathRelations + [relation]
      signature = tuple(r['id'] for r in nextRelations)
      if signature in seen:
        continue
      seen.add(signature)
      nextNodes = pathNodes + [relation['tail']]
      if len(paths) >= body.limit:
        truncated = True
        queue.clear()
        break
      paths.append({'nodes': nextNodes, 'relations': nextRelations})
      queue.append((nextNodes, nextRelations))
  return {'paths': paths, 'machineModel': body.machineModel, 'truncated': truncated,
    'limits': LIMITS, 'unknown': ['此查詢未判定根因、備品相容性或復機條件；仍須逐項核對來源。'] if paths else [
      '結果因掃描或路徑上限截斷，無法據此判斷沒有來源；請縮小範圍或整理失效關係。' if truncated else
      '沒有符合機型且已核准的有效出向路徑；請補來源或明確警報／零件名稱。'],
    'notice': NOTICE, 'automaticActions': []}


def assistGraph(db, body):
  sources = currentSources()
  # 原搜尋器保留；另傳即時來源，避免圖譜入口使用到已失效的檢索快取。
  chunks = [{'id': s['sourceId'], 'chunk_id': s['chunkId'], 'title': s['title'],
    'text': s['text'], 'machine_models': s['machineModels'], 'is_synthetic': s['isSynthetic'],
    'source_url': s['url'], 'version': s['version'], 'section': s['section']}
    for s in sources.values() if s['sourceType'] not in ['stock_catalog', 'qualification_catalog']]
  baseline = maintenance_ai.search(body.query, chunks=chunks, machine_model=body.machineModel, limit=5)
  result = queryGraph(db, body, sources) if body.useGraph else {
    'paths': [], 'unknown': ['純字詞檢索，不提供關係推論。'], 'notice': NOTICE, 'automaticActions': []}
  result.update(retrieval=baseline, mode='keyword_plus_graph' if body.useGraph else 'keyword', llmUsed=False)
  return result


def register(app):
  @app.get('/api/graph/sources')
  def sources(request: Request):
    auth.supervisor(request)
    return list(currentSources().values())

  @app.get('/api/graph/candidates')
  def candidates(request: Request):
    auth.supervisor(request)
    current = currentSources()
    with store.Session() as db:
      rows = db.scalars(select(GraphRelation).order_by(GraphRelation.createdAt.desc()).limit(500)).all()
      return [relationDict(row, current, db) for row in rows]

  @app.post('/api/graph/candidates')
  def candidate(body: CandidateInput, request: Request):
    auth.supervisor(request)
    with store.Session() as db:
      try:
        row, created = createCandidate(db, body, request.state.user['username'])
        db.commit()
      except IntegrityError:
        db.rollback()
        raise HTTPException(409, '候選已由另一請求建立，請重新載入')
      return relationDict(row, currentSources(), db)

  @app.post('/api/graph/rebuild')
  def rebuild(request: Request):
    auth.supervisor(request)
    current = currentSources()
    created = 0
    with store.Session() as db:
      try:
        for source in current.values():
          if source['sourceType'] in ['stock_catalog', 'qualification_catalog']:
            kind = 'spare' if source['sourceType'] == 'stock_catalog' else 'qualification'
            ensureNode(db, NodeInput(kind=kind, label=source['title']), '')
          for data in structuredCandidates(source):
            row, added = createCandidate(db, CandidateInput(**data), request.state.user['username'], current)
            created += int(added)
        db.commit()
      except IntegrityError:
        db.rollback()
        raise HTTPException(409, '重建與另一請求衝突，請重試')
    return {'created': created, 'status': 'candidate', 'notice': '規則轉換只建立候選，須逐筆核對發布。'}

  @app.post('/api/graph/relations/{relationId}/review')
  def review(relationId: str, body: ReviewInput, request: Request):
    auth.supervisor(request)
    with store.Session() as db:
      result = reviewRelation(db, relationId, body, request.state.user['username'])
      db.commit()
      return result

  @app.post('/api/graph/query')
  def query(body: QueryInput):
    with store.Session() as db:
      return queryGraph(db, body)

  @app.post('/api/graph/assist')
  def assist(body: AssistInput):
    with store.Session() as db:
      return assistGraph(db, body)
