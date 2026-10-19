"""來源實體不能只以顯示名稱合併；概念節點仍維持機型內共用。"""
from fastapi import HTTPException
from .maintenance_ai import digest
from .graph_models import GraphNode


def entityScope(node, source=None):
  if node.kind == 'case':
    if not source or source['sourceType'] != 'reviewed_repair_case' or node.label != source['title']:
      raise HTTPException(422, '案例節點必須使用目前案例來源及其正式標題')
    return {'sourceId': source['sourceId'], 'entityType': 'case'}
  if node.kind == 'manual_section':
    excluded = {'reviewed_repair_case', 'equipment_template', 'stock_catalog', 'qualification_catalog'}
    if not source or source['sourceType'] in excluded or not source.get('section') or node.label != source['section']:
      raise HTTPException(422, '手冊段落節點必須使用目前手冊來源的段落標題')
    return {'sourceId': source['sourceId'], 'chunkId': source['chunkId'], 'entityType': 'manual_section'}
  return None


def nodeIdentity(node, model, scope=None):
  key = [model, node.kind, node.label]
  if scope:
    key += ['source-entities-v1', scope]
  return 'GN-' + digest(key)


def relationIdentityValid(row, data, source, db):
  for side, nodeId in [('head', row.headId), ('tail', row.tailId)]:
    node = db.get(GraphNode, nodeId)
    if not node:
      return False
    if node.kind not in {'case', 'manual_section'}:
      continue
    try:
      scope = entityScope(node, source)
    except HTTPException:
      return False
    # 舊無作用域關係不能由名稱猜回來源，必須重建候選並重新核對。
    if data.get('nodeScopes', {}).get(side) != scope or nodeId != nodeIdentity(node, row.machineModel, scope):
      return False
  return True
