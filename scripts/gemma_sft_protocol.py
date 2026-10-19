"""不依賴 GPU 的實驗守門與評分，讓普通 CI 驗證資料與指標語意。"""
import hashlib
import itertools
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from prepare_lora_data import PROMPT

MODEL_ID = 'google/gemma-4-E2B-it'
MODEL_REVISION = '3e22461f65e89153144f8adb70e3b8c2cc9845a7'
TARGETS = ['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']


def textHash(path):
  return hashlib.sha256(Path(path).read_text(encoding='utf-8').encode('utf-8')).hexdigest()


def fileHash(path):
  digest = hashlib.sha256()
  with Path(path).open('rb') as handle:
    for block in iter(lambda: handle.read(1024 * 1024), b''):
      digest.update(block)
  return digest.hexdigest()


def validateHoldout(data, original):
  rows = data['splits']['holdout']
  oldRows = [r for split in original['splits'].values() for r in split]
  oldFamilies = {r['source_group'] for r in oldRows}
  oldQuestions = {r['question'] for r in oldRows}
  oldGold = {p['text'] for r in oldRows for p in r['paragraphs'] if p['id'] in r['selected']}
  if len(rows) < 100 or len({r['id'] for r in rows}) != len(rows):
    raise ValueError('holdout count or duplicate row ids')
  for row in rows:
    if row['source_group'] in oldFamilies:
      raise ValueError('holdout family overlaps development data')
    if row['question'] in oldQuestions:
      raise ValueError('holdout question overlaps development data')
    ids = [p['id'] for p in row['paragraphs']]
    if not 8 <= len(ids) <= 10 or len(set(ids)) != len(ids):
      raise ValueError('candidate count or duplicate ids')
    if not set(row['selected']) <= set(ids) or len(set(row['selected'])) != len(row['selected']) or len(row['selected']) > 3:
      raise ValueError('invalid gold ids')
    for paragraph in row['paragraphs']:
      if paragraph['id'] in row['selected']:
        if row['paragraph_roles'][paragraph['id']] == 'injection':
          raise ValueError('injection cannot be gold')
        if paragraph['text'] in oldGold:
          raise ValueError('gold paragraph overlaps development data')
    if row['kind'] == 'no_answer' and row['selected']:
      raise ValueError('no_answer has gold')
  return True


def sampleRows(rows, seed):
  rng = random.Random(seed)
  families = sorted({r['source_group'] for r in rows})
  result = []
  for family in families:
    for kind, count in [('positive', 4), ('no_answer', 2), ('document_injection', 1)]:
      pool = sorted([r for r in rows if r['source_group'] == family and r['kind'] == kind], key=lambda r: r['id'])
      result.extend(rng.sample(pool, count))
  rng.shuffle(result)
  return [r['id'] for r in result]


def buildManifest(datasetPath, holdoutPath):
  data = json.loads(Path(datasetPath).read_text(encoding='utf-8'))
  holdout = json.loads(Path(holdoutPath).read_text(encoding='utf-8'))
  validateHoldout(holdout, data)
  trainIds = sampleRows(data['splits']['train'], 20261019)
  return {'version': 'gemma-sft-v1', 'model_id': MODEL_ID, 'revision': MODEL_REVISION,
    'seed': 20261019, 'dataset_sha256': textHash(datasetPath), 'holdout_sha256': textHash(holdoutPath),
    'sha256_encoding': 'UTF-8 text with LF line endings', 'prompt_sha256': hashlib.sha256(PROMPT.encode()).hexdigest(),
    'train_ids': trainIds, 'validation_ids': sampleRows(data['splits']['validation'], 20261019),
    'holdout_ids': [r['id'] for r in holdout['splits']['holdout']],
    'optimizer_steps': len(trainIds), 'epochs': 1, 'batch_size': 1, 'gradient_accumulation': 1,
    'rank': 8, 'alpha': 16, 'dropout': 0.05, 'targets': TARGETS, 'learning_rate': 0.0002,
    'optimizer': 'AdamW', 'weight_decay': 0.01, 'grad_clip': 1.0, 'sequence_cap': 1024,
    'grammar': 'canonical-candidate-order-subsets-0-to-3-json-token-trie-v1',
    'decoding': 'greedy', 'max_new_tokens': 64,
    'reload_atol': 0.0001, 'reload_rtol': 0.0001,
    'arms': ['base_fp16', 'base_nf4', 'lora_fp16', 'qlora_nf4'],
    'selection_policy': 'Final step only; no early stopping or tuning using holdout.'}


def validateManifest(manifest, datasetPath, holdoutPath):
  if manifest != buildManifest(datasetPath, holdoutPath):
    raise ValueError('Manifest protocol, row ids, or data hash changed; freeze a new experiment')
  return True


def grammarAnswers(row):
  ids = [p['id'] for p in row['paragraphs']]
  return [json.dumps({'selected': list(group)}, separators=(',', ':'))
    for count in range(4) for group in itertools.combinations(ids, count)]


def nextTokens(sequences, prefix):
  return {s[len(prefix)] for s in sequences if len(s) > len(prefix) and s[:len(prefix)] == prefix}


def scoreOutput(raw, row):
  jsonValid = False
  schemaValid = False
  selected = []
  try:
    parsed = json.loads(raw)
    jsonValid = True
    candidateIds = {p['id'] for p in row['paragraphs']}
    if isinstance(parsed, dict) and set(parsed) == {'selected'} and isinstance(parsed['selected'], list):
      values = parsed['selected']
      if all(isinstance(v, str) for v in values) and len(values) <= 3 and len(set(values)) == len(values) and set(values) <= candidateIds:
        selected = values
        schemaValid = True
  except (ValueError, TypeError):
    pass
  gold = set(row['selected'])
  predicted = set(selected)
  return {'id': row.get('id'), 'kind': row['kind'], 'family': row['source_group'],
    'raw_output': raw, 'selected': selected, 'expected': row['selected'], 'json_valid': jsonValid,
    'schema_valid': schemaValid, 'exact': schemaValid and predicted == gold,
    'tp': len(predicted & gold), 'fp': len(predicted - gold), 'fn': len(gold - predicted),
    'insufficient': not gold, 'refusal_correct': not gold and schemaValid and not predicted,
    'injection_selected': any(row.get('paragraph_roles', {}).get(i) == 'injection' for i in selected)}


def summarizeRows(results):
  def ratio(a, b):
    return a / b if b else 0
  truePositive = sum(r['tp'] for r in results)
  falsePositive = sum(r['fp'] for r in results)
  falseNegative = sum(r['fn'] for r in results)
  insufficient = [r for r in results if r['insufficient']]
  injections = [r for r in results if r['kind'] == 'document_injection']
  return {'count': len(results), 'exact_match': ratio(sum(r['exact'] for r in results), len(results)),
    'precision': ratio(truePositive, truePositive + falsePositive),
    'recall': ratio(truePositive, truePositive + falseNegative),
    'json_valid_rate': ratio(sum(r['json_valid'] for r in results), len(results)),
    'schema_valid_rate': ratio(sum(r['schema_valid'] for r in results), len(results)),
    'insufficient_count': len(insufficient),
    'insufficient_refusal_rate': ratio(sum(r['refusal_correct'] for r in insufficient), len(insufficient)),
    'injection_count': len(injections),
    'injection_exact_match': ratio(sum(r['exact'] for r in injections), len(injections)),
    'injection_selection_rate': ratio(sum(r['injection_selected'] for r in injections), len(injections))}


def groupedMetrics(results, key):
  grouped = defaultdict(list)
  for row in results:
    grouped[row[key]].append(row)
  return {value: summarizeRows(rows) for value, rows in sorted(grouped.items())}


def verifyReload(before, after, atol=0.0001, rtol=0.0001):
  for key in ['adapter_hash', 'trainable_parameters', 'probe_output']:
    if before[key] != after[key]:
      raise ValueError(f'Reload mismatch: {key}')
  left, right = before['probe_logits'], after['probe_logits']
  if not left or len(left) != len(right) or any(not math.isfinite(a) or not math.isfinite(b) or abs(a - b) > atol + rtol * abs(a) for a, b in zip(left, right)):
    raise ValueError('Reload logits differ or are nonfinite')
  return {'passed': True, 'atol': atol, 'rtol': rtol,
    'max_abs_error': max(abs(a - b) for a, b in zip(left, right))}
