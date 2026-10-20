from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_production_delivers_integration_configuration_to_api_and_worker():
  compose = yaml.safe_load((ROOT / 'compose.production.yaml').read_text(encoding='utf-8'))
  api = compose['services']['api']
  worker = compose['services'].get('integration-worker')
  assert worker is not None, '正式部署缺少背景工單傳送服務'
  assert worker['command'] == ['python', '-m', 'backend.integration_worker']
  assert api['environment'].get('INTEGRATION_SOURCES'), '介接設定沒有傳入 API'
  assert worker['environment']['INTEGRATION_SOURCES'] == api['environment']['INTEGRATION_SOURCES']
  assert worker['environment']['DATABASE_URL'] == api['environment']['DATABASE_URL']
  assert worker['depends_on']['api']['condition'] == 'service_healthy'
  assert worker['restart'] == 'unless-stopped'
  assert worker.get('init') is True or worker.get('stop_signal') == 'SIGINT'
  assert not worker.get('ports')
