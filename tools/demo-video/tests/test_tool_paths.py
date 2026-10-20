import importlib.util
import sys
import types
from pathlib import Path


def test_recorder_can_read_repository_measurements(monkeypatch):
  asyncApi = types.ModuleType('playwright.async_api')
  asyncApi.async_playwright = None
  monkeypatch.setitem(sys.modules, 'playwright', types.ModuleType('playwright'))
  monkeypatch.setitem(sys.modules, 'playwright.async_api', asyncApi)
  path = Path(__file__).resolve().parents[1] / 'record.py'
  spec = importlib.util.spec_from_file_location('demo_video_recorder', path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  measurements = (module.REPO / 'demo-measurements.csv').read_text(encoding='utf-8-sig')
  assert measurements.splitlines()[0] == 'metric,before,after,conditions'
