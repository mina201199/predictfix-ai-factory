# 本機 Gemma RAG 展示啟動方式

目前這台電腦已驗證 Gemma 4 E2B Q8_0 可用 CPU 執行模型選段。展示網站為 `http://127.0.0.1:18962/knowledge.html`，模型服務為 `http://127.0.0.1:18964`，使用既有隔離資料庫。模型檔與 Python 位於旁邊的 `predictfix-ai-factory`，網站程式則從 `predictfix-wave2-main` 執行。

2026-10-21 第一次 AI 中心查詢為 10.47 秒，同題重跑約 3.3–3.5 秒；快取可能加速重跑，現場預留 15 秒。這不是多人負載基準。完整結果見 [本次模型實跑證據](../artifacts/interview-gemma-live-20261021/README.md)。

## 啟動前

本輪交付時兩個服務已啟動，先直接開網站，不要重複執行下列啟動指令。電腦或終端機重開後才需要重新啟動；若埠已被使用，先確認既有服務，不關閉不明程序。

使用兩個專用 PowerShell 終端機。兩者都先設定：

```powershell
Set-Location -LiteralPath 'C:\Users\User\Desktop\ai factory\predictfix-wave2-main'
$python = (Resolve-Path '../predictfix-ai-factory/.venv/Scripts/python.exe').Path
$demoDir = Join-Path $PWD '.runtime/interview-20261021'
```

## 第一個終端機 啟動模型

```powershell
$server = (Resolve-Path '../predictfix-ai-factory/.runtime/llama/llama-server.exe').Path
$modelFile = (Resolve-Path '../predictfix-ai-factory/.runtime/models/gemma-4-E2B-it-Q8_0.gguf').Path
$expectedHash = '996d08777aadc6bfd3c7375ef70ba25a0f55240075860754fdb18d6d860aa63a'
if ((Get-FileHash -LiteralPath $modelFile -Algorithm SHA256).Hash -ne $expectedHash) {
  throw '模型雜湊與已驗證版本不同，請先確認檔案'
}
& $server -m $modelFile --alias gemma-4-E2B-it-Q8_0 --host 127.0.0.1 --port 18964 -c 8192 -t 12 -np 1 -ngl 0 --reasoning off --reasoning-budget 0
```

看到 `model loaded` 與 `listening on http://127.0.0.1:18964` 後，在第二個終端機確認：

```powershell
Invoke-RestMethod 'http://127.0.0.1:18964/health'
(Invoke-RestMethod 'http://127.0.0.1:18964/v1/models').data | Select-Object id
```

預期 `status: ok` 與 `gemma-4-E2B-it-Q8_0`。本次設定為 CPU、12 執行緒、單一 slot、context 8192；不同於舊 44 題基準的 context 2048，兩者速度不直接視為同條件比較。

## 第二個終端機 啟動展示網站

若上一輪純檢索的展示網站仍在執行，先在其原終端機按 Ctrl+C，再使用同一個隔離資料庫重新啟動。

```powershell
if (-not (Test-Path -LiteralPath "$demoDir/.env")) { throw '找不到展示環境設定' }
if (-not (Test-Path -LiteralPath "$demoDir/demo.db")) { throw '找不到隔離展示資料庫' }
$env:APP_MODE = 'demo'
$env:DEMO_MODE = '1'
$env:DATABASE_URL = 'sqlite:///' + (Join-Path $demoDir 'demo.db').Replace('\', '/')
$env:INTEGRATION_SOURCES = $null
$env:BOOTSTRAP_PASSWORD = $null
$env:OPENAI_ENABLED = '0'
$env:LLM_PROVIDER = 'llamacpp'
$env:LOCAL_LLM_MODEL = 'gemma-4-E2B-it-Q8_0'
$env:LLM_URL = 'http://127.0.0.1:18964'
$env:OLLAMA_MODEL = ''
$env:COOKIE_SECURE = '0'
$env:LAN_MODE = '0'
& $python scripts/integration_run.py --env-file "$demoDir/.env" serve --port 18962
```

出勤與未完成工單仍依 [展示準備工具](interview-demo.md) 的第二終端機章節操作；網站執行中請另開終端機跑準備工具。它使用 `use_llm=False` 建立展示資料，不代表現場 AI 中心也停用模型。

## 現場實際操作

1. 開 `http://127.0.0.1:18962/knowledge.html`，以主管登入，停在「排查助手」。
2. 問題填「特定刀位換刀卡住，應先核對哪些資料？」；機型選 `PF-INTERVIEW-DEMO`，零件填「換刀」。保留「納入虛構示範資料」與「由 AI 選取相關原文」兩個勾選。
3. 點「查找維修依據」。等待時說明先檢索、再由模型選段、後端帶出原文的過程。
4. 應看到「AI 原文整理」、有 `[S1]` 等引用的原文，以及「本機模型已執行 · gemma-4-E2B-it-Q8_0 · … ms」。向下捲動到「來源與證據」，展開對應的手冊或案例，核對版本、機型和原文。
5. 本輪同題選到 `S1:P1`、`S2:P1`、`S3:P1`；來源順序可能隨案例變動，現場依當次編號核對，不背固定順位。不要將引用存在說成診斷正確率。
6. 切回 `workflow.html`，直接選已準備的工單演示驗收及主管審核，不再重複查詢一次模型。

工作台的「本機 AI 已執行」可證明呼叫狀態，但主要呈現候選清單；AI 中心同時呈現選出的原文及耗時，更適合面試展示。

如果顯示「候選來源 · 未取得有效 AI 整理」或「未使用有效模型結果」，就不是本次要求的成功狀態。保留畫面，檢查模型健康狀態；若現場超過 15 秒，先說明仍在處理並切到流程，完成後再回來看結果，不要重複連點。程式的 HTTP timeout 是 75 秒，15 秒只是講稿的切換門檻。

結束後在網站與模型各自的終端機按 Ctrl+C。這些設定只用於 localhost 的合成資料展示，沒有改動正式上線設定，也不會呼叫 OpenAI。
