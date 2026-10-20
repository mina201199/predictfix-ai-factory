import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


def test_independent_evaluation_validates_original_training_and_new_plan():
  from run_selection_independent_eval import validateInputs
  plan, trained, manifest = validateInputs()
  assert plan['rows'] == 100 and trained['optimizer_steps_actual'] == 504
  assert manifest['version'] == 'gemma-sft-v4-coverage'
  assert manifest['holdout_ids'] == []


@pytest.mark.parametrize('field,value', [('adapter_sha256', 'wrong'), ('rows', 99),
  ('max_new_tokens', 65), ('decoding', 'sampling'), ('dataset', 'training/selection-dataset-v2.json')])
def test_independent_evaluation_refuses_any_changed_frozen_plan(field, value):
  from run_selection_independent_eval import validateInputs, readJson, PLAN
  broken = copy.deepcopy(readJson(PLAN))
  broken[field] = value
  with pytest.raises(ValueError, match='frozen plan'):
    validateInputs(broken)


def test_evaluation_manifest_is_separate_and_uses_only_new_holdout():
  from run_selection_independent_eval import validateInputs, evaluationManifest, readJson, ROOT
  plan, _, trainedManifest = validateInputs()
  before = copy.deepcopy(trainedManifest)
  data = readJson(ROOT / plan['dataset'])
  manifest = evaluationManifest(trainedManifest, data)
  assert trainedManifest == before
  assert manifest['evaluation_splits'] == ['holdout']
  assert manifest['holdout_ids'] == [r['id'] for r in data['splits']['holdout']]
  assert manifest['train_ids'] == before['train_ids']


def test_model_prompt_excludes_gold_and_metadata():
  from run_selection_independent_eval import readJson, ROOT
  from prepare_lora_data import prompt
  row = readJson(ROOT / 'training/selection-holdout-v5-independent.json')['splits']['holdout'][0]
  serialized = prompt(row)
  for key in ['label_rationale', 'selected', 'source_group', 'paragraph_roles', 'equipment_theme']:
    if key != 'selected':
      assert f'"{key}"' not in serialized
  assert '"selected"' not in serialized.split('輸入：', 1)[1]
