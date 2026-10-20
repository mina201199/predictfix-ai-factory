"""Gemma 固定 SFT 實驗；只讀官方快取，輸出僅寫入新的實驗資料夾。"""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import random
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from gemma_sft_protocol import (MODEL_ID, MODEL_REVISION, buildManifest, fileHash,
  grammarAnswers, groupedMetrics, nextTokens, scoreOutput, summarizeRows, textHash,
  validateManifest, verifyReload)
from prepare_lora_data import prompt

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'training/selection-dataset-v2.json'
HOLDOUT = ROOT / 'training/selection-holdout-v3.json'
PROTOCOL = ROOT / 'training/gemma-sft-protocol-v1.json'
CHECKPOINT_SHA = '2db5482b20d746879bb3ef79b5203e9075a2e2b98f54ec7c2f281c1477ddc550'


def writeJson(path, value):
  path = Path(path)
  temporary = path.with_name(path.name + '.tmp')
  content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
  temporary.write_text(content, encoding='utf-8')
  # 外層預算可終止本程序，因此完整寫入後才取代上一份可讀報告。
  os.replace(temporary, path)


def readJson(path):
  return json.loads(Path(path).read_text(encoding='utf-8'))


def canonicalAnswer(row):
  return json.dumps({'selected': [p['id'] for p in row['paragraphs'] if p['id'] in row['selected']]}, separators=(',', ':'))


def encodeExample(tokenizer, row, cap):
  messages = [{'role': 'user', 'content': prompt(row)}]
  promptIds = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_dict=True)['input_ids']
  fullIds = tokenizer.apply_chat_template(messages + [{'role': 'assistant', 'content': canonicalAnswer(row)}], tokenize=True, return_dict=True)['input_ids']
  if fullIds[:len(promptIds)] != promptIds:
    raise ValueError(f'Chat template prefix mismatch: {row["id"]}')
  if len(fullIds) > cap:
    raise ValueError(f'Sequence exceeds cap without truncation: {row["id"]}: {len(fullIds)}')
  return fullIds, [-100] * len(promptIds) + fullIds[len(promptIds):]


def resolveRows(manifest, split):
  source = readJson(HOLDOUT)['splits']['holdout'] if split == 'holdout' else readJson(DATASET)['splits'][split]
  index = {r['id']: r for r in source}
  return [index[rowId] for rowId in manifest[f'{split}_ids']]


def loadModel(args, report, adapter=None):
  import torch
  from transformers import AutoConfig, AutoTokenizer, Gemma4ForCausalLM
  from check_qlora_feasibility import placeDecoder
  snapshot = Path(args.runtime_dir).resolve() / 'hf-cache/models--google--gemma-4-E2B-it/snapshots' / MODEL_REVISION
  weights = snapshot / 'model.safetensors'
  if not weights.is_file():
    raise FileNotFoundError(f'Offline weights not found: {weights}')
  report['checkpoint_sha256'] = fileHash(weights)
  if report['checkpoint_sha256'] != CHECKPOINT_SHA:
    raise ValueError('Official checkpoint SHA256 mismatch')
  config = AutoConfig.from_pretrained(snapshot, local_files_only=True)
  tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
  model, loading = Gemma4ForCausalLM.from_pretrained(snapshot, config=config.text_config,
    dtype=torch.bfloat16, key_mapping={r'^model\.language_model\.': 'model.'},
    local_files_only=True, output_loading_info=True)
  report['checkpoint_loading'] = {'missing_keys': sorted(loading.get('missing_keys', [])),
    'mismatched_keys': sorted(loading.get('mismatched_keys', []), key=str),
    'unexpected_key_count': len(loading.get('unexpected_keys', []))}
  if report['checkpoint_loading']['missing_keys'] or report['checkpoint_loading']['mismatched_keys']:
    raise ValueError('Pretrained text weights incomplete')
  model.requires_grad_(False)
  torch.cuda.init()
  torch.cuda.reset_peak_memory_stats()
  report['placement'] = {}
  placeDecoder(model, args.mode, 'cuda', report['placement'])
  if adapter:
    from peft import PeftModel
    wrapped = PeftModel.from_pretrained(model, adapter, is_trainable=True)
    report['adapter_parameters'] = sum(p.numel() for p in model.parameters() if p.requires_grad)
    # wrapper 不能被提早回收；底層手動 forward 與第一波相同，保留其 adapter 模組。
    return model, tokenizer, wrapped
  return model, tokenizer, None


def resources():
  import psutil
  import torch
  from check_qlora_feasibility import gpuSnapshot, nvidiaSmi
  memory = psutil.Process().memory_info()
  device = nvidiaSmi()
  if device:
    device['device_used_mib'] = device.pop('used_by_others_mib')
  return {'cpu_rss_mib': round(memory.rss / 2**20, 2),
    'cpu_peak_working_set_mib': round(getattr(memory, 'peak_wset', memory.rss) / 2**20, 2),
    'torch_cuda': gpuSnapshot(torch) if torch.cuda.is_initialized() else None,
    'nvidia_smi_whole_device': device}


def forwardText(model, ids, past=None, cache=True):
  import torch
  text = model.model
  ids = torch.tensor([ids], dtype=torch.long)
  dtype = text.norm.weight.dtype
  device = text.norm.weight.device
  embeds = text.embed_tokens(ids).to(device, dtype)
  perLayer = text.get_per_layer_inputs(ids, None).to(device, dtype)
  return text(inputs_embeds=embeds, per_layer_inputs=perLayer, use_cache=cache, past_key_values=past)


def generateConstrained(model, tokenizer, row, maxTokens):
  import torch
  import torch.nn.functional as functional
  model.eval()
  promptIds = tokenizer.apply_chat_template([{'role': 'user', 'content': prompt(row)}],
    tokenize=True, add_generation_prompt=True, return_dict=True)['input_ids']
  choices = [tokenizer.encode(answer, add_special_tokens=False) for answer in grammarAnswers(row)]
  prefix = []
  pending = list(promptIds)
  past = None
  firstBranch = None
  with torch.inference_mode():
    for _ in range(maxTokens):
      allowed = sorted(nextTokens(choices, prefix))
      if not allowed:
        raise RuntimeError('Grammar exhausted before terminal')
      if len(allowed) == 1:
        token = allowed[0]
      else:
        output = forwardText(model, pending, past, True)
        past = output.past_key_values
        pending = []
        hidden = output.last_hidden_state[:, -1].to('cpu', model.lm_head.weight.dtype)
        # grammar 之外的 token 都被遮罩，只算允許的詞彙列與完整 logits 後遮罩的 argmax 相同。
        weights = model.lm_head.weight[allowed]
        logits = functional.linear(hidden, weights).float()[0]
        softcap = model.config.final_logit_softcapping
        if softcap:
          logits = torch.tanh(logits / softcap) * softcap
        if not torch.isfinite(logits).all():
          raise RuntimeError('Nonfinite generation logits')
        if firstBranch is None:
          firstBranch = {'token_ids': allowed, 'logits': logits.tolist()}
        token = allowed[int(logits.argmax())]
      prefix.append(token)
      pending.append(token)
      if prefix in choices:
        raw = tokenizer.decode(prefix, skip_special_tokens=False)
        if raw not in grammarAnswers(row):
          raise RuntimeError('Tokenizer round trip violates grammar')
        return {'raw': raw, 'prompt_tokens': len(promptIds), 'generated_tokens': len(prefix),
          'first_branch': firstBranch}
  raise RuntimeError('Generation token budget exceeded')


def adapterEvidence(model, tokenizer, row, adapterDir, manifest):
  evidence = generateConstrained(model, tokenizer, row, manifest['max_new_tokens'])
  return {'adapter_hash': fileHash(Path(adapterDir) / 'adapter_model.safetensors'),
    'adapter_config_hash': fileHash(Path(adapterDir) / 'adapter_config.json'),
    'trainable_parameters': sum(p.numel() for p in model.parameters() if p.requires_grad),
    'probe_id': row['id'], 'probe_output': evidence['raw'],
    'probe_token_ids': evidence['first_branch']['token_ids'],
    'probe_logits': evidence['first_branch']['logits']}


def initializeAdapter(model, seed):
  import torch
  generator = torch.Generator(device='cpu').manual_seed(seed)
  digest = hashlib.sha256()
  with torch.no_grad():
    for name, parameter in sorted(model.named_parameters()):
      if not parameter.requires_grad:
        continue
      # 先用相同 CPU fp32 抽樣再複製，排除 base dtype 與 nf4 建層消耗 RNG 的差異。
      values = torch.empty(parameter.shape, dtype=torch.float32)
      if '.lora_A.' in name:
        torch.nn.init.kaiming_uniform_(values, a=math.sqrt(5), generator=generator)
      elif '.lora_B.' in name:
        values.zero_()
      else:
        raise ValueError(f'Unexpected trainable parameter: {name}')
      parameter.data = values.to(parameter.device)
      digest.update(name.encode('utf-8'))
      digest.update(values.numpy().tobytes())
  torch.manual_seed(seed)
  return digest.hexdigest()


def evaluate(model, tokenizer, manifest, args, report, save):
  results = []
  for split in ['validation', 'holdout']:
    for row in resolveRows(manifest, split):
      if args.max_seconds and time.monotonic() - args.started > args.max_seconds:
        raise TimeoutError('Budget expired between evaluation rows')
      generated = generateConstrained(model, tokenizer, row, manifest['max_new_tokens'])
      result = {**scoreOutput(generated['raw'], row), 'split': split,
        'prompt_tokens': generated['prompt_tokens'], 'generated_tokens': generated['generated_tokens']}
      results.append(result)
      report['results'] = results
      report['metrics_by_split'] = {s: summarizeRows([r for r in results if r['split'] == s]) for s in ['validation', 'holdout']}
      report['metrics_by_kind'] = groupedMetrics(results, 'kind')
      report['metrics_by_family'] = groupedMetrics(results, 'family')
      save()
      print(json.dumps({'evaluated': len(results), 'id': row['id'], 'split': split}, ensure_ascii=False), flush=True)


def train(model, tokenizer, manifest, args, report, save, probe=False):
  import torch
  import torch.nn.functional as functional
  from check_qlora_feasibility import addLora
  torch.manual_seed(manifest['seed'])
  wrapped, lora = addLora(model, manifest['rank'])
  report['lora'] = lora
  report['initial_adapter_sha256'] = initializeAdapter(model, manifest['seed'])
  rows = resolveRows(manifest, 'train')
  # 所有訓練列先檢查長度，不能先跑一半後才悄悄略過超長題目。
  examples = [(row['id'], *encodeExample(tokenizer, row, manifest['sequence_cap'])) for row in rows]
  trainable = [p for p in model.parameters() if p.requires_grad]
  optimizer = torch.optim.AdamW(trainable, lr=manifest['learning_rate'], weight_decay=manifest['weight_decay'])
  records = []
  report['steps'] = records
  report['train_sequence_tokens'] = 0
  report['supervised_tokens'] = 0
  model.train()
  for rowId, ids, labelValues in examples[:2] if probe else examples:
    if args.max_seconds and time.monotonic() - args.started > args.max_seconds:
      raise TimeoutError('Budget expired between optimizer steps')
    stepStart = time.monotonic()
    optimizer.zero_grad(set_to_none=True)
    labels = torch.tensor(labelValues, dtype=torch.long)
    output = forwardText(model, ids, cache=False)
    targets = labels[1:]
    positions = (targets != -100).nonzero().squeeze(1)
    decisionCount = None
    if manifest.get('objective', {}).get('name') == 'grammar-decision-balanced-v1':
      from selection_decisions import decisionPlan, decisionLoss
      row = next(row for row in rows if row['id'] == rowId)
      answer = tokenizer.encode(canonicalAnswer(row), add_special_tokens=False)
      choices = [tokenizer.encode(value, add_special_tokens=False) for value in grammarAnswers(row)]
      plan = decisionPlan(choices, answer)
      promptLength = sum(value == -100 for value in labelValues)
      loss = decisionLoss(model, output.last_hidden_state, promptLength, plan)
      decisionCount = len(plan)
    else:
      hidden = output.last_hidden_state[0, positions.to('cuda')].to('cpu', model.lm_head.weight.dtype)
      logits = model.lm_head(hidden).float()
      softcap = model.config.final_logit_softcapping
      if softcap:
        logits = torch.tanh(logits / softcap) * softcap
      loss = functional.cross_entropy(logits, targets[positions])
    if not torch.isfinite(loss):
      raise RuntimeError('Nonfinite training loss')
    loss.backward()
    gradNorm = torch.nn.utils.clip_grad_norm_(trainable, manifest['grad_clip'], error_if_nonfinite=True)
    optimizer.step()
    torch.cuda.synchronize()
    record = {'step': len(records) + 1, 'id': rowId, 'loss': float(loss.detach()),
      'grad_norm': float(gradNorm), 'sequence_tokens': len(ids),
      'supervised_tokens': decisionCount if decisionCount is not None else len(positions),
      'wall_seconds_uncontrolled': time.monotonic() - stepStart, 'resources': resources()}
    records.append(record)
    report['optimizer_steps_actual'] = len(records)
    report['train_sequence_tokens'] += len(ids)
    report['supervised_tokens'] += record['supervised_tokens']
    save()
    print(json.dumps({'step': record['step'], 'loss': record['loss'], 'wall_seconds_uncontrolled': record['wall_seconds_uncontrolled']}), flush=True)
    # 只保存已完成 optimizer 更新的獨立 checkpoint，不覆寫先前 adapter。
    if not probe and (len(records) % 18 == 0 or len(records) == len(examples)):
      checkpoint = args.run_dir / f'checkpoint-{len(records):04d}'
      wrapped.save_pretrained(checkpoint, safe_serialization=True)
      report.setdefault('checkpoint_dirs', []).append(str(checkpoint))
      save()
    del output, loss
    if decisionCount is None:
      del hidden, logits
  if probe:
    return wrapped
  if len(records) != manifest['optimizer_steps']:
    raise RuntimeError('Incomplete fixed step budget')
  adapterDir = args.run_dir / 'adapter'
  wrapped.save_pretrained(adapterDir, safe_serialization=True)
  report['adapter_dir'] = str(adapterDir)
  report['before_reload'] = adapterEvidence(model, tokenizer, rows[0], adapterDir, manifest)
  writeJson(args.run_dir / 'before-reload.json', report['before_reload'])
  save()
  return wrapped


def checkBaseline(path, mode, manifestHash):
  baseline = readJson(path)
  if baseline.get('command') != 'baseline' or baseline.get('mode') != mode or baseline.get('status') != 'completed' or baseline.get('protocol_sha256') != manifestHash:
    raise ValueError('A completed matching original-model baseline is required before SFT')
  if baseline.get('adapter_source') is not None:
    raise ValueError('Original-model baseline cannot contain an adapter')
  if len(baseline.get('results', [])) != 128:
    raise ValueError('Baseline must include all fixed validation and holdout rows')
  expected = [(rowId, split) for split in ['validation', 'holdout'] for rowId in baseline['protocol'][f'{split}_ids']]
  actual = [(row['id'], row['split']) for row in baseline['results']]
  if actual != expected:
    raise ValueError('Baseline rows differ from the complete frozen evaluation order')


def validateCommandArgs(args):
  if args.adapter_run and args.command != 'reload':
    raise ValueError('--adapter-run is allowed only for reload')
  if args.baseline_report and args.command != 'train':
    raise ValueError('--baseline-report is allowed only for train')
  if args.verify_only and args.command != 'reload':
    raise ValueError('--verify-only is allowed only for reload')
  if args.max_seconds < 0 or args.cpu_threads < 1:
    raise ValueError('Invalid time budget or CPU thread count')


def run(args):
  validateCommandArgs(args)
  args.started = time.monotonic()
  args.run_dir = args.run_dir.resolve()
  args.run_dir.mkdir(parents=True, exist_ok=False)
  os.environ['HF_HUB_OFFLINE'] = '1'
  os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
  manifest = readJson(PROTOCOL)
  validateManifest(manifest, DATASET, HOLDOUT)
  report = {'status': 'started', 'command': args.command, 'mode': args.mode,
    'started_at': datetime.now(timezone.utc).isoformat(),
    'model_id': MODEL_ID, 'revision': MODEL_REVISION, 'protocol_sha256': textHash(PROTOCOL),
    'dataset_sha256': textHash(DATASET), 'holdout_sha256': textHash(HOLDOUT),
    'protocol': manifest, 'python': sys.version, 'platform': platform.platform(),
    'source_sha256': {name: textHash(ROOT / 'scripts' / name) for name in
      ['run_gemma_sft.py', 'gemma_sft_protocol.py', 'selection_decisions.py', 'check_qlora_feasibility.py', 'prepare_lora_data.py']},
    'adapter_source': str(args.adapter_run) if args.adapter_run else None,
    'clock_context': 'Uncontrolled concurrent workloads; wall time is budget evidence, not performance comparison.'}
  reportPath = args.run_dir / 'report.json'
  def save():
    report['wall_seconds_uncontrolled'] = time.monotonic() - args.started
    writeJson(reportPath, report)
  save()
  try:
    import torch
    from check_qlora_feasibility import nvidiaSmi
    report['nvidia_smi_before_cuda_init'] = nvidiaSmi()
    report['packages'] = {name: importlib.metadata.version(name) for name in
      ['torch', 'transformers', 'peft', 'bitsandbytes', 'accelerate', 'psutil', 'safetensors']}
    random.seed(manifest['seed'])
    torch.manual_seed(manifest['seed'])
    torch.set_num_threads(args.cpu_threads)
    report['cpu_threads'] = args.cpu_threads
    torch.backends.cuda.matmul.allow_tf32 = False
    report['seed'] = manifest['seed']
    if args.command == 'train':
      if not args.baseline_report:
        raise ValueError('--baseline-report required for fixed SFT')
      checkBaseline(args.baseline_report, args.mode, report['protocol_sha256'])
    if args.command == 'reload' and not args.adapter_run:
      raise ValueError('--adapter-run required')
    adapterDir = args.adapter_run.resolve() / 'adapter' if args.adapter_run else None
    if adapterDir:
      trained = readJson(args.adapter_run / 'report.json')
      if trained['status'] != 'trained_pending_reload' or trained['mode'] != args.mode or trained['protocol_sha256'] != report['protocol_sha256']:
        raise ValueError('Adapter source is incomplete or does not match protocol/mode')
    model, tokenizer, wrapped = loadModel(args, report, adapterDir)
    report['resources_after_load'] = resources()
    save()
    if args.command == 'probe':
      timings = []
      for row in resolveRows(manifest, 'train')[:2]:
        started = time.monotonic()
        generated = generateConstrained(model, tokenizer, row, manifest['max_new_tokens'])
        timings.append({'id': row['id'], 'wall_seconds_uncontrolled': time.monotonic() - started,
          'prompt_tokens': generated['prompt_tokens'], 'generated_tokens': generated['generated_tokens']})
        print(json.dumps(timings[-1]), flush=True)
      report['inference_cost_probe'] = timings
      save()
      wrapped = train(model, tokenizer, manifest, args, report, save, probe=True)
      report['status'] = 'cost_probe_only'
    elif args.command == 'baseline':
      evaluate(model, tokenizer, manifest, args, report, save)
      report['status'] = 'completed'
    elif args.command == 'train':
      wrapped = train(model, tokenizer, manifest, args, report, save)
      report['status'] = 'trained_pending_reload'
    elif args.command == 'reload':
      before = readJson(args.adapter_run / 'before-reload.json')
      after = adapterEvidence(model, tokenizer, resolveRows(manifest, 'train')[0], adapterDir, manifest)
      if before['adapter_config_hash'] != after['adapter_config_hash'] or before['probe_token_ids'] != after['probe_token_ids']:
        raise ValueError('Reload config hash or branch token ids mismatch')
      report['reload_verification'] = verifyReload(before, after, manifest['reload_atol'], manifest['reload_rtol'])
      report['before_reload'] = before
      report['after_reload'] = after
      save()
      if not args.verify_only:
        evaluate(model, tokenizer, manifest, args, report, save)
      report['status'] = 'reload_verified' if args.verify_only else 'completed'
    report['resources_final'] = resources()
  except (Exception, KeyboardInterrupt) as error:
    report['status'] = 'interrupted' if isinstance(error, KeyboardInterrupt) else 'timed_out' if isinstance(error, TimeoutError) else 'failed'
    report['error'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
    try:
      report['resources_at_failure'] = resources()
    except Exception:
      pass
    save()
    raise
  save()
  print(json.dumps({'report': str(reportPath), 'status': report['status']}, ensure_ascii=False), flush=True)


def main():
  global PROTOCOL, HOLDOUT
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('command', choices=['freeze', 'probe', 'baseline', 'train', 'reload'])
  parser.add_argument('--mode', choices=['fp16', 'qlora'], default='qlora')
  parser.add_argument('--runtime-dir', type=Path, help='Read-only shared .runtime containing hf-cache')
  parser.add_argument('--run-dir', type=Path, help='New output folder in this worktree')
  parser.add_argument('--baseline-report', type=Path)
  parser.add_argument('--adapter-run', type=Path)
  parser.add_argument('--verify-only', action='store_true')
  parser.add_argument('--max-seconds', type=float, default=0, help='Cooperative budget checked between rows/steps')
  parser.add_argument('--cpu-threads', type=int, default=6)
  parser.add_argument('--protocol', type=Path)
  parser.add_argument('--holdout', type=Path)
  parser.add_argument('--decision-objective', action='store_true', help='Freeze v2 decision-balanced objective')
  args = parser.parse_args()
  for argument, name in [(args.protocol, 'protocol'), (args.holdout, 'holdout')]:
    if argument and not argument.resolve().is_relative_to(ROOT / 'training'):
      parser.error(f'--{name} must be inside this worktree training folder')
  if args.protocol:
    PROTOCOL = args.protocol.resolve()
  if args.holdout:
    HOLDOUT = args.holdout.resolve()
  if args.decision_objective and args.command != 'freeze':
    parser.error('--decision-objective is only valid when freezing the protocol')
  if args.command == 'freeze':
    with PROTOCOL.open('x', encoding='utf-8', newline='\n') as handle:
      json.dump(buildManifest(DATASET, HOLDOUT, decisionObjective=args.decision_objective), handle, ensure_ascii=False, indent=2)
      handle.write('\n')
    print(PROTOCOL)
  else:
    if not args.runtime_dir or not args.run_dir:
      parser.error('--runtime-dir and --run-dir required')
    if not args.run_dir.resolve().is_relative_to(ROOT / '.runtime'):
      parser.error('--run-dir must be a new folder inside this worktree .runtime')
    run(args)


if __name__ == '__main__':
  main()
