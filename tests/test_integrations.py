import os
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('mode', ['production', 'demo'])
def test_isolated_integration_contract(mode, tmp_path):
  env = {**os.environ, 'APP_MODE': mode, 'DEMO_MODE': '1' if mode == 'demo' else '0',
    'BOOTSTRAP_PASSWORD': 'Isolated-Integration-Password-123456',
    'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'integration.db'),
    'LOCAL_LLM_MODEL': '', 'OLLAMA_MODEL': '', 'OPENAI_ENABLED': '0', 'PYTHONIOENCODING': 'utf-8'}
  result = subprocess.run([sys.executable, '-m', 'pytest', '--confcutdir=.', '--rootdir=.',
    'tests/integration_scenario.py', '-q', '-x', '-p', 'no:cacheprovider', '--basetemp=' + str(tmp_path / 'child'),
    '--junitxml=' + str(tmp_path / 'child-report.xml')],
    cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=180)
  assert result.returncode == 0, result.stdout + '\n' + result.stderr
  suites = ElementTree.parse(tmp_path / 'child-report.xml').getroot().findall('testsuite')
  assert sum(int(suite.attrib['tests']) for suite in suites) > 0
  assert sum(int(suite.attrib['skipped']) for suite in suites) == 0, '介接子程序不得以 skip 掩蓋缺測'
