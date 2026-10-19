"""在匯入資料庫前讀取明確指定的 .env；不展開或執行檔案內容。"""
import argparse
import os
from pathlib import Path
import re
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ALLOWED = {'INTEGRATION_SOURCES', 'DATABASE_URL', 'APP_MODE', 'DEMO_MODE', 'BOOTSTRAP_PASSWORD'}


def loadSettings(path):
  for lineNumber, rawLine in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), start=1):
    line = rawLine.strip()
    if not line or line.startswith('#'):
      continue
    key, separator, value = line.partition('=')
    key, value = key.strip(), value.strip()
    if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
      raise ValueError('Invalid env syntax at line ' + str(lineNumber))
    if value.startswith(('"', "'")):
      if len(value) < 2 or value[-1] != value[0]:
        raise ValueError('Invalid env quote at line ' + str(lineNumber))
      value = value[1:-1]
    if key in ALLOWED:
      os.environ.setdefault(key, value)


def main():
  parser = argparse.ArgumentParser(description='Integration environment launcher')
  parser.add_argument('--env-file', type=Path, required=True)
  parser.add_argument('mode', choices=['serve', 'worker', 'simulator'])
  args, remaining = parser.parse_known_args()
  try:
    loadSettings(args.env_file)
  except (OSError, ValueError) as error:
    raise SystemExit('Unable to load integration environment: ' + (str(error) if isinstance(error, ValueError) else 'file unavailable')) from None
  if remaining and remaining[0] == '--':
    remaining = remaining[1:]
  if args.mode == 'serve':
    serve = argparse.ArgumentParser()
    serve.add_argument('--port', type=int, default=8096)
    settings = serve.parse_args(remaining)
    if not 1024 <= settings.port <= 65535:
      serve.error('port must be 1024..65535')
    import uvicorn
    uvicorn.run('backend.app:app', host='127.0.0.1', port=settings.port)
  else:
    module = 'backend.integration_worker' if args.mode == 'worker' else 'scripts.integration_simulator'
    sys.argv = [module, *remaining]
    runpy.run_module(module, run_name='__main__')


if __name__ == '__main__':
  main()
