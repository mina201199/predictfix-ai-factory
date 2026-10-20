import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def test_independent_holdout_is_reproducible_disjoint_and_balanced():
  from build_selection_independent_holdout import buildIndependentHoldout, auditHoldout
  data = buildIndependentHoldout()
  assert data == buildIndependentHoldout()
  report = auditHoldout(data)
  assert report['passed']
  rows = data['splits']['holdout']
  assert len(rows) == 100 and len({r['source_group'] for r in rows}) == 10
  assert Counter(len(r['selected']) for r in rows) == {0: 30, 1: 30, 2: 20, 3: 20}
  assert sum(r['kind'] == 'document_injection' for r in rows) == 20
  frozen = ROOT / 'training/selection-holdout-v5-independent.json'
  assert json.loads(frozen.read_text(encoding='utf-8')) == data


def test_holdout_audit_rejects_distractor_gold_and_stale_revision():
  from build_selection_independent_holdout import buildIndependentHoldout, auditHoldout
  data = buildIndependentHoldout()
  row = data['splits']['holdout'][0]
  row['selected'] = [next(k for k, v in row['paragraph_roles'].items() if v == 'obsolete')]
  with pytest.raises(ValueError, match='gold'):
    auditHoldout(data)


def test_holdout_audit_rejects_old_question_leakage():
  from build_selection_independent_holdout import buildIndependentHoldout, auditHoldout
  data = buildIndependentHoldout()
  old = json.loads((ROOT / 'training/selection-dataset-v2.json').read_text(encoding='utf-8'))
  data['splits']['holdout'][0]['question'] = old['splits']['train'][0]['question']
  with pytest.raises(ValueError, match='overlap'):
    auditHoldout(data)
