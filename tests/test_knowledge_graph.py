import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_graph_scenario(tmp_path):
  env = {**os.environ, 'APP_MODE': 'demo', 'DEMO_MODE': '1',
    'BOOTSTRAP_PASSWORD': 'Isolated-Graph-Fixture-123456',
    'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'graph.db'),
    'OPENAI_ENABLED': '0', 'LOCAL_LLM_MODEL': '', 'OLLAMA_MODEL': ''}
  result = subprocess.run([sys.executable, str(ROOT / 'tests/graph_scenario.py')],
    cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=120)
  assert result.returncode == 0, result.stdout + result.stderr
  assert json.loads(result.stdout.strip().splitlines()[-1])['passed'] >= 20


def test_graph_evaluation_has_real_quality_gates(tmp_path):
  output = tmp_path / 'evaluation.json'
  result = subprocess.run([sys.executable, str(ROOT / 'scripts/evaluate_knowledge_graph.py'), '--output', str(output)],
    cwd=ROOT, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
    capture_output=True, text=True, encoding='utf-8', timeout=120)
  assert result.returncode == 0, result.stdout + result.stderr
  report = json.loads(output.read_text(encoding='utf-8'))
  assert report['qualityGatePassed'] is True
  assert report['sourceScope'] == 'fixed_snapshot_only'
  assert report['evaluatedSourceIds'] == ['KG-SYNTH-A', 'KG-SYNTH-B', 'KG-SYNTH-C', 'KG-SYNTH-D',
    'KG-SYNTH-INJECTION', 'KG-SYNTH-OTHER']
  assert len(report['questions']) == 12 and report['authorizationPassed']
  assert report['summary']['keyword_plus_graph']['macroRecallOnRelevantQuestions'] >= report['summary']['keyword']['macroRecallOnRelevantQuestions']
  from scripts.evaluate_knowledge_graph import qualityFailures
  report['questions'][0]['modes']['keyword_plus_graph']['noAutomaticActions'] = False
  assert qualityFailures(report)
