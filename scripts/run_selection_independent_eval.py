"""獨立測試只評估已凍結模型；原始訓練與新測試來源分開驗證。"""
import argparse
import copy
import hashlib
import os
import random
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import run_gemma_sft as runner
from gemma_sft_protocol import fileHash, textHash, validateManifest, verifyReload
from run_gemma_sft import ROOT, readJson, writeJson
from run_gemma_sft_campaign import runBounded

PLAN = ROOT / 'training/selection-independent-v5-evaluation-plan.json'
PLAN_SHA = '607a3c0ee406847b35f5c2b00db63690fc7a161b8522bda3477d508a5f894a6c'
ARMS = ['base_nf4', 'qlora_nf4_504_final']


def validateInputs(plan=None):
  if textHash(PLAN) != PLAN_SHA:
    raise ValueError('Changed frozen plan file')
  frozen = readJson(PLAN)
  if plan is not None and plan != frozen:
    raise ValueError('Changed frozen plan')
  plan = frozen
  dataset = ROOT / plan['dataset']
  if textHash(dataset) != plan['dataset_sha256_lf']:
    raise ValueError('New test data hash mismatch')
  data = readJson(dataset)
  rows = data['splits']['holdout']
  if len(rows) != plan['rows'] or len({r['id'] for r in rows}) != len(rows):
    raise ValueError('New test rows mismatch')
  protocol = ROOT / plan['training_protocol']
  if textHash(protocol) != plan['training_protocol_sha256']:
    raise ValueError('Original training protocol mismatch')
  manifest = readJson(protocol)
  validateManifest(manifest, runner.DATASET, ROOT / 'training/selection-holdout-v4-repair.json')
  adapter = ROOT / plan['candidate_adapter_dir']
  trained = readJson(adapter.parent / 'report.json')
  if trained['status'] != 'trained_pending_reload' or trained['mode'] != 'qlora':
    raise ValueError('Original training incomplete or wrong mode')
  if trained['protocol_sha256'] != textHash(protocol) or trained['protocol'] != manifest:
    raise ValueError('Adapter training provenance mismatch')
  if trained['optimizer_steps_actual'] != 504 or [r['id'] for r in trained['steps']] != manifest['train_ids']:
    raise ValueError('Adapter training steps mismatch')
  for field in ['model_id', 'revision', 'checkpoint_sha256']:
    if trained[field] != plan[field]:
      raise ValueError(f'Model provenance mismatch: {field}')
  for name, expected in trained['source_sha256'].items():
    if textHash(ROOT / 'scripts' / name) != expected:
      raise ValueError(f'Training source changed: {name}')
  if fileHash(adapter / 'adapter_model.safetensors') != plan['adapter_sha256']:
    raise ValueError('Adapter weights hash mismatch')
  if fileHash(adapter / 'adapter_config.json') != plan['adapter_config_sha256']:
    raise ValueError('Adapter config hash mismatch')
  from prepare_lora_data import PROMPT
  if hashlib.sha256(PROMPT.encode()).hexdigest() != plan['prompt_sha256']:
    raise ValueError('Prompt hash mismatch')
  return plan, trained, manifest


def evaluationManifest(trainingManifest, data):
  manifest = copy.deepcopy(trainingManifest)
  manifest['evaluation_splits'] = ['holdout']
  manifest['holdout_ids'] = [r['id'] for r in data['splits']['holdout']]
  return manifest


def evaluateArm(args):
  started = time.monotonic()
  args.started = started
  plan, trained, trainingManifest = validateInputs()
  args.run_dir.mkdir(parents=True, exist_ok=False)
  report = {'status': 'started', 'arm': args.arm, 'mode': 'qlora', 'command': 'independent_eval',
    'started_at': datetime.now(timezone.utc).isoformat(), 'plan_sha256': textHash(PLAN),
    'dataset_sha256': plan['dataset_sha256_lf'], 'training_protocol_sha256': plan['training_protocol_sha256'],
    'training_performed': False, 'model_id': plan['model_id'], 'revision': plan['revision'],
    'adapter_sha256': plan['adapter_sha256'] if args.arm != 'base_nf4' else None,
    'source_sha256': {**trained['source_sha256'], Path(__file__).name: textHash(__file__)},
    'limitations': plan['limitations'], 'clock_context': 'Uncontrolled concurrent workloads; no latency comparison claim.'}
  def save():
    report['wall_seconds_uncontrolled'] = time.monotonic() - started
    writeJson(args.run_dir / 'report.json', report)
  save()
  try:
    import torch
    random.seed(trainingManifest['seed'])
    torch.manual_seed(trainingManifest['seed'])
    torch.set_num_threads(6)
    torch.backends.cuda.matmul.allow_tf32 = False
    args.mode = 'qlora'
    adapter = ROOT / plan['candidate_adapter_dir'] if args.arm != 'base_nf4' else None
    model, tokenizer, wrapped = runner.loadModel(args, report, adapter)
    model.eval()
    if adapter:
      before = readJson(adapter.parent / 'before-reload.json')
      after = runner.adapterEvidence(model, tokenizer, runner.resolveRows(trainingManifest, 'train')[0], adapter, trainingManifest)
      if before['adapter_config_hash'] != after['adapter_config_hash'] or before['probe_token_ids'] != after['probe_token_ids']:
        raise ValueError('Adapter reload config or probe IDs mismatch')
      report['reload_verification'] = verifyReload(before, after, trainingManifest['reload_atol'], trainingManifest['reload_rtol'])
      report['after_reload'] = after
    # 重載證據包含原始可訓練參數數量，核對後才凍結以進行純推論。
    model.requires_grad_(False)
    runner.HOLDOUT = ROOT / plan['dataset']
    manifest = evaluationManifest(trainingManifest, readJson(runner.HOLDOUT))
    report['evaluation_manifest'] = manifest
    save()
    runner.evaluate(model, tokenizer, manifest, args, report, save)
    report['resources_final'] = runner.resources()
    report['status'] = 'completed'
  except Exception as error:
    report.update(status='failed', error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
    raise
  finally:
    save()


def campaign(args):
  validateInputs()
  started = time.monotonic()
  args.run_dir.mkdir(parents=True, exist_ok=False)
  report = {'status': 'running', 'max_seconds': 1800, 'plan_sha256': textHash(PLAN),
    'user_authorization': 'OK: base and final504 candidate each100; total30min; no retraining', 'stages': {}}
  def save():
    report['wall_seconds_uncontrolled'] = time.monotonic() - started
    writeJson(args.run_dir / 'campaign.json', report)
  save()
  for arm in ARMS:
    remaining = 1800 - (time.monotonic() - started)
    if remaining <= 0:
      report['stages'][arm] = {'status': 'not_run_budget'}
      continue
    command = [sys.executable, str(Path(__file__).resolve()), '--arm', arm,
      '--runtime-dir', str(args.runtime_dir.resolve()), '--run-dir', str(args.run_dir / arm), '--max-seconds', str(remaining)]
    entry = {'status': 'running', 'report': str(args.run_dir / arm / 'report.json')}
    report['stages'][arm] = entry
    save()
    with (args.run_dir / f'{arm}.log').open('w', encoding='utf-8') as log:
      result = runBounded(command, ROOT, dict(os.environ, HF_HUB_OFFLINE='1', PYTHONIOENCODING='utf-8'), log, remaining)
    child = readJson(entry['report']) if Path(entry['report']).exists() else {}
    entry.update(result)
    entry['status'] = 'hard_timed_out' if result['timed_out'] else child.get('status', 'failed_no_report')
    if result['exit_code'] != 0 and entry['status'] == 'completed':
      entry['status'] = 'failed_exit_code'
    save()
    print(f'{arm}: {entry["status"]}', flush=True)
    if entry['status'] != 'completed':
      break
  report['status'] = 'completed' if len(report['stages']) == 2 and all(e['status'] == 'completed' for e in report['stages'].values()) else 'incomplete'
  save()


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--arm', choices=ARMS)
  parser.add_argument('--runtime-dir', type=Path, required=True)
  parser.add_argument('--run-dir', type=Path, required=True)
  parser.add_argument('--max-seconds', type=float, default=1800)
  args = parser.parse_args()
  args.run_dir = args.run_dir.resolve()
  if not args.run_dir.is_relative_to(ROOT / '.runtime') or not 0 < args.max_seconds <= 1800:
    parser.error('New output must be in worktree .runtime; budget must be within1800seconds')
  os.environ['HF_HUB_OFFLINE'] = '1'
  os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
  evaluateArm(args) if args.arm else campaign(args)
