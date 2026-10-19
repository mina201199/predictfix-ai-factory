# 機台銘牌掃描總覽 Implementation Plan

**執行紀錄（2026-10-19）：** 已完成實作並保留在 `feat/postgres-and-machine-scan`。105 項 pytest、零跳過；Node 掃描競態檢查與 PostgreSQL 容器重啟／備份還原驗證通過。OCR 90 張合成銘牌 top-1 100%、自動開錯台 0；桌面及 375×812 手機尺寸已操作。實體手機／Getac 的區網連線與相機仍待裝置實測，HTTPS 與 App 為後續工作。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal：** 拍機台銘牌 → 伺服器端 OCR 讀出機台編號 → 顯示涵蓋 9 個面向的機台總覽 → 本機模型產生附來源的摘要與建議；另提供選用的區網模式讓手機連線拍照。

**Architecture：** 純函式（OCR 比對、可靠度計算）放在不匯入 `backend.store` 的模組，方便單元測試；API 集中在 `backend/machine_scan.py`，以 `register(app)` 接進 `backend/app.py`。前端是新的原生頁面 `scan.html`。API 行為以子程序情境腳本測試，沿用 `tests/test_repair_flow.py` 的做法。

**Tech Stack：** Python 3.12、FastAPI、Pillow 12.3、RapidOCR（ONNX Runtime，CPU；不可行時改 Tesseract）、原生 HTML/CSS/JS、PowerShell。

**Spec：** `docs/superpowers/specs/2026-10-16-machine-scan-and-postgres-design.md`（第 5 節）

## Global Constraints

- 接續 PostgreSQL 計畫的分支 `feat/postgres-and-machine-scan`。
- 所有功能離線可用；OCR 模型在 `docker build` 與 `setup.ps1` 階段就位，執行時不得下載任何東西。OCR 相關套件版本固定寫進 `requirements.txt`。
- 嚴格 CSP：`.html`／`.js` 不得出現 `style=` 屬性、`<style>`、inline `<script>`、`createElement('style')`（`tests/test_csp.py` 會檢查）；也不得使用外部 CDN。
- 新前端檔案要加進 `backend/app.py` 的 `STATIC`。
- 新路由不放進 `DEMO_ONLY_PATHS`；demo 與正式模式都要能用，所有缺值以 `null` 回傳、前端顯示「尚無資料」。唯一例外：範例銘牌 API 在正式模式回 404。
- 上傳限制沿用 `backend/evidence.py`：6 MB、Pillow `verify()`、`DecompressionBombWarning` 視為錯誤、最多 2,000 萬畫素。
- OCR 決策門檻：信心 ≥ `0.85` 自動開啟；`0.50`～`0.85` 列候選請使用者確認；其餘改手動輸入。
- 可靠度：MTBF 需 ≥ 3 張工單，MTTR 需 ≥ 2 張已結工單，不足時回 `null`（前端顯示「樣本不足」）。結案時間取 workflow `reviews` 中最後一筆 `decision=='approve'` 的 `at`，**不用** `approved_at`。
- 所有登入使用者（`engineer`、`supervisor`）都可使用掃描、總覽、AI 摘要。
- `backend/nameplate.py`、`backend/machine_metrics.py`、`scripts/generate_nameplates.py` 在模組層級不可 import `backend.store` 或 `backend.app`（避免 pytest 收集測試時固定 `DATABASE_URL`）。
- 銘牌文字只用英數字，字型用 Pillow 內建 `ImageFont.load_default(size=...)`，Windows 與 CI 結果一致，也沒有字型授權問題。
- 「示範資料」標示只在 `/api/auth/config` 回傳 `app_mode=='demo'` 時顯示。
- 新檔案縮排 2 個空白；修改既有檔案沿用該檔案縮排。註解用正體中文，只說明「為什麼」。密碼不寫進程式碼。

## Review Focus

- 照片裡完全沒有字，或拍到的是別的東西 → 回傳空候選、`decision:'manual'`，頁面直接跳到手動輸入，不能卡住（測試：情境腳本上傳純色圖片）。
- 銘牌上有多個像編號的字串（型號 `VMC-850`、序號 `24-0137`）→ 只把資料庫中存在的機台列為候選，型號與序號不能被誤判成機台（測試：`test_ignores_model_and_serial_numbers`）。
- OCR 把 `0` 讀成 `O`、`1` 讀成 `l` → 仍要比對到正確機台（測試：`test_confuses_letters_and_digits`）。
- 本機模型沒開、逾時或回傳格式錯誤 → 總覽仍正常顯示，AI 區塊改為「規則產生」，不顯示錯誤頁（測試：情境腳本在未設定模型時呼叫 `ai-summary`）。
- 正式模式新建的設備沒有任何感測值與工單 → 總覽各區塊回 `null`／空陣列，可靠度回 `null`，不出 500（測試：正式模式情境腳本）。

---

### Task 1：銘牌產生器與 OCR 比對核心

**Files:**
- Create: `scripts/generate_nameplates.py`
- Create: `backend/nameplate.py`
- Modify: `requirements.txt`、`scripts/check_runtime.py`（加入 OCR import 檢查）、`Dockerfile`（build 時呼叫 `warmup()`）、`setup.ps1`（若安裝流程需要額外步驟）
- Test: `tests/test_nameplate.py`

**Interfaces:**
- Produces（`scripts/generate_nameplates.py`）：
  - `VARIANTS = ('clean', 'perspective', 'blur', 'glare', 'low_contrast')`
  - `render_nameplate(machine_id: str, variant: str = 'clean', seed: int = 0) -> PIL.Image.Image`：虛構廠牌 `TAIHO MACHINERY CO.`，內容含 `MODEL VMC-850`、`SERIAL No. 24-0137`（依 seed 變化）、`3PH 220V 60Hz`、`MFG 2024-03`，以及最大字級的 `MACHINE ID <machine_id>`。
  - CLI：`python scripts/generate_nameplates.py --out artifacts/demo-nameplates` 輸出 `CNC-01.png`～`CNC-18.png`（只輸出 clean 版本）與 `print-sheet.png`（3×6 排版可列印）。
- Produces（`backend/nameplate.py`）：
  - `AUTO_OPEN = 0.85`、`CONFIRM_MIN = 0.50`
  - `normalize_text(text: str) -> str`
  - `match_machine_ids(lines: list[tuple[str, float]], machine_ids: list[str]) -> list[dict]`：回傳依信心由高到低、最多 3 筆的 `{'machine_id': str, 'confidence': float, 'raw_text': str}`，只含 `confidence >= CONFIRM_MIN`。
  - `decide(candidates: list[dict]) -> str`：`'auto' | 'confirm' | 'manual'`
  - `recognize(image_bytes: bytes) -> list[tuple[str, float]]`：OCR 每一行文字與分數；引擎延遲建立並快取。
  - `warmup() -> dict`：建立引擎並辨識一張內建小圖，回傳 `{'engine': str, 'version': str}`。
  - `engine_info() -> dict`：同上的引擎名稱與版本，不觸發辨識。

- [ ] **Step 1：確認 OCR 引擎可行（決策關卡）**

在 venv 安裝 RapidOCR 的 ONNX Runtime 版本（優先選 `opencv-python-headless` 相依），確認：Python 3.12 可安裝、模型檔隨套件存在本機、拔掉網路（或設定不存在的 proxy 環境變數）後仍能辨識 `render_nameplate('CNC-07')`。任一項失敗就改用 Tesseract（Docker 以 apt 安裝、Windows 由 `setup.ps1` 檢查），並在 commit 訊息寫明原因。

- [ ] **Step 2：寫失敗的測試**

```python
IDS=[f'CNC-{n:02}' for n in range(1,19)]

def test_exact_match_auto_opens():
  c=nameplate.match_machine_ids([('MACHINE ID CNC-07',0.98)],IDS)
  assert c[0]['machine_id']=='CNC-07' and nameplate.decide(c)=='auto'

def test_confuses_letters_and_digits():
  assert nameplate.match_machine_ids([('CNC-0l',0.95)],IDS)[0]['machine_id']=='CNC-01'
  assert nameplate.match_machine_ids([('CNC O7',0.95)],IDS)[0]['machine_id']=='CNC-07'

def test_ignores_model_and_serial_numbers():
  lines=[('MODEL VMC-850',0.99),('SERIAL No. 24-0137',0.99),('MACHINE ID CNC-12',0.97)]
  c=nameplate.match_machine_ids(lines,IDS)
  assert c[0]['machine_id']=='CNC-12' and all(x['machine_id'] in IDS for x in c)

def test_unknown_id_never_auto_opens():
  assert nameplate.decide(nameplate.match_machine_ids([('CNC-99',0.99)],IDS))!='auto'

def test_production_style_ids():
  assert nameplate.match_machine_ids([('ID MILL-001',0.9)],['MILL-001','M01'])[0]['machine_id']=='MILL-001'

def test_no_text_means_manual():
  assert nameplate.decide(nameplate.match_machine_ids([],IDS))=='manual'

def test_reads_rendered_nameplate():
  image=generate_nameplates.render_nameplate('CNC-07')
  buffer=io.BytesIO();image.save(buffer,'PNG')
  c=nameplate.match_machine_ids(nameplate.recognize(buffer.getvalue()),IDS)
  assert c[0]['machine_id']=='CNC-07' and c[0]['confidence']>=nameplate.AUTO_OPEN
```

- [ ] **Step 3：執行測試確認失敗**

Run: `.venv\Scripts\python.exe -m pytest tests/test_nameplate.py -q`
Expected: FAIL（模組不存在）

- [ ] **Step 4：實作產生器與 `backend/nameplate.py`**

比對方式：正規化後以 regex 取出 `字母段-數字段` 形式的 token，對每個機台編號用 `difflib.SequenceMatcher` 計算相似度（數字段先做 `O→0、I/L→1、S→5、B→8` 的修正版本，取兩者較高分），`confidence = OCR 分數 × 相似度`，每台機台只留最高分。

- [ ] **Step 5：執行測試確認通過，並跑完整 pytest**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 全部 PASS，0 skipped

- [ ] **Step 6：確認 Docker 映像可離線載入引擎**

Run: `docker build -t predictfix-ocr-check .` 然後 `docker run --rm --network none predictfix-ocr-check python -c "from backend.nameplate import warmup; print(warmup())"`
Expected：印出引擎名稱與版本，沒有網路錯誤

- [ ] **Step 7：Commit**

```bash
git add scripts/generate_nameplates.py backend/nameplate.py tests/test_nameplate.py requirements.txt scripts/check_runtime.py Dockerfile setup.ps1
git commit -m "Add offline nameplate OCR and machine ID matching"
```

### Task 2：掃描 API 與範例銘牌

**Files:**
- Create: `backend/machine_scan.py`
- Modify: `backend/app.py`（`machine_scan.register(app)`）
- Create: `artifacts/demo-nameplates/`（執行 Task 1 的 CLI 產生，commit 18 張 clean PNG 與 `print-sheet.png`）
- Create: `tests/machine_scan_scenario.py`（demo 模式）、`tests/test_machine_scan.py`
- Test：同上

**Interfaces:**
- Consumes：Task 1 的 `recognize`、`match_machine_ids`、`decide`、`render_nameplate`。
- Produces：
  - `POST /api/scan/nameplate`：raw body 圖片（與 `/api/tickets/{tid}/photos` 相同上傳方式）→ `{'candidates': [...], 'decision': 'auto'|'confirm'|'manual', 'text': [str], 'elapsed_ms': int, 'engine': str}`。比對對象是 `active` 的機台。OCR 以 `run_in_threadpool` 執行，不阻塞事件迴圈。
  - `GET /api/scan/samples` → `[{'machine_id': str, 'url': '/api/scan/samples/CNC-01.png'}]`；`GET /api/scan/samples/{name}`：`name` 只接受 `^[A-Z]{2,5}-\d{2}\.png$`，從 `artifacts/demo-nameplates/` 讀檔。兩者在正式模式回 404。
  - `tests/test_machine_scan.py::run_scenario(tmp_path, script: str, mode: str) -> str`：沿用 `tests/test_repair_flow.py` 的子程序環境設定（`OLLAMA_MODEL=''`、`LOCAL_LLM_MODEL=''`），後續 Task 的情境都用它。

- [ ] **Step 1：寫失敗的情境腳本與測試**

`tests/machine_scan_scenario.py`（demo 模式，supervisor 登入）至少斷言：
- 上傳 `render_nameplate('CNC-07')` → `decision=='auto'` 且第一個候選是 `CNC-07`
- 上傳 400×300 純灰 PNG → `candidates==[]` 且 `decision=='manual'`
- 上傳文字檔 → 422；上傳 7 MB → 413
- 登出後呼叫 → 401
- 以 engineer（`amy`）登入也能掃描 → 200
- `GET /api/scan/samples` 回 18 筆，第一筆圖片可取得且 `content-type` 為 `image/png`
- `GET /api/scan/samples/..%2Fsecret.png` → 404

- [ ] **Step 2：執行測試確認失敗**

Run: `.venv\Scripts\python.exe -m pytest tests/test_machine_scan.py -q`
Expected: FAIL

- [ ] **Step 3：實作 `backend/machine_scan.py` 掃描與範例路由，產生並加入範例銘牌圖片**

- [ ] **Step 4：執行測試確認通過，並跑完整 pytest**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 全部 PASS，0 skipped

- [ ] **Step 5：Commit**

```bash
git add backend/machine_scan.py backend/app.py artifacts/demo-nameplates tests/machine_scan_scenario.py tests/test_machine_scan.py
git commit -m "Add nameplate scan API and demo nameplate samples"
```

### Task 3：機台總覽、可靠度與歷史資料灌入

**Files:**
- Create: `backend/machine_metrics.py`
- Create: `scripts/seed_machine_history.py`
- Modify: `backend/machine_scan.py`（總覽路由）
- Create: `tests/test_machine_metrics.py`、`tests/machine_scan_production_scenario.py`
- Modify: `tests/machine_scan_scenario.py`、`tests/test_machine_scan.py`

**Interfaces:**
- Produces（`backend/machine_metrics.py`，純函式）：
  - `closed_at(workflow: dict) -> datetime | None`：`reviews` 中最後一筆 `decision=='approve'` 的 `at`。
  - `reliability(tickets: list[dict]) -> dict`：每筆 ticket 需有 `created_at: datetime`、`closed_at: datetime | None`；回傳 `{'failures': int, 'mtbf_days': float | None, 'mttr_hours': float | None, 'mtbf_samples': int, 'mttr_samples': int}`。MTBF 為相鄰工單建立時間間隔的平均，四捨五入到小數 1 位。
- Produces（`scripts/seed_machine_history.py`）：
  - `seed_history() -> dict`：只在 `APP_MODE=demo` 執行，否則 `raise SystemExit`；以 audit `machine_history_seed_v1` 確保只灌一次；為 `CNC-01`～`CNC-18` 各建立 3～6 張回溯 30～330 天的已結工單（id 前綴 `HIST-`、issue 前綴 `【DEMO 歷史】`，含 workflow `reviews` 核准紀錄、工作紀錄、結案說明），並讓約 1/3 的機台有一張 `維修中` 的工單與最新工作紀錄。回傳 `{'machines': int, 'tickets': int}`。
  - 因為要回溯建立時間，這支腳本直接寫資料庫，不走 API；`backend.store` 在函式內才匯入。
- Produces（`backend/machine_scan.py`）：`build_overview(db, mid: str) -> dict | None`（機台不存在或停用時回 `None`），路由與 Task 4 都呼叫它。
- Produces：`GET /api/machines/{mid}/overview` →

```
{'data_mode': 'demo'|'production',
 'machine': {'id','name','kind','machine_model','installed_on','hours'},
 'live': {'status','risk','temp','vib','util'},
 'parts': [{'name','health','used','life','remaining','note','replaced_on'}],
 'people': {'responsible': {'name','on_duty','attendance','shift','open_tickets'} | None,
            'last_inspection': {'date','inspector','note'} | None},
 'in_progress': [{'id','issue','engineer','status','created_at','logged_minutes','latest_log'}],
 'history': [{'id','issue','engineer','created_at','closed_at','completion_note','photo_count','case_id'}],
 'maintenance': {'next_inspection', 'plans': [{'id','title','next_due','days_until_due','reminder'}]},
 'stock': [{'part','item_id','name','quantity','minimum','low'}],
 'reliability': <reliability() 的結果>}
```

  - 不存在或已停用的機台 → 404。`history` 依結案時間新到舊、最多 20 筆。負責人在班狀態重用 `workforce.roster()`，以姓名比對 `asset.responsible`。備品以零件名稱是否包含於庫存品項名稱（或反之）比對，比不到就不列出。查詢需批次取資料，不可每張工單各查一次。

- [ ] **Step 1：寫失敗的單元測試**

```python
def test_reliability_needs_enough_samples():
  r=machine_metrics.reliability([ticket(days_ago=10,closed_hours=5),ticket(days_ago=5,closed_hours=None)])
  assert r['mtbf_days'] is None and r['mttr_hours'] is None and r['failures']==2

def test_reliability_values():
  r=machine_metrics.reliability([ticket(30,4),ticket(20,6),ticket(10,None)])
  assert r['mtbf_days']==10.0 and r['mttr_hours']==5.0

def test_closed_at_uses_last_approval_not_procedure_approval():
  wf={'approved_at':'2026-01-01T00:00:00+00:00','reviews':[{'decision':'reject','at':'2026-02-01T00:00:00+00:00'},{'decision':'approve','at':'2026-02-03T00:00:00+00:00'}]}
  assert machine_metrics.closed_at(wf).isoformat().startswith('2026-02-03')
```

- [ ] **Step 2：擴充情境腳本並寫正式模式情境**

demo 情境：呼叫 `seed_history()` 後，`CNC-07` 總覽所有頂層鍵都存在、`history` 非空、`reliability['mtbf_days']` 不是 `None`；在 `in_progress` 有工單的機台，`latest_log` 不是 `None`；`/api/machines/CNC-99/overview` → 404。
正式模式情境（`tests/machine_scan_production_scenario.py`）：建立 `MILL-001` 後總覽 200，`live['temp'] is None`、`history==[]`、`reliability['mtbf_days'] is None`；`/api/scan/samples` → 404；`seed_history()` 在正式模式會 `SystemExit`。

- [ ] **Step 3：執行測試確認失敗**

Run: `.venv\Scripts\python.exe -m pytest tests/test_machine_metrics.py tests/test_machine_scan.py -q`
Expected: FAIL

- [ ] **Step 4：實作 `machine_metrics.py`、`seed_machine_history.py` 與總覽路由**

- [ ] **Step 5：執行測試確認通過，並跑完整 pytest**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 全部 PASS，0 skipped

- [ ] **Step 6：Commit**

```bash
git add backend/machine_metrics.py backend/machine_scan.py scripts/seed_machine_history.py tests
git commit -m "Add machine overview with people, history, maintenance, stock and reliability"
```

### Task 4：AI 摘要與規則退回

**Files:**
- Modify: `backend/machine_scan.py`
- Modify: `tests/machine_scan_scenario.py`
- Test: `tests/test_machine_scan.py`

**Interfaces:**
- Consumes：Task 3 的總覽建構函式（`build_overview(db, mid: str) -> dict`，在 Task 3 定義於 `backend/machine_scan.py`）、`maintenance_ai.search(query, machine_model=..., limit=4)`、`maintenance_ai.generate_json(prompt, schema)`。
- Produces：
  - `rule_summary(overview: dict) -> dict`（純函式，放在 `backend/machine_metrics.py`）：依序挑出「健康度 < 80 的零件」「逾期或 7 天內到期的保養」「未結工單」「庫存低於安全量的備品」，產生摘要與建議。
  - `POST /api/machines/{mid}/ai-summary` → `{'mode': 'llm'|'rule', 'summary': [str, str, str], 'suggestions': [{'text': str, 'source': {'type': 'part'|'ticket'|'manual'|'plan'|'stock', 'ref': str}}], 'meta': {...generate_json 回傳的 meta}}`；`suggestions` 2～4 條，每條都要有 `source`。
  - 模型輸出的 `source.ref` 必須是總覽或檢索結果中真實存在的零件名稱、工單 id、手冊 id、保養計畫 id 或備品 id；不存在就丟棄該條。丟到少於 2 條時整體改用 `rule_summary`。

- [ ] **Step 1：寫失敗的情境斷言**

未設定模型（情境環境已清空 `OLLAMA_MODEL`、`LOCAL_LLM_MODEL`）時：`ai-summary` 回 200、`mode=='rule'`、`len(summary)==3`、`2<=len(suggestions)<=4`、每條 `source['type']` 在允許清單內。另在單元測試以假的 overview 驗證 `rule_summary` 會把健康度 78 的「切削刀具」列入建議。

- [ ] **Step 2：執行測試確認失敗**

Run: `.venv\Scripts\python.exe -m pytest tests/test_machine_scan.py tests/test_machine_metrics.py -q`
Expected: FAIL

- [ ] **Step 3：實作 `rule_summary` 與 `ai-summary` 路由**

提示詞用正體中文，只放總覽中與建議相關的欄位與檢索到的手冊段落，要求模型只能引用提供的 ref；JSON schema 限制 `summary` 恰好 3 項。

- [ ] **Step 4：執行測試確認通過，並跑完整 pytest**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 全部 PASS，0 skipped

- [ ] **Step 5：用本機模型手動驗證一次**

Run: `.\start.ps1 -Demo` 後在另一個終端機以 demo 登入並 `POST /api/machines/CNC-07/ai-summary`
Expected：`mode=='llm'`，每條建議的 `source.ref` 都能在總覽或手冊中找到（若本機沒有模型檔，記錄為「未驗證」並回報）

- [ ] **Step 6：Commit**

```bash
git add backend/machine_scan.py backend/machine_metrics.py tests
git commit -m "Add grounded AI machine summary with rule-based fallback"
```

### Task 5：掃描頁面

**Files:**
- Create: `scan.html`、`scan.js`、`scan.css`
- Modify: `backend/app.py`（`STATIC` 加入三個檔案）
- Modify: `index.html`（demo 導覽列加 `<a class="nav" href="/scan.html">`）、`console.html`（導覽列加 `<a href="/scan.html">`）
- Modify: `tests/test_csp.py`（`PAGES` 加 `/scan.html`）、`scripts/check_container.py`（頁面清單加 `/scan.html`）

**Interfaces:**
- Consumes：Task 2～4 的 API、`/api/auth/config`、`/api/machines`、`auth.js` 的登入流程（照 `workflow.html` 引入方式）。

- [ ] **Step 1：寫失敗的測試**

`tests/test_csp.py` 的 `PAGES` 加入 `/scan.html`，並新增斷言：demo 與正式模式 `GET /scan.html` 皆 200、`GET /scan.js` 200。

- [ ] **Step 2：執行測試確認失敗**

Run: `.venv\Scripts\python.exe -m pytest tests/test_csp.py -q`
Expected: FAIL（404）

- [ ] **Step 3：實作頁面**

版面由上到下：
1. 取得照片：`<input type="file" accept="image/*" capture="environment">`、拖放區、demo 模式才顯示的範例銘牌選單（點選後抓圖片 blob 再送 `scan/nameplate`，讓 OCR 真的執行）、手動輸入（`<datalist>` 列出 `/api/machines` 的編號）。
2. OCR 結果：編號、信心百分比、處理毫秒、「修正」按鈕；`confirm` 時列候選按鈕，`manual` 時聚焦手動輸入。
3. 一眼摘要：先顯示「AI 分析中…」，取得後顯示 3 行摘要；`mode=='rule'` 時標「規則產生」。
4. 用 `<details>` 收合的分段：現況（零件健康度用 `<meter>`）→ 人員與進行中 → 歷史檢修 → 保養與備品 → 可靠度（`null` 顯示「樣本不足」）→ AI 建議（每條附來源標籤）。
5. 操作：「建立工單」連到既有報修頁、「問 AI」連到 `knowledge.html`；若目標頁已支援帶入機台參數就帶上，否則只連結。
6. demo 模式頂部顯示「示範資料」標示。

- [ ] **Step 4：執行測試確認通過，並跑完整 pytest**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 全部 PASS，0 skipped

- [ ] **Step 5：在瀏覽器實際操作**

`.\start.ps1 -Demo` 後開 `http://127.0.0.1:8080/scan.html`，以 Browser pane 的 mobile（375×812）與 desktop 各走一次：範例銘牌 → 自動開啟總覽 → 各分段有內容 → AI 摘要出現；再上傳純灰圖片確認跳到手動輸入。console 不得有 CSP 錯誤。

- [ ] **Step 6：Commit**

```bash
git add scan.html scan.js scan.css backend/app.py index.html console.html tests/test_csp.py scripts/check_container.py
git commit -m "Add mobile-first machine scan page"
```

### Task 6：區網模式

**Files:**
- Modify: `backend/config.py`、`backend/auth.py`、`start.ps1`
- Create: `tests/test_lan_mode.py`

**Interfaces:**
- Produces：
  - `config.lan() -> bool`：`os.getenv('LAN_MODE') == '1'`
  - `config.validate()` 新增：`lan()` 且 `DEMO_MODE=='1'` 時 `raise RuntimeError('LAN mode forbids quick login')`
  - `/api/auth/config` 新增 `'lan_mode': bool`；`/api/auth/demo` 在 `config.lan()` 時一律 403（即使 `DEMO_MODE` 被誤設）。
  - `start.ps1 -Lan`：`$env:LAN_MODE='1'`、`$env:DEMO_MODE='0'`（即使同時加 `-Demo`），uvicorn `--host 0.0.0.0`；`LAN_MODE` 加入 `$managedVariables`；啟動前印出每個非 loopback、非 169.254 的 IPv4 對應網址 `http://<ip>:<port>/scan.html`、帳號密碼來源（`.env` 的 `BOOTSTRAP_PASSWORD` 或 `data/initial-accounts.json`，不印出密碼本身），以及防火牆指令 `New-NetFirewallRule -DisplayName "PredictFix LAN demo" -Direction Inbound -Protocol TCP -LocalPort <port> -Profile Private -Action Allow`（只印出，不執行）。llama.cpp、Ollama 維持 `127.0.0.1`。

- [ ] **Step 1：寫失敗的測試**（子程序執行，沿用 `tests/test_csp.py::runApp` 的做法）

```python
def test_lan_mode_disables_quick_login(tmp_path):
  # APP_MODE=demo、DEMO_MODE=0、LAN_MODE=1
  assert report['config']['lan_mode'] is True and report['config']['demo_mode'] is False
  assert report['demo_status']==403
  assert report['password_login_status']==200

def test_lan_mode_with_quick_login_refuses_to_start(tmp_path):
  # DEMO_MODE=1、LAN_MODE=1 → 程序非 0 結束且 stderr 含 'LAN mode forbids quick login'
```

- [ ] **Step 2：執行測試確認失敗**

Run: `.venv\Scripts\python.exe -m pytest tests/test_lan_mode.py -q`
Expected: FAIL

- [ ] **Step 3：實作 config、auth、start.ps1**

- [ ] **Step 4：執行測試確認通過，並跑完整 pytest**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 全部 PASS，0 skipped

- [ ] **Step 5：手動驗證**

Run: `.\start.ps1 -Demo -Lan`
Expected：終端機印出區網網址、帳密來源與防火牆指令；`http://127.0.0.1:8080` 登入頁沒有快速登入按鈕，帳號密碼可登入。手機連線需要使用者自己執行防火牆指令，這一步回報為「待使用者實測」。

- [ ] **Step 6：Commit**

```bash
git add backend/config.py backend/auth.py start.ps1 tests/test_lan_mode.py
git commit -m "Add opt-in LAN mode that disables passwordless demo login"
```

### Task 7：OCR 評估報告與 README

**Files:**
- Create: `scripts/evaluate_ocr.py`、`artifacts/ocr-eval-report.json`
- Modify: `README.md`

**Interfaces:**
- Consumes：`render_nameplate`、`VARIANTS`、`recognize`、`match_machine_ids`、`decide`、`engine_info`。
- Produces：`artifacts/ocr-eval-report.json` = `{'dataset': 'synthetic nameplates generated by scripts/generate_nameplates.py', 'is_synthetic': True, 'engine': {...}, 'generated_at': str, 'samples_per_variant': 18, 'by_variant': {variant: {'top1_accuracy': float, 'auto_open_rate': float, 'wrong_auto_open': int, 'median_ms': float}}, 'overall': {...同欄位}}`。`wrong_auto_open` 是「自動開啟但機台錯誤」的次數，這是最不能發生的錯誤。

- [ ] **Step 1：實作並執行評估**

Run: `.venv\Scripts\python.exe scripts/evaluate_ocr.py`
Expected：產生報告；`clean` 的 `top1_accuracy` 為 1.0、所有變化版本的 `wrong_auto_open` 為 0。若不符合，回到 Task 1 調整比對或前處理，並把實際數字誠實寫進報告，不得調整資料去迎合結果。

- [ ] **Step 2：更新 README**

新增：機台銘牌掃描的流程與截圖位置說明、OCR 評估數字（註明合成資料）、`scripts/seed_machine_history.py` 的使用時機、區網模式啟動步驟與防火牆指令、驗證方式（開哪個頁面、操作什麼、看到什麼），以及面試說法（目前以網頁展示是因為 demo；之後可用 Capacitor 或原生 App 接同一套 API，整合工業平板掃描器、MDM 與離線快取）。技術表格補上 OCR 引擎。

- [ ] **Step 3：跑完整 pytest 與 `check_test_report`**

Run: `.venv\Scripts\python.exe -m pytest -q --junitxml=.runtime/tests.xml` 然後 `.venv\Scripts\python.exe scripts/check_test_report.py .runtime/tests.xml`
Expected：全部 PASS、0 skipped，報告檢查通過

- [ ] **Step 4：Commit**

```bash
git add scripts/evaluate_ocr.py artifacts/ocr-eval-report.json README.md
git commit -m "Add synthetic OCR evaluation report and document machine scan"
```
