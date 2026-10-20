import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


@pytest.fixture
def syntheticTrainingInputs(tmp_path, monkeypatch):
  import run_selection_independent_eval as evaluation
  sourceRoot = evaluation.ROOT
  plan = copy.deepcopy(evaluation.readJson(evaluation.PLAN))
  shutil.copytree(sourceRoot / 'training', tmp_path / 'training')
  (tmp_path / 'scripts').mkdir()
  sourceName = 'run_gemma_sft.py'
  shutil.copyfile(sourceRoot / 'scripts' / sourceName, tmp_path / 'scripts' / sourceName)
  adapter = tmp_path / plan['candidate_adapter_dir']
  adapter.mkdir(parents=True)
  weights = adapter / 'adapter_model.safetensors'
  config = adapter / 'adapter_config.json'
  weights.write_bytes(b'synthetic adapter fixture; not a trained model')
  config.write_text('{}', encoding='utf-8')
  plan['adapter_sha256'] = evaluation.fileHash(weights)
  plan['adapter_config_sha256'] = evaluation.fileHash(config)
  protocol = tmp_path / plan['training_protocol']
  manifest = evaluation.readJson(protocol)
  trained = {'status': 'trained_pending_reload', 'mode': 'qlora',
    'protocol_sha256': evaluation.textHash(protocol), 'protocol': manifest,
    'optimizer_steps_actual': 504, 'steps': [{'id': rowId} for rowId in manifest['train_ids']],
    'source_sha256': {sourceName: evaluation.textHash(tmp_path / 'scripts' / sourceName)},
    **{field: plan[field] for field in ['model_id', 'revision', 'checkpoint_sha256']}}
  (adapter.parent / 'report.json').write_text(json.dumps(trained), encoding='utf-8')
  planPath = tmp_path / 'evaluation-plan.json'
  planPath.write_text(json.dumps(plan), encoding='utf-8')
  # 測試使用獨立產物，保留正式驗證流程的檔案與雜湊檢查。
  monkeypatch.setattr(evaluation, 'ROOT', tmp_path)
  monkeypatch.setattr(evaluation, 'PLAN', planPath)
  monkeypatch.setattr(evaluation, 'PLAN_SHA', evaluation.textHash(planPath))
  return adapter


def test_independent_evaluation_validates_original_training_and_new_plan(syntheticTrainingInputs):
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


def test_evaluation_manifest_is_separate_and_uses_only_new_holdout(syntheticTrainingInputs):
  from run_selection_independent_eval import validateInputs, evaluationManifest, readJson, ROOT
  plan, _, trainedManifest = validateInputs()
  before = copy.deepcopy(trainedManifest)
  data = readJson(ROOT / plan['dataset'])
  manifest = evaluationManifest(trainedManifest, data)
  assert trainedManifest == before
  assert manifest['evaluation_splits'] == ['holdout']
  assert manifest['holdout_ids'] == [r['id'] for r in data['splits']['holdout']]
  assert manifest['train_ids'] == before['train_ids']


def test_independent_evaluation_requires_training_report(syntheticTrainingInputs):
  from run_selection_independent_eval import validateInputs
  (syntheticTrainingInputs.parent / 'report.json').unlink()
  with pytest.raises(FileNotFoundError):
    validateInputs()


def test_independent_evaluation_rejects_corrupted_adapter(syntheticTrainingInputs):
  from run_selection_independent_eval import validateInputs
  (syntheticTrainingInputs / 'adapter_model.safetensors').write_bytes(b'corrupt')
  with pytest.raises(ValueError, match='Adapter weights hash mismatch'):
    validateInputs()


def test_model_prompt_excludes_gold_and_metadata():
  from run_selection_independent_eval import readJson, ROOT
  from prepare_lora_data import prompt
  row = readJson(ROOT / 'training/selection-holdout-v5-independent.json')['splits']['holdout'][0]
  serialized = prompt(row)
  for key in ['label_rationale', 'selected', 'source_group', 'paragraph_roles', 'equipment_theme']:
    if key != 'selected':
      assert f'"{key}"' not in serialized
  assert '"selected"' not in serialized.split('輸入：', 1)[1]
