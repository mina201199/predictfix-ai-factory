import copy
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def test_holdout_is_disjoint_and_reproducible():
  from build_selection_holdout import buildHoldout
  from gemma_sft_protocol import validateHoldout
  original = json.loads((ROOT / 'training/selection-dataset-v2.json').read_text(encoding='utf-8'))
  data = buildHoldout()
  assert data == buildHoldout()
  assert len(data['splits']['holdout']) >= 100
  validateHoldout(data, original)
  broken = copy.deepcopy(data)
  broken['splits']['holdout'][0]['source_group'] = original['splits']['train'][0]['source_group']
  with pytest.raises(ValueError, match='family'):
    validateHoldout(broken, original)


def test_holdout_rejects_injection_gold_and_duplicate_ids():
  from build_selection_holdout import buildHoldout
  from gemma_sft_protocol import validateHoldout
  original = json.loads((ROOT / 'training/selection-dataset-v2.json').read_text(encoding='utf-8'))
  data = buildHoldout()
  row = next(r for r in data['splits']['holdout'] if r['kind'] == 'document_injection')
  row['selected'] = [next(k for k, v in row['paragraph_roles'].items() if v == 'injection')]
  with pytest.raises(ValueError, match='injection'):
    validateHoldout(data, original)
  duplicate = buildHoldout()
  duplicate['splits']['holdout'][0]['paragraphs'][1]['id'] = duplicate['splits']['holdout'][0]['paragraphs'][0]['id']
  with pytest.raises(ValueError, match='duplicate ids'):
    validateHoldout(duplicate, original)


def test_metrics_do_not_reward_invalid_json_empty_gold_or_unknown_ids():
  from gemma_sft_protocol import scoreOutput, summarizeRows
  row = {'selected': [], 'paragraphs': [{'id': 'P1'}], 'kind': 'no_answer', 'source_group': 'f'}
  invalid = scoreOutput('garbage', row)
  assert not invalid['exact'] and not invalid['refusal_correct']
  assert not scoreOutput('{"selected":["P2"]}', row)['schema_valid']
  assert not scoreOutput('{"selected":[],"extra":true}', row)['schema_valid']
  assert scoreOutput('{"selected":[]}', row)['refusal_correct']
  stats = summarizeRows([invalid, scoreOutput('{"selected":[]}', row)])
  assert stats['exact_match'] == 0.5
  assert stats['insufficient_refusal_rate'] == 0.5
  assert stats['precision'] == 0 and stats['recall'] == 0


def test_grammar_allows_only_canonical_zero_to_three_candidate_ids():
  from gemma_sft_protocol import grammarAnswers, nextTokens
  row = {'paragraphs': [{'id': 'P2'}, {'id': 'P1'}, {'id': 'P3'}, {'id': 'P4'}]}
  answers = grammarAnswers(row)
  assert len(answers) == 15
  assert '{"selected":[]}' in answers
  assert '{"selected":["P2","P1"]}' in answers
  assert '{"selected":["P1","P2"]}' not in answers
  assert nextTokens([[1, 2], [1, 3]], [1]) == {2, 3}
  assert nextTokens([[1, 2], [1, 3]], [4]) == set()


def test_manifest_pins_rows_hashes_and_blocks_modified_data(tmp_path):
  from build_selection_holdout import buildHoldout
  from gemma_sft_protocol import buildManifest, validateManifest
  originalPath = ROOT / 'training/selection-dataset-v2.json'
  holdoutPath = tmp_path / 'holdout.json'
  holdoutPath.write_text(json.dumps(buildHoldout(), ensure_ascii=False), encoding='utf-8')
  manifest = buildManifest(originalPath, holdoutPath)
  assert len(manifest['train_ids']) == 126
  assert len(manifest['validation_ids']) == 28
  assert len(manifest['holdout_ids']) == 100
  assert manifest['optimizer_steps'] == 126
  validateManifest(manifest, originalPath, holdoutPath)
  holdoutPath.write_text(holdoutPath.read_text(encoding='utf-8') + ' ', encoding='utf-8')
  with pytest.raises(ValueError, match='hash'):
    validateManifest(manifest, originalPath, holdoutPath)


def test_reload_gate_rejects_different_outputs_hashes_and_nonfinite_logits():
  from gemma_sft_protocol import verifyReload
  evidence = {'adapter_hash': 'abc', 'trainable_parameters': 120,
    'probe_output': '{"selected":[]}', 'probe_logits': [0.1, 0.2]}
  assert verifyReload(evidence, dict(evidence))['passed']
  changed = {**evidence, 'probe_logits': [float('nan'), 0.2]}
  with pytest.raises(ValueError, match='logits'):
    verifyReload(evidence, changed)
  with pytest.raises(ValueError, match='output'):
    verifyReload(evidence, {**evidence, 'probe_output': 'different'})
  with pytest.raises(ValueError, match='hash'):
    verifyReload(evidence, {**evidence, 'adapter_hash': 'other'})


def test_baseline_gate_rejects_duplicates_even_when_count_is_correct(tmp_path):
  from run_gemma_sft import checkBaseline
  from gemma_sft_protocol import buildManifest
  manifest = buildManifest(ROOT / 'training/selection-dataset-v2.json', ROOT / 'training/selection-holdout-v3.json')
  report = {'command': 'baseline', 'mode': 'qlora', 'status': 'completed', 'protocol_sha256': 'pinned',
    'protocol': manifest, 'results': [{'id': 'duplicated', 'split': 'holdout'}] * 128}
  path = tmp_path / 'report.json'
  path.write_text(json.dumps(report), encoding='utf-8')
  with pytest.raises(ValueError, match='rows'):
    checkBaseline(path, 'qlora', 'pinned')


def test_committed_manifest_and_holdout_are_frozen():
  from build_selection_holdout import buildHoldout
  from gemma_sft_protocol import validateManifest
  holdout = ROOT / 'training/selection-holdout-v3.json'
  assert json.loads(holdout.read_text(encoding='utf-8')) == buildHoldout()
  validateManifest(json.loads((ROOT / 'training/gemma-sft-protocol-v1.json').read_text(encoding='utf-8')),
    ROOT / 'training/selection-dataset-v2.json', holdout)


@pytest.mark.parametrize('command', ['baseline', 'probe', 'train'])
def test_adapter_is_never_allowed_in_original_model_or_training_command(command):
  from run_gemma_sft import validateCommandArgs
  args = SimpleNamespace(command=command, adapter_run=Path('adapter'), baseline_report=None,
    verify_only=False, max_seconds=0, cpu_threads=6)
  with pytest.raises(ValueError, match='adapter-run'):
    validateCommandArgs(args)


def test_encode_example_rejects_truncation_and_chat_prefix_drift():
  from run_gemma_sft import encodeExample
  class TemplateFixture:
    def apply_chat_template(self, messages, **kwargs):
      return {'input_ids': [1, 2] if len(messages) == 1 else [1, 2, 3, 4]}
  row = {'id': 'fixture', 'question': 'q', 'paragraphs': [{'id': 'P1', 'text': 'x'}], 'selected': ['P1']}
  assert encodeExample(TemplateFixture(), row, 4) == ([1, 2, 3, 4], [-100, -100, 3, 4])
  with pytest.raises(ValueError, match='cap'):
    encodeExample(TemplateFixture(), row, 3)


def test_campaign_orders_baselines_before_training_and_isolates_failed_arms():
  from run_gemma_sft_campaign import campaignStages, stageReady
  stages = campaignStages('full')
  assert [s['name'] for s in stages[:2]] == ['base_nf4', 'base_fp16']
  assert [s['name'] for s in stages[2:]] == ['qlora_train', 'qlora_reload', 'lora_train', 'lora_reload']
  statuses = {'base_nf4': 'completed', 'base_fp16': 'failed'}
  assert stageReady(stages[2], statuses)
  assert not stageReady(stages[4], statuses)
  assert not stageReady(stages[3], {**statuses, 'qlora_train': 'timed_out'})
  assert stageReady(stages[3], {**statuses, 'qlora_train': 'trained_pending_reload'})


def test_campaign_does_not_parse_partial_reports_from_terminated_processes(tmp_path):
  from run_gemma_sft_campaign import collectQuality
  broken = tmp_path / 'report.json'
  broken.write_text('{"status":', encoding='utf-8')
  assert collectQuality({'base_nf4': {'status': 'hard_timed_out', 'report': str(broken)}}) == {}


def test_failed_atomic_report_replace_preserves_previous_complete_json(tmp_path, monkeypatch):
  import os
  from run_gemma_sft import writeJson
  report = tmp_path / 'report.json'
  report.write_text('{"status":"previous"}', encoding='utf-8')
  def denyReplace(*args):
    raise PermissionError('isolated fixture simulates replace failure')
  monkeypatch.setattr(os, 'replace', denyReplace)
  with pytest.raises(PermissionError):
    writeJson(report, {'status': 'next'})
  assert json.loads(report.read_text(encoding='utf-8')) == {'status': 'previous'}


def test_timeout_stops_owned_grandchild_heartbeat(tmp_path):
  import os
  import subprocess
  import time
  from run_gemma_sft_campaign import runBounded, stopOwnedTree
  heartbeat = tmp_path / 'heartbeat.txt'
  unrelatedHeartbeat = tmp_path / 'unrelated-heartbeat.txt'
  childCode = ('import sys,time\nfrom pathlib import Path\np=Path(sys.argv[1])\n'
    'while True:\n  p.write_text(str(time.monotonic()))\n  time.sleep(0.05)\n')
  parentCode = ('import subprocess,sys,time\n'
    'subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]])\ntime.sleep(60)\n')
  command = [sys.executable, '-c', parentCode, childCode, str(heartbeat)]
  with (tmp_path / 'child.log').open('w', encoding='utf-8') as log:
    unrelated = subprocess.Popen([sys.executable, '-c', childCode, str(unrelatedHeartbeat)],
      stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != 'nt')
    try:
      result = runBounded(command, tmp_path, None, log, 3)
      assert result['timed_out']
      assert heartbeat.exists(), 'Fixture grandchild must actually run before the timeout'
      previous = heartbeat.read_text(encoding='utf-8')
      unrelatedTime = unrelatedHeartbeat.stat().st_mtime_ns
      time.sleep(0.25)
      assert heartbeat.read_text(encoding='utf-8') == previous
      assert unrelatedHeartbeat.stat().st_mtime_ns > unrelatedTime
    finally:
      stopOwnedTree(unrelated)


def test_ownership_rejects_stale_parent_id_from_pid_reuse():
  from gemma_sft_process import isOwnedEdge
  parents = {100: 42, 101: 42, 102: 99}
  created = {42: 1000, 100: 900, 101: 1100, 102: 1200}
  assert not isOwnedEdge(42, 100, parents, created)
  assert isOwnedEdge(42, 101, parents, created)
  assert not isOwnedEdge(42, 102, parents, created)


def test_cleanup_accepts_already_exited_race_but_rejects_live_permission_failure():
  from gemma_sft_process import terminateOwnedHandle
  class KernelFixture:
    def __init__(self, exitedAfterAttempt):
      self.exitedAfterAttempt = exitedAfterAttempt
      self.attempted = False
    def WaitForSingleObject(self, handle, milliseconds):
      return 0 if self.attempted and self.exitedAfterAttempt else 258
    def TerminateProcess(self, handle, exitCode):
      self.attempted = True
      return False
  errorFactory = lambda: PermissionError('isolated kernel fixture')
  terminateOwnedHandle(KernelFixture(True), 123, errorFactory)
  with pytest.raises(PermissionError):
    terminateOwnedHandle(KernelFixture(False), 123, errorFactory)
