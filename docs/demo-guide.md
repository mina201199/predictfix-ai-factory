# 展示操作指南

## 直接開啟公開展示

**[開啟公開展示](https://predictfix-mobile-demo.ruru0109lee.chatgpt.site)**，不需登入、安裝程式或準備 API Key。首頁包含約一分鐘實機影片、中文逐字稿、三分鐘操作指南與常見問題。也可以 [直接觀看 MP4](https://predictfix-mobile-demo.ruru0109lee.chatgpt.site/media/predictfix-demo.mp4)。

1. 先播放影片，了解「來源 → 派工 → 復測 → 審核 → 案例」。
2. 按「開始互動展示」，以主管身分開啟換刀情境。核對來源原文、勾選確認，再核准清單。
3. 指派陳怡安，觀察另兩位工程師因資格或出勤不符而無法派工；切換為被指派的工程師。
4. 按「填入示範排查紀錄」，把任一驗收改為「失敗」並嘗試提交，確認阻擋；改回「通過」再提交。
5. 切換為主管，核對結果並結案；確認案例內容與來源後發布，再查看案例。

隨時點「面試導覽」返回說明。再次開始會接續未完成工單；頁尾「重設展示」經確認後恢復初始資料。操作紀錄只留在當前瀏覽器，不跨裝置同步。影片約 13 MB；首次載入請視網路等候，若無聲請開啟播放器音量。

影片是本機後端應用的實際操作錄影；公開互動版是固定虛構情境，檢查在瀏覽器執行，不連接正式資料庫、現場設備或即時 AI。角色切換只是體驗功能。兩者介面、人名與驗收數值可能不同。正式後端仍須本機啟動。

可直接分享的簡介文字：

> PredictFix AI 維修流程展示：免登入觀看一分鐘實機影片，並依三分鐘導覽體驗來源核對、資格派工、復測驗收與案例發布。所有資料均為虛構。
>
> https://predictfix-mobile-demo.ruru0109lee.chatgpt.site

公開展示版本與檢查結果見 [2026-10-21 對外交付紀錄](showcase-delivery-20261021.md)。

## 本機 Gemma 與維修助手展示

**本機 AI 展示使用實際 Gemma 呼叫。** 請先依 [本機 Gemma RAG 啟動方式](gemma-live-validation.md) 啟動模型與網站。下方原有「不呼叫模型」的啟動指令保留作為純流程備案；不要在準備展示 RAG 時套用該組停用模型的環境變數。既有隔離資料準備與維修操作仍適用。

## 本次固定展示版本與準備（2026-10-21）

目前這台電腦使用 `C:\Users\User\Desktop\ai factory\predictfix-wave2-main`，分支 `codex/interview-readiness`，基底為 `2c9e38f`。資料夾名稱雖有 main，分支已是本次展示準備分支；`predictfix-ai-factory` 是另一個評估分支，不用來展示新增的圖譜與介接功能。這裡修改尚未代表已推送或合併。

展示採本機 HTTP，API 用 **18962**，模擬接收端用 **18963**；不使用既有 8081 模型或其他埠的服務。資料、測試用 `.env`、日誌放在 `.runtime/interview-20261021/`，不寫正式資料庫。這是一個**不呼叫模型的流程展示**：一般來源查找使用現有檢索，不能把規則結果說成當場由 Gemma 生成。CPU/GPU 成績見 [本機模型基準](local-llm-benchmark.md)；如要現場展示模型，需另確認模型檔與服務可用。

### 目前電腦：啟動已準備的資料

開一個專門給展示的 PowerShell，執行下列指令。埠被占用時應停止並確認，不關閉不明程序。

```powershell
Set-Location -LiteralPath 'C:\Users\User\Desktop\ai factory\predictfix-wave2-main'
$python = (Resolve-Path '../predictfix-ai-factory/.venv/Scripts/python.exe').Path
$demoDir = Join-Path $PWD '.runtime/interview-20261021'
if (-not (Test-Path -LiteralPath "$demoDir/.env")) { throw '先完成下方新環境準備步驟' }
if (-not (Test-Path -LiteralPath "$demoDir/demo.db")) { throw '找不到隔離展示資料庫' }
$env:APP_MODE = 'demo'
$env:DEMO_MODE = '1'
$env:DATABASE_URL = 'sqlite:///' + (Join-Path $demoDir 'demo.db').Replace('\', '/')
$env:INTEGRATION_SOURCES = $null
$env:BOOTSTRAP_PASSWORD = $null
$env:OPENAI_ENABLED = '0'
$env:LLM_PROVIDER = 'ollama'
$env:LOCAL_LLM_MODEL = ''
$env:OLLAMA_MODEL = ''
$env:OLLAMA_URL = 'http://127.0.0.1:9'
$env:COOKIE_SECURE = '0'
$env:LAN_MODE = '0'
& $python scripts/integration_run.py --env-file "$demoDir/.env" serve --port 18962
```

開啟 <http://127.0.0.1:18962/workflow.html>。快速登入主管與示範工程師僅用於 localhost 合成資料展示；不要將這個設定改為對外開放。停止時在這個終端機按 Ctrl+C，關閉終端機即可丟棄本次環境變數。

### 新環境或需要另一份乾淨展示資料

原始程式可用 `setup.ps1` 安裝相依，但本輪使用既有虛擬環境，沒有重新安裝。若移到別台電腦，先確認 Python 環境並把 `$python` 改成該專案 `.venv/Scripts/python.exe`；模型權重不包含於 Git。

以下在服務尚未啟動時執行。新資料夾必須不存在，不覆寫既有 `.env` 或資料庫。完成後把三個終端機的 `$demoDir` 都改成這個新路徑。

```powershell
$demoDir = Join-Path $PWD ('.runtime/interview-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (Test-Path -LiteralPath $demoDir) { throw '展示資料夾已存在，請使用新路徑' }
New-Item -ItemType Directory -Path $demoDir | Out-Null
& $python scripts/evaluate_knowledge_graph.py --demo-db "$demoDir/demo.db" --output "$demoDir/graph-evaluation.json"
if ($LASTEXITCODE -ne 0) { throw '圖譜準備失敗，請先查看輸出' }
@'
import json, secrets, sys
from pathlib import Path
folder = Path(sys.argv[1]).resolve()
source = {'mes-demo': {'keys': {'v1': secrets.token_urlsafe(48)}, 'outboundKeyId': 'v1',
  'outboundUrl': 'http://127.0.0.1:18963/events', 'allowHttp': True}}
settings = {'APP_MODE': 'demo', 'DEMO_MODE': '1',
  'DATABASE_URL': 'sqlite:///' + (folder / 'demo.db').as_posix(),
  'BOOTSTRAP_PASSWORD': secrets.token_urlsafe(32), 'INTEGRATION_SOURCES': json.dumps(source)}
with (folder / '.env').open('x', encoding='utf-8') as file:
  file.write(''.join(key + '=' + value + '\n' for key, value in settings.items()))
print('Created isolated demo settings; no secrets printed.')
'@ | & $python - $demoDir
```

`.runtime/` 和 `.env` 均由 `.gitignore` 排除。圖譜建立器先建立合成 fixture 帳號；此處隨機初始密碼不會重設已存在帳號，展示一律使用快速登入。

### 第二個終端機：更新當日出勤與示範工單

先設定相同的專案路徑與 `$python`，再執行：

```powershell
@'
import json
import httpx
from scripts.prepare_interview_demo import prepare
with httpx.Client(base_url='http://127.0.0.1:18962', timeout=30, trust_env=False) as client:
  result = prepare(client)
print(json.dumps(result, ensure_ascii=False))
'@ | & $python -
```

預期 `ready_for_dispatch: true`、`procedure_present: true`，並顯示當次 `ticket_id`。這個方式不覆寫 Git 內的舊展示報告。

初始化工具只接受本機、且必須明確開啟展示模式。建立 `DEMO-INTERVIEW` 設備、虛構手冊、專用 `interview_demo` 工程師、當日出勤、資格、30 分鐘估時、已核准且已派工的排查／驗收清單、到期保養計畫及五個示範備品。專用工程師透過展示登入使用，不輸出或保存其隨機密碼；正式環境沒有快速登入。

重跑會沿用未完成的示範工單；完成後重跑才建立新的一張。不清空既有資料，不重新入庫或重複建立保養計畫，不改動原有工程師的任務。已存在但身分不符的保留帳號、專用工程師的無關未估工單會使工具停止，避免覆寫。

出勤仍有時間範圍；開始展示前重跑準備工具，重新確認目前班次與容量。保養計畫保留原到期日，過期時可展示「逾期」提醒。

## 2–3 分鐘操作流程

入口：<http://127.0.0.1:18962/workflow.html>。這是本機網址。

| 時間 | 操作 | 重點 |
|---|---|---|
| 0:00–0:30 | 主管登入，選示範設備，描述「特定刀位換刀卡住」，查找來源；故意少填一個條件。 | 補問來自必要欄位；引用能核對機型與原文，AI 不判定復機。 |
| 0:30–1:00 | 在「執行與驗收」選 `INTERVIEW DEMO` 工單，打開清單引用與推薦原因。 | 主管核准來源，工程師要有資格、出勤與剩餘容量。此工單已預先準備。 |
| 1:00–1:45 | 登出，再點「以面試示範工程師體驗」；逐項記錄，把驗收填未通過，嘗試提交，再補完成復測。 | 提交由後端阻擋；記錄的是虛構測試條件與結果。 |
| 1:45–2:30 | 切回主管，在工單工作台核對量測／紀錄並審核；到 AI 中心建立案例草稿。 | 審核可退回；案例需補齊並人工核對後發布，才能被下一次檢索。 |
| 2:30–3:00 | 展示保養、備品清單，再開安全報告。 | 日常功能、冪等與權限同樣有驗證；45 個安全情境不是安全認證。 |

切換角色要先登出，不共用主管身分執行工程師操作。最後一步發布案例如超出時間，可先展示已完成的自動操作結果，現場走到主管審核即可。

## 完整流程自動驗證

在上述第二個終端機，把 Python 呼叫改成 `prepare(client, complete=True)` 即可執行完整 API 流程。只用這份隔離資料庫；完成後再執行一次 `prepare(client)`，留下新工單供現場操作。

此函式真的執行驗收失敗阻擋、重新復測、提交、主管審核、案例發布及檢索；會完成目前那張示範工單。舊 CLI `prepare_interview_demo.py --walkthrough` 仍可用，但會覆寫舊報告，本輪採上述函式呼叫並另存結果。新證據見 [本輪證據目錄](../artifacts/validation-20261021/README.md)；[舊完整流程報告](../artifacts/validation-walkthrough-report.json) 與 [舊準備報告](../artifacts/validation-demo-report.json) 保留歷史內容。

這些是 API 操作證據；操作過程另見 [60 秒操作影片](media/predictfix-demo.mp4)。本機地址只供目前電腦使用；外部觀看者請使用上方公開展示網址。公開網站不代表 FastAPI 後端已完成公網部署。

## 圖譜加演：來源有效性與權限（約 2 分鐘）

開 <http://127.0.0.1:18962/graph.html>，以主管登入。機型填 `KG-SYNTH-M1`、起點填 `DEMO-E17`，選「字詞＋圖譜」應有 4 條路徑，包含 `FILTER-A` 與 `LOTO`；純字詞模式沒有圖譜路徑。展開引用，說明來源版本與逐字引文。

在候選區找 `壓差確認 → 需要備品 → FILTER-A`，填寫合成演練理由後撤回；再查剩 3 條。重新核准恢復 4 條。登出再以工程師登入：能查詢，不能管理候選。這是獨立圖譜入口，沒有呼叫模型，也沒有自動判定故障原因或庫存適用性。

## 介接加演：重送與回寫（約 2–3 分鐘）

主管開 <http://127.0.0.1:18962/integrations.html>，建立來源 `mes-demo`、外部機台 `SIM-CNC-01`、內部設備 `DEMO-INTERVIEW` 的對照。本輪資料已準備這個對照，新環境需先完成維修工單準備。

在第二個終端機設定同一 `$demoDir`。為避免其他環境設定蓋過這份 `.env`，只在這個展示終端機清除相關值：

```powershell
$demoDir = Join-Path $PWD '.runtime/interview-20261021'
foreach ($name in @('DATABASE_URL', 'INTEGRATION_SOURCES', 'BOOTSTRAP_PASSWORD', 'APP_MODE', 'DEMO_MODE')) {
  [Environment]::SetEnvironmentVariable($name, $null, 'Process')
}
$runId = [guid]::NewGuid().ToString('N')
& $python scripts/integration_run.py --env-file "$demoDir/.env" simulator send --target http://127.0.0.1:18962 --source mes-demo --scenario replay --external-id "DEMO-$runId" --event-id "EVT-$runId"
```

預期兩筆 HTTP 200、相同 `ticketId`，管理頁只有一張對應工單。每次演練使用新 `$runId`，不要跨次重用事件 ID 卻改動內容。可另以 `--scenario bad-signature`、新的 ID 展示 401；以 `--scenario unknown`、新的 ID 展示 pending，待主管建立對照後再解析。

第三個專用終端機先設定相同專案路徑、`$python`、`$demoDir`，並同樣清除上列五個環境值，啟動接收器：

```powershell
& $python scripts/integration_run.py --env-file "$demoDir/.env" simulator receiver --source mes-demo --port 18963 --db "$demoDir/receiver.db" --fail-first 1
```

回第二個終端機執行一次 worker：

```powershell
& $python scripts/integration_run.py --env-file "$demoDir/.env" worker --once
```

新事件第一次會收到 503，管理頁顯示 pending、attempts=1、`http_status_503`；等待至少 11 秒，再執行同一指令，應變成 sent、attempts=2。`--once` 每次只處理一筆，若先前有待送事件，要依管理頁順序處理至本次事件。資料庫保存重試紀錄，接收器不會因重啟就把相同事件當新事件。

停止 API 與接收器各自用 Ctrl+C。`--once` worker 自行退出。不要關閉其他專案服務，不要刪除資料庫來重跑；需要乾淨狀態時建立新資料夾。

## 展示前測試與 CI 邊界

[GitHub Actions](../.github/workflows/ci.yml) 分成完整測試、容器與 PostgreSQL 三個 job：

- 測試 job 安裝固定套件、檢查依賴、跑全套 pytest，解析 JUnit，要求確實執行測試且零失敗、零錯誤、零跳過。
- 容器 job 建置 Dockerfile，再分別啟動正式及展示模式，檢查頁面／JS／CSS、嚴格 CSP、匿名 API 阻擋及手機展示資產。正式模式的 API 文件與手機展示回傳 404。
- PostgreSQL job 執行並發派工、正式模式、維修流程情境，以及 Compose 重啟與備份還原。未涵蓋 TLS，新增圖譜／外部工單的 PostgreSQL 路徑也尚未驗收。

本機可先跑：

```powershell
$testDir = Join-Path $PWD ('.runtime/interview-tests-' + [guid]::NewGuid().ToString('N'))
& $python -m pytest --confcutdir=. --rootdir=. tests tools/demo-video/tests -q -p no:cacheprovider --basetemp=$testDir --junitxml=.runtime/interview-tests.xml
if ($LASTEXITCODE -ne 0) { throw '測試有失敗，請保留輸出並先處理' }
& $python scripts/check_test_report.py .runtime/interview-tests.xml
```

歷史主線已有 GitHub Actions 成功紀錄；本次整合應核對推送提交的實際結果，見 [2026-10-20 交付驗證](release-validation-20261020.md)。

## 歷史環境紀錄（2026-10-07）

以下保留 2026-10-07 當時的環境紀錄，不代表目前 Docker 或 PostgreSQL 狀態。當時本機兩模式已恢復，SQLAlchemy 使用官方支援的純 Python 安裝，未修改 Windows 安全政策；Dockerfile 已補齊維修流程資產，兩份 Compose 設定通過語法與環境代入檢查，但當時本機 Docker 引擎無法連線。

2026-10-07 已新建 Python 3.12 環境，重新安裝固定依賴，全套 38 項測試通過、零跳過；再以該環境啟動隔離正式模式，頁面資產、API 文件與匿名存取阻擋通過。這是在目前工作目錄進行，尚未驗證另一台電腦或乾淨 Git checkout。完整狀態見 [交付檢查報告](../artifacts/validation-readiness-report.json)。

上述 2026-10-07 紀錄中的 Docker socket 阻擋屬歷史環境狀態，不能用來判斷目前 CI 或其他電腦的引擎狀態。

後續 Docker／PostgreSQL 已有驗證與修正，見 [2026-10-20 稽核](../artifacts/system-audit-20261020/README.md)。2026-10-21 本機演練結果見 [驗證證據](../artifacts/validation-20261021/README.md)；手機／企業網路與現場成效仍待處理。正式部署與現場項目不在本輪範圍內。

後續還需：驗證 HTTPS、圖譜／外部工單的 PostgreSQL 路徑，選定公開後端展示環境與網域，加入監控和異地備份演練。真實感測器、現場診斷與成效評估是另一階段。
