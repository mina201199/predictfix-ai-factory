"""序列執行固定實驗並記錄超時；只終止本工具建立的子程序。"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from gemma_sft_protocol import textHash
from run_gemma_sft import PROTOCOL, ROOT, readJson, writeJson


def campaignStages(scope):
  nf4 = {'name': 'base_nf4', 'command': 'baseline', 'mode': 'qlora', 'requires': {}}
  fp16 = {'name': 'base_fp16', 'command': 'baseline', 'mode': 'fp16', 'requires': {}}
  qlora = [
    {'name': 'qlora_train', 'command': 'train', 'mode': 'qlora', 'requires': {'base_nf4': 'completed'}, 'baseline': 'base_nf4'},
    {'name': 'qlora_reload', 'command': 'reload', 'mode': 'qlora', 'requires': {'qlora_train': 'trained_pending_reload'}, 'adapter': 'qlora_train'},
  ]
  lora = [
    {'name': 'lora_train', 'command': 'train', 'mode': 'fp16', 'requires': {'base_fp16': 'completed'}, 'baseline': 'base_fp16'},
    {'name': 'lora_reload', 'command': 'reload', 'mode': 'fp16', 'requires': {'lora_train': 'trained_pending_reload'}, 'adapter': 'lora_train'},
  ]
  return [nf4, fp16, *qlora, *lora] if scope == 'full' else [nf4, *qlora]


def stageReady(stage, statuses):
  return all(statuses.get(name) == status for name, status in stage['requires'].items())


def collectQuality(stages):
  table = {}
  for name, entry in stages.items():
    path = entry.get('report')
    if entry['status'] != 'completed' or not path or not Path(path).exists():
      continue
    child = readJson(path)
    if child.get('command') in ('baseline', 'reload'):
      table[name] = child['metrics_by_split']
  return table


def stopOwnedTree(process):
  if process.poll() is not None:
    return
  if os.name == 'nt':
    from gemma_sft_process import stopWindowsTree
    stopWindowsTree(process.pid, int(process._handle))
  else:
    try:
      os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
      pass
  process.wait(timeout=15)


def runBounded(command, cwd, environment, log, timeoutSeconds):
  process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=log,
    stderr=subprocess.STDOUT, start_new_session=os.name != 'nt')
  try:
    return {'exit_code': process.wait(timeout=timeoutSeconds), 'timed_out': False, 'pid': process.pid}
  except subprocess.TimeoutExpired:
    stopOwnedTree(process)
    return {'exit_code': process.returncode, 'timed_out': True, 'pid': process.pid}
  except BaseException:
    stopOwnedTree(process)
    raise


def campaign(args):
  started = time.monotonic()
  args.run_dir = args.run_dir.resolve()
  if not args.run_dir.is_relative_to(ROOT / '.runtime'):
    raise ValueError('Campaign output must be inside this worktree .runtime')
  args.run_dir.mkdir(parents=True, exist_ok=False)
  report = {'scope': args.scope, 'max_hours': args.max_hours, 'protocol_sha256': textHash(PROTOCOL),
    'status': 'running', 'stages': {}, 'quality_table': {},
    'limitations': ['Concurrent workloads; wall clock is cost evidence, not controlled performance.',
      'Missing/failed arms have no quality score; resource probe is not formal training.']}
  def save():
    report['wall_seconds_uncontrolled'] = time.monotonic() - started
    writeJson(args.run_dir / 'campaign.json', report)
  statuses = {}
  stages = campaignStages(args.scope)
  if args.baseline_nf4:
    from run_gemma_sft import checkBaseline
    checkBaseline(args.baseline_nf4, 'qlora', textHash(PROTOCOL))
    report['stages']['base_nf4'] = {'status': 'completed', 'report': str(args.baseline_nf4.resolve()), 'reused': True}
    statuses['base_nf4'] = 'completed'
  save()
  for stage in stages:
    name = stage['name']
    if name in statuses:
      continue
    remaining = args.max_hours * 3600 - (time.monotonic() - started)
    if remaining <= 0 or not stageReady(stage, statuses):
      statuses[name] = 'not_run_budget' if remaining <= 0 else 'blocked_dependency'
      report['stages'][name] = {'status': statuses[name]}
      save()
      continue
    output = args.run_dir / name
    command = [sys.executable, str(ROOT / 'scripts/run_gemma_sft.py'), stage['command'],
      '--mode', stage['mode'], '--runtime-dir', str(args.runtime_dir.resolve()), '--run-dir', str(output),
      '--max-seconds', str(remaining)]
    if stage.get('baseline'):
      command += ['--baseline-report', report['stages'][stage['baseline']]['report']]
    if stage.get('adapter'):
      command += ['--adapter-run', str(args.run_dir / stage['adapter'])]
    entry = {'status': 'running', 'report': str(output / 'report.json'), 'command': command}
    report['stages'][name] = entry
    save()
    print(json.dumps({'stage': name, 'status': 'running'}), flush=True)
    environment = dict(os.environ, HF_HUB_OFFLINE='1', PYTHONIOENCODING='utf-8')
    try:
      with (args.run_dir / f'{name}.log').open('w', encoding='utf-8') as log:
        result = runBounded(command, ROOT, environment, log, remaining)
      entry['pid'] = result['pid']
      if result['timed_out']:
        entry.update(status='hard_timed_out', reason='Total campaign budget exhausted; owned stage subprocess tree terminated')
      else:
        child = readJson(output / 'report.json') if (output / 'report.json').exists() else {}
        status = child.get('status', 'failed_no_report')
        if result['exit_code'] != 0 and status in ('completed', 'trained_pending_reload'):
          status = 'failed_exit_code'
        entry.update(status=status, exit_code=result['exit_code'])
    except Exception as error:
      entry.update(status='supervision_failed', error_type=type(error).__name__, error=str(error))
      report['status'] = 'supervision_failed'
      save()
      raise
    statuses[name] = entry['status']
    save()
    print(json.dumps({'stage': name, 'status': entry['status']}), flush=True)
  report['quality_table'] = collectQuality(report['stages'])
  report['status'] = 'completed' if all(status == ('trained_pending_reload' if name.endswith('_train') else 'completed') for name, status in statuses.items()) else 'incomplete'
  save()
  print(json.dumps({'campaign': str(args.run_dir / 'campaign.json'), 'status': report['status']}), flush=True)


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--scope', choices=['full', 'qlora'], default='full')
  parser.add_argument('--max-hours', type=float, required=True)
  parser.add_argument('--runtime-dir', type=Path, required=True)
  parser.add_argument('--run-dir', type=Path, required=True)
  parser.add_argument('--baseline-nf4', type=Path, help='Reuse a complete matching baseline')
  arguments = parser.parse_args()
  if arguments.max_hours <= 0:
    parser.error('--max-hours must be positive')
  campaign(arguments)
