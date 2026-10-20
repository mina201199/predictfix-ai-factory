import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


def test_refusal_decision_has_equal_weight_for_short_and_long_answers():
  from selection_decisions import decisionPlan
  choices = [[1, 2, 3, 9], [1, 2, 4, 5, 6, 9], [1, 2, 4, 8, 7, 9]]
  empty = decisionPlan(choices, choices[0])
  positive = decisionPlan(choices, choices[2])
  assert empty == [{'position': 2, 'allowed': [3, 4], 'targetIndex': 0, 'weight': 1.0}]
  assert positive[0]['weight'] == empty[0]['weight']
  assert positive[0]['targetIndex'] == 1
  assert positive[1] == {'position': 3, 'allowed': [5, 8], 'targetIndex': 1, 'weight': 1.0}
  assert all(len(item['allowed']) > 1 for item in positive)


def test_content_decisions_have_fixed_total_weight_and_gold_must_be_legal():
  from selection_decisions import decisionPlan
  choices = [[1, 2, 3], [1, 2, 4, 5, 6], [1, 2, 4, 8, 6], [1, 2, 4, 8, 7]]
  plan = decisionPlan(choices, choices[-1])
  assert sum(item['weight'] for item in plan[1:]) == 1.0
  assert plan[0]['weight'] == 1.0
  with pytest.raises(ValueError, match='legal'):
    decisionPlan(choices, [1, 2, 999])
  with pytest.raises(ValueError, match='decision'):
    decisionPlan([[1, 2]], [1, 2])


def test_repair_holdout_has_new_families_and_preserves_old_builder():
  import json
  from build_selection_holdout import buildHoldout
  from build_selection_repair_holdout import buildRepairHoldout
  root = Path(__file__).resolve().parents[1]
  previous = buildHoldout()
  fresh = buildRepairHoldout()
  assert buildHoldout() == previous
  assert fresh == buildRepairHoldout()
  assert len(fresh['splits']['holdout']) == 100
  original = json.loads((root / 'training/selection-dataset-v2.json').read_text(encoding='utf-8'))
  oldRows = [r for rows in original['splits'].values() for r in rows] + previous['splits']['holdout']
  for field in ['id', 'source_group', 'question']:
    assert not {r[field] for r in fresh['splits']['holdout']} & {r[field] for r in oldRows}


def test_v2_manifest_freezes_decision_objective_and_rejects_edited_weights():
  import copy
  from gemma_sft_protocol import buildManifest, validateManifest
  root = Path(__file__).resolve().parents[1]
  dataset = root / 'training/selection-dataset-v2.json'
  holdout = root / 'training/selection-holdout-v3.json'
  manifest = buildManifest(dataset, holdout, decisionObjective=True)
  assert manifest['version'] == 'gemma-sft-v2'
  assert manifest['objective']['name'] == 'grammar-decision-balanced-v1'
  assert validateManifest(manifest, dataset, holdout)
  broken = copy.deepcopy(manifest)
  broken['objective']['first_branch_weight'] = 0.01
  with pytest.raises(ValueError, match='Manifest'):
    validateManifest(broken, dataset, holdout)


def test_campaign_forwards_both_frozen_paths_and_rejects_outside_training():
  from types import SimpleNamespace
  from run_gemma_sft_campaign import protocolFlags
  root = Path(__file__).resolve().parents[1]
  args = SimpleNamespace(protocol=root / 'training/gemma-sft-protocol-v2.json',
    holdout=root / 'training/selection-holdout-v4-repair.json')
  assert protocolFlags(args) == ['--protocol', str(args.protocol), '--holdout', str(args.holdout)]
  args.protocol = root / '.runtime/invalid.json'
  with pytest.raises(ValueError, match='training'):
    protocolFlags(args)
