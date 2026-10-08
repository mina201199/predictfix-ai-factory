"""Each security category runs in a fresh process and production-mode database."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('category', ['injection', 'access', 'leakage', 'hallucination'])
def test_security_category(category, tmp_path):
    env = {**os.environ, 'APP_MODE': 'production', 'DEMO_MODE': '0',
           'BOOTSTRAP_PASSWORD': 'Security-Fixture-Password-123456',
           'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'security.db'),
           'LOCAL_LLM_MODEL': '', 'OLLAMA_MODEL': '',
           'SECURITY_ENV_CANARY': 'ENV-CANARY-NOT-FOR-MODEL-789'}
    result = subprocess.run([sys.executable, str(ROOT / 'tests/security_scenario.py'), category],
                            cwd=ROOT, env=env, capture_output=True, text=True,
                            encoding='utf-8', timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['category'] == category and report['checks']
    assert all(report['checks'].values())
