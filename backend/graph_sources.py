"""只轉接現有明確來源；不從鄰接或人員履歷推論因果與機型適用性。"""
import json
from sqlalchemy import select
from . import maintenance_ai as knowledge, store, config


def sourceSnapshot(chunk):
  models = chunk.get('machine_models', [])
  return {'sourceId': chunk['id'], 'chunkId': chunk['chunk_id'],
    'version': str(chunk.get('version', '')), 'section': chunk.get('section', ''),
    'title': chunk.get('title', ''), 'text': chunk['text'],
    'machineModels': models, 'isSynthetic': bool(chunk.get('is_synthetic', True)),
    'sourceType': chunk.get('source_type', 'manual'),
    'url': '/api/cases/' + chunk['id'] if chunk.get('source_type') == 'reviewed_repair_case'
      else '/api/knowledge/manuals/' + chunk['id'],
    'lineStart': chunk.get('line_start'), 'lineEnd': chunk.get('line_end')}


def currentSources():
  # 圖譜必須立即反映內容變更，不能依賴只以 ID／active 作鍵的檢索快取。
  sources = [sourceSnapshot(chunk) for chunk in knowledge.buildCorpus()]
  with store.Session() as db:
    for source in list(sources):
      if source['sourceType'] == 'reviewed_repair_case':
        row = db.get(store.RepairCase, source['sourceId'])
        if not row or row.status != 'published':
          sources.remove(source)
        else:
          # 相同 revision 撤回後重新發布，也必須重新核對圖譜關係。
          source['publicationHash'] = knowledge.digest([row.revision, row.payload])
    for row in db.scalars(select(store.EquipmentTemplate).order_by(store.EquipmentTemplate.id)):
      data = json.loads(row.payload)
      text = data['name'] + '\n' + '\n'.join(data.get('parts', []))
      text += '\n' + '\n'.join(step['label'] + '\n' + step.get('criterion', '') for step in data.get('steps', []))
      sources.append({'sourceId': row.id, 'chunkId': 'template:' + row.id,
        'version': str(row.revision), 'section': '結構化設備模板', 'title': data['name'],
        'text': text, 'machineModels': [row.id],
        'isSynthetic': config.demo(), 'sourceType': 'equipment_template',
        'url': '/api/equipment-templates', 'structured': data})
    for row in db.scalars(select(store.StockItem).order_by(store.StockItem.id)):
      sources.append({'sourceId': row.id, 'chunkId': 'stock:' + row.id, 'version': 'catalog',
        'section': '備品目錄（不代表機型相容）', 'title': row.name,
        'text': row.name, 'machineModels': [], 'isSynthetic': config.demo(),
        'sourceType': 'stock_catalog', 'url': '/api/stock'})
    qualifications = set()
    for row in db.scalars(select(store.EngineerProfile)):
      qualifications.update(json.loads(row.payload).get('qualifications', []))
    for label in sorted(qualifications):
      sources.append({'sourceId': 'qualification:' + knowledge.digest(label),
        'chunkId': 'qualification:' + knowledge.digest(label), 'version': 'catalog',
        'section': '資格目錄（不含個人資料）', 'title': label, 'text': label,
        'machineModels': [], 'isSynthetic': config.demo(), 'sourceType': 'qualification_catalog',
        'url': '/workflow.html'})
  return {source['chunkId']: source for source in sources}


def sourceHash(source):
  return knowledge.digest(source)


def structuredCandidates(source):
  common = {'sourceChunkId': source['chunkId'], 'quote': source['text']}
  if source['sourceType'] == 'equipment_template':
    model = source['machineModels'][0]
    data = source['structured']
    for label in data.get('parts', []):
      yield {**common, 'machineModel': model,
        'head': {'kind': 'machine_model', 'label': model},
        'tail': {'kind': 'part', 'label': label}, 'relation': 'has_part'}
    for step in data.get('steps', []):
      kind = 'inspect' if step['kind'] == 'inspect' else 'verify'
      yield {**common, 'machineModel': model,
        'head': {'kind': 'machine_model', 'label': model},
        'tail': {'kind': kind + '_step', 'label': step['label']}, 'relation': kind}
  if source['sourceType'] == 'reviewed_repair_case':
    model = source['machineModels'][0]
    yield {**common, 'machineModel': model,
      'head': {'kind': 'machine_model', 'label': model},
      'tail': {'kind': 'case', 'label': source['title']}, 'relation': 'references'}
    for prefix, kind, relation in [('症狀：', 'symptom', 'references'),
      ('處置：', 'inspect_step', 'inspect'), ('驗收：', 'verify_step', 'verify')]:
      label = next((line[len(prefix):] for line in source['text'].splitlines() if line.startswith(prefix)), '')
      if label.strip() and len(label) <= 500:
        yield {**common, 'machineModel': model,
          'head': {'kind': 'case', 'label': source['title']},
          'tail': {'kind': kind, 'label': label}, 'relation': relation}
