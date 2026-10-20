import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PAGES=['/','/console.html','/knowledge.html','/workflow.html','/scan.html','/mobile.html']


def runApp(tmpPath,mode,code):
  # 匯入 backend 會固定 DATABASE_URL，必須在子程序執行，避免影響 test_api 的隔離資料庫
  env={**os.environ,'APP_MODE':mode,'DEMO_MODE':'1' if mode=='demo' else '0','BOOTSTRAP_PASSWORD':'Isolated-Csp-Password-123456',
       'DATABASE_URL':'sqlite:///'+str(tmpPath/f'{mode}.db'),'LOCAL_LLM_MODEL':'','OLLAMA_MODEL':''}
  script='import json\nfrom fastapi.testclient import TestClient\nfrom backend.app import app\nwith TestClient(app) as client:\n'+code
  result=subprocess.run([sys.executable,'-c',script],env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=120)
  assert result.returncode==0,result.stderr
  return json.loads(result.stdout.strip().splitlines()[-1])


def directives(header):
  return {part.split()[0]:part.split()[1:] for part in (header or '').split(';') if part.strip()}


def assertStrict(header):
  policy=directives(header)
  # 不允許 'unsafe-inline'：注入的 <script>、事件屬性與 style 屬性都不會生效
  assert policy['script-src']==["'self'"] and policy['style-src']==["'self'"]
  assert policy['object-src']==["'none'"] and policy['base-uri']==["'none'"] and policy['frame-ancestors']==["'none'"]


def test_demo_pages_send_strict_csp_and_docs_use_their_own_policy(tmp_path):
  code=('    pages={p:client.get(p).headers.get("content-security-policy") for p in %r}\n'
        '    docs=client.get("/docs")\n'
        '    print(json.dumps({"pages":pages,"docs_status":docs.status_code,"docs_csp":docs.headers.get("content-security-policy")}))\n')%PAGES
  report=runApp(tmp_path,'demo',code)
  for header in report['pages'].values():
    assertStrict(header)
  assert report['docs_status']==200 and 'https://cdn.jsdelivr.net' in directives(report['docs_csp'])['script-src']


def test_production_hides_api_docs_and_sends_strict_csp(tmp_path):
  code=('    statuses={p:client.get(p).status_code for p in ["/docs","/redoc","/openapi.json","/docs/oauth2-redirect","/mobile.html","/app.js","/app.css"]}\n'
        '    print(json.dumps({"statuses":statuses,"csp":client.get("/").headers.get("content-security-policy")}))\n')
  report=runApp(tmp_path,'production',code)
  # 正式模式不需登入就能看到完整 API 結構，且 Swagger 需要外部 CDN；只在展示模式提供
  assert set(report['statuses'].values())=={404}
  assertStrict(report['csp'])


def test_served_files_have_no_inline_code_or_style_attributes():
  mobile=ROOT/'sites/predictfix-mobile/dist'
  for path in sorted(ROOT.glob('*.html'))+sorted(ROOT.glob('*.js'))+sorted(mobile.glob('*.html'))+sorted(mobile.glob('*.js')):
    text=path.read_text(encoding='utf-8')
    # 嚴格 CSP 會直接擋掉這些寫法，畫面會在不報錯的情況下少掉樣式或功能
    assert not re.search(r'\sstyle\s*=',text),path.name
    # 執行時建立 <style> 元素同樣會被 style-src 擋下
    assert not re.search(r"createElement\(\s*['\"]style['\"]\s*\)",text),path.name
    if path.suffix=='.html':
      assert '<style' not in text,path.name
      assert not re.search(r'<script(?![^>]*\ssrc=)[^>]*>',text),path.name


def test_mobile_demo_assets_load_with_strict_csp(tmp_path):
  code=('    paths=["/mobile.html","/app.js","/app.css"]\n'
        '    print(json.dumps({p:{"status":client.get(p).status_code,"csp":client.get(p).headers.get("content-security-policy")} for p in paths}))\n')
  report=runApp(tmp_path,'demo',code)
  for path,result in report.items():
    assert result['status']==200,path
    assertStrict(result['csp'])


def test_scan_page_is_served_and_linked_in_both_modes(tmp_path):
  code='    print(json.dumps({p:client.get(p).status_code for p in ["/scan.html","/scan.js","/scan.css"]}))\n'
  for mode in ['demo','production']:
    assert set(runApp(tmp_path,mode,code).values())=={200},mode
  # demo 與正式模式的首頁不同，兩邊的導覽列都要能進到掃描頁
  for page in ['index.html','console.html']:
    assert 'href="/scan.html"' in (ROOT/page).read_text(encoding='utf-8'),page
