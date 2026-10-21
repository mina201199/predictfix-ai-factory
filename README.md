# PredictFix AI｜智慧工廠維修 Copilot

> **CNC 換刀卡住了。該先查什麼、派誰處理，以及怎麼確認真的修好了？**

PredictFix AI 將維修知識查找、資格與容量派工、排查驗收及案例累積接成一套可操作的維修管理系統，面向 CNC 工廠的主管與維修工程師。

**[面試回答與證據](docs/interview-readiness.md) · [面試展示步驟](docs/interview-demo.md) · [本機體驗](#快速開始) · [操作手冊](docs/repair-flow.md) · [系統架構](docs/system-architecture.md) · [安全測試](docs/security-testing.md)**

**目前是本機 MVP，尚未完成企業現場驗收。** 2026-10-21 階段交接位於分支 `codex/interview-readiness`（基底 `2c9e38f`），包含面試材料、本機 Gemma RAG、浮動維修 Agent 與操作 Demo。最新接手事項以下方清單為準；[早期交接紀錄](docs/interview-handoff-20261021.md) 與各日期實驗保留當時狀態，不能視為即時服務狀態。

## 組員接手：2026-10-21 階段進度

### 已完成與目前界線

- 七個主要頁面已有浮動「維修助手」，直接以自然語言提供設備、機型與問題，支援接續追問。
- **RAG 白話問答**：依機型篩選有效手冊／案例，以 TF-IDF＋BM25 檢索，再由本機 Gemma 整理建議並附來源；可展開原文核對。知識中心原有查詢仍是模型選段、原文映射，兩個入口的呈現不同。
- **真實串流**：完整的一點建議通過來源 ID 與新增數值檢查後先顯示，再補完整回答與引用；不是逐字動畫。CPU 單次觀察第一點 8.4 秒、完整回答 13.1 秒，尚非冷啟動、多次分位數或多人負載基準。
- **受限操作 Agent**：可準備建立工單與主管派工草稿；使用者按確認後才呼叫既有寫入 API，後端再檢查權限、CSRF、資格、容量及工單狀態。模型沒有任意 API 或程式執行能力，核准清單、復測、結案仍由既有維修流程處理。
- **五個 Demo 按鈕**：三個知識問題、「建立工單」、「主管派工」。派工按鈕只帶入同一段操作中、已確認建立成功的工單編號，不猜測最新一筆工單；沒有工單或建立仍待確認時會提示先完成建立。
- 已有本機 Gemma、瀏覽器截圖、隔離權限／操作／串流測試；[Agent 證據](artifacts/agent-widget-20261021/README.md)、[模型選段證據](artifacts/interview-gemma-live-20261021/README.md)、[維修流程演練](artifacts/interview-browser-20261021/README.md) 可分別查核。來源存在與格式合法不代表建議已經領域專家認可。

### 接手後先重現 Demo

1. 取得 `codex/interview-readiness` 分支，依下方[快速開始](#快速開始)建立 Python 環境。此 checkpoint 不包含 `.env`、資料庫、模型、llama.cpp 執行檔或虛擬環境。
2. 目前這台 Windows 電腦使用網站 `http://127.0.0.1:18962/`、模型 `http://127.0.0.1:18964`；依[本機 Gemma 啟動方式](docs/interview-gemma-live.md)確認服務。該文件的絕對路徑與相鄰資料夾是這台電腦的配置，其他電腦須自行準備模型與調整路徑，不能直接假設存在。
3. 依[展示準備工具](docs/interview-demo.md)執行 `scripts/prepare_interview_demo.py`，準備 `DEMO-INTERVIEW` 設備、`PF-INTERVIEW-DEMO` 機型與 `INTERVIEW DEMO 工程師`。跨日展示要更新當日出勤，並檢查資格與剩餘容量。
4. 以主管登入，重新整理頁面並開啟右下角助手。點知識 Demo，應先看到一點白話建議，再看到引用與可展開原文；可接著追問。
5. 點「建立工單」→核對設備、機型與異常描述→按確認→看到新工單編號。**接著在同一段對話、不要重新整理**，點「主管派工」→核對剛建立的編號與工程師→按確認；到維修流程核對指派結果。取消草稿不應寫入，工程師帳號不應能派工。
6. 最新 Demo 按鈕已驗證建立草稿可顯示及取消、派工規劃正確且規劃前後工單筆數不變；早期自然語言版本已完成實際建立與派工。最新按鈕的完整雙確認瀏覽器演練仍列在下方待辦，勿把不同版本證據混為同一次驗收。

### 尚未完成：面試前優先接手

以下只列待辦，這次 checkpoint 不另行實作。標示「可直接做」表示可用目前程式與合成資料完成；涉及現場結論的部分仍需資料。

| 優先 | 待辦與驗收條件 | 接手入口 | 是否需要提供資料 |
|---|---|---|---|
| P1 | **重排五分鐘講稿並完整計時**：加入白話 RAG、來源核對、建立與派工兩次確認；實際按最新 Demo 按鈕走完，記錄總時長及等待時的說法，模型慢時可切回流程。 | [五分鐘講稿](docs/interview-script-5min.md)、`agent-widget.js`；目前講稿早於最新操作 Demo | 可直接做；若要同步原始投影片，需提供簡報 |
| P1 | **擴充多輪問答與草稿品質評估**：小模型曾重複建議、漏填派工原因；固定 Demo 問句已補明確欄位，尚未證明任意問法穩定。新增追問、缺資料、歧義設備與不支持的參數題，確認會追問或拒答，不會憑空補值。 | `backend/agent.py`、`backend/agent_answers.py`、`tests/test_agent*.py` | 合成題可直接做；真實正確率需去識別手冊、案例及專家標準答案 |
| P1 | **確認語意有來源支持**：目前檢查來源 ID／新增數值；「問欄位但片段未列欄位」僅有限字詞規則，可能誤擋或漏擋。須加入錯誤改寫與來源覆蓋評估，避免把引用合法當成診斷正確。 | `backend/agent_answers.py`、`tests/test_agent_answers.py` | 防護回歸可直接做；維修建議是否安全有效需領域人員核對 |
| P2 | **補效能量測**：分開冷啟動與暖機，記錄首點／完整回覆 p50、p95、硬體與提示詞；再比較提示詞、片段長度或量化設定。現有 8.4／13.1 秒只是單次觀察，不承諾即時回覆。 | `backend/maintenance_ai.py`、[串流證據](artifacts/agent-widget-20261021/README.md) | CPU 量測可直接做；GPU 比較需可用硬體／租用資源及相同題庫 |
| P2 | **整理操作狀態接續**：目前剛建立的工單 ID 只保留在記憶體；重新整理、清除對話或切換登入後須重新指定工單。確認卡不恢復且有五分鐘有效期限。若要跨重整派工，需提供明確選取／後端查核，不可猜最後一張工單。 | `agent-widget.js`、`tests/agent_demo_actions_test.cjs` | 可直接做；面試現階段可依「同一段對話」操作避開 |
| P2 | **全頁與窄螢幕驗收**：檢查舊助手入口是否需整併，實測五個按鈕、來源展開與確認卡在窄螢幕的捲動及鍵盤操作。 | `agent-widget.css`、`agent-widget.js`、`auth.js` | 瀏覽器模擬可直接做；實體手機需裝置 |

### 尚未完成：正式上線前再處理

**本輪不動正式部署及現場介接。** 以下由組員另排工作，不應在面試說成已驗收。

| 待辦 | 驗收方向 | 所需資料／決策 |
|---|---|---|
| 權限細分與企業身分 | 主管的帳號管理、派工與審核是否分權；跨廠資料可讀範圍、SSO 與最小權限 | 企業角色矩陣、廠別與身分系統規格 |
| 真實工單介接 | API／CSV／outbox 已有本機驗證；對真實端點測簽章、欄位對應、去重、重試、失敗補償及稽核 | ERP／MES／工單 API 規格、測試端點與授權方式；密鑰只放環境設定 |
| 知識與圖譜落地 | 來源授權、版本、撤回與專家審核；一般 RAG 尚未串接圖譜，需另做效果比較 | 去識別手冊／故障碼／已結案案例、設備機型對照、領域專家 |
| 模型治理及調參 | 現用 Google Gemma 純 CPU；舊 Qwen 僅歷史實驗。Gemma 504 步 QLoRA 結果尚不採用，沒有 GPU 成本節省結論 | 案場模型政策、授權審查、真實保留題庫、硬體成本與訓練資源 |
| 正式環境驗收 | 重跑最新分支 CI、Docker／PostgreSQL／HTTPS、備份還原、監控、多人負載、企業網路與手機登入 | 部署環境、網路／憑證、容量與可用性需求；既有紀錄不能代替最新驗收 |
| 業務成效 | 定義查資料、派工、維修與結案所需時間，前後對照並保留稽核證據 | 現場基準工時、樣本數、停機成本與實際使用紀錄；目前不填節省比例 |

### 程式入口與驗證

| 檔案 | 接手用途 |
|---|---|
| `auth.js`、`agent-widget.js`、`agent-widget.css` | 全頁載入、Demo 問句、對話串流、人工確認與操作後狀態 |
| `backend/app.py`、`backend/agent.py` | `/api/agent/chat`、JSON／NDJSON 回覆、受限工具規劃；規劃不寫入 |
| `backend/agent_answers.py` | 檢索、白話建議、引用驗證與逐點預覽 |
| `backend/maintenance_ai.py` | llama.cpp／Ollama 呼叫與串流轉接 |
| `tests/test_agent*.py`、`tests/test_local_llm_request.py` | 權限、草稿、引用、斷線取消及模型協定回歸 |
| `tests/agent_demo_actions_test.cjs`、`tests/agent_streaming_ui_test.cjs` | Demo 工單編號／待確認保護、UTF-8 分包與串流失敗情境 |

建立好自己的 `.venv` 後，在 repo 根目錄執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests tools/demo-video/tests -q -p no:cacheprovider --rootdir=. --confcutdir=.
node tests/agent_demo_actions_test.cjs
node tests/agent_streaming_ui_test.cjs
node --check agent-widget.js
git diff --check
```

2026-10-21 本次 checkpoint 完整回歸：**164 passed，0 failed／error／skipped，252.56 秒**，有 1 個既有 Starlette 棄用警告；[JUnit 結果](artifacts/checkpoint-20261021-tests.xml)。Demo 操作前端測試、串流前端 3 個情境、JavaScript 語法與 `git diff --check` 均通過。本機使用相鄰工作目錄的 `.venv` 執行，組員請改用自己的環境。既有分階段結果保留於 `artifacts/`，不相加計算為新測試數。自動測試使用隔離資料與模擬模型，不等於真實工廠或最新完整瀏覽器操作驗收；本次 GitHub CI 尚未確認。

## 目前做到哪裡

| 項目 | 狀態 | 可以如何理解 |
|---|---|---|
| 展示模式 | 已實作並完成本機驗證 | 虛構設備、示範手冊、主管／工程師快速體驗，使用獨立展示資料庫。 |
| 正式資料模式 | 已實作並完成隔離測試與本機檢查 | 從空資料庫建立設備、帳號、出勤、工單與授權手冊；不載入展示資料，不提供快速登入。 |
| 本機運行 | 已恢復並驗證 | SQLAlchemy 改採官方支援的純 Python 安裝，展示及正式資料模式皆通過健康檢查。 |
| 獨立本機部署 | 曾於 8084 驗證，非即時服務狀態 | 檔案雜湊快照、隔離 SQLite、正式登入、重啟及備份還原的歷史紀錄；不是公開網站。 |
| LoRA 小規模訓練 | 已完成並部署獨立實驗 API | Qwen3-0.6B，12 步 CPU 訓練；保留測試 9／12 題符合，資料不足 3 題皆失敗，未替換正式模型。 |
| Gemma QLoRA | 504 步實驗完成，尚不採用 | 新 100 題合成評估完全正確率 42%、recall 50.77%，三段答案 0/20；最新結果來自獨立訓練分支，沒有替換現用 Q8_0 模型。見 [面試證據](docs/interview-readiness.md)。 |
| 外部工單介接 | API／CSV／outbox 已實作 | 本機模擬器及隔離測試已驗證；正式 Compose 已含 worker，尚未對接真實企業端點。 |
| 維修知識圖譜 | 可追溯關係、審查與獨立查詢已實作 | 有合成來源覆蓋評估；一般 AI 查詢尚未直接使用圖譜，未經領域專家及現場成效驗收。 |
| 可重複展示 | 已提供準備工具與展示腳本 | 專用設備、工程師、資格與出勤；驗收阻擋、主管審核、案例發布與檢索已跑通。 |
| CI | 有既有通過紀錄，本輪未重跑 | 設定含完整測試、容器與 PostgreSQL job；現有連結是先前執行紀錄，非本次面試修改的 CI。[歷史執行紀錄](https://github.com/mina201199/predictfix-ai-factory/actions/runs/38715442505)。 |
| Docker／PostgreSQL／HTTPS | 有本機驗證紀錄，正式環境尚待驗收 | 既有 PostgreSQL 備份還原及 2026-10-20 工單介接稽核已留證據；交接另記錄本機 Caddy TLS 驗證，手機與企業網路尚未驗收。本輪不重跑部署。 |
| 公開網站／企業上線 | 尚未完成 | 尚無外部可用網址，未接真實感測器，未完成工廠現場驗收。 |

**目前定位是具備資料保存與權限流程的本機 MVP。** 「正式資料模式」是應用程式的運行模式，不代表已部署到正式伺服器。

## 解決什麼問題

一次維修通常需要跨越三種資訊：手冊裡的排查依據、人員的資格與可用時間，以及工單中的量測和復測結果。這些資料若分散在文件與口頭交接中，就難以回答「為什麼這樣修」和「憑什麼結案」。

本專案把它們接在同一張工單上，交付以下能力：

| 交付物 | 使用者得到什麼 | 驗證依據 |
|---|---|---|
| **有來源的排查依據** | 依機型查找手冊與已發布案例，查看來源版本及原文，交由主管核准清單。 | 有效引用映射、錯誤引用拒絕、撤回資料排除測試；[檢索報告](artifacts/retrieval-eval-report.json)。 |
| **可解釋的工程師推薦** | 根據技能、必要資格、出勤及剩餘容量比較人選，由主管確認派工。 | 資格／出勤阻擋、容量檢查、SQLite 並發派工測試。 |
| **有證據的驗收與案例** | 逐項記錄結果；驗收通過才可提交，主管可退回重修；完成案件可整理成案例。 | 驗收阻擋、提交快照、重修歷程、案例發布與資料保存測試。 |

日常操作另涵蓋設備與帳號建檔、定期保養到期清單、備品入庫／領用／退料、照片與量測、實際工時紀錄。尚未量測節省多少工時或降低多少停機損失。

## Demo：從換刀卡住到留下維修案例

[![操作影片預覽：驗收未通過就提交，後端直接擋下](docs/media/predictfix-preview.gif)](docs/media/predictfix-demo.mp4)

**[▶ 觀看 60 秒完整影片（含中文旁白）](docs/media/predictfix-demo.mp4)**：本機展示模式實機錄影，涵蓋報修補問、核准清單、資格派工、驗收阻擋、主管審核與案例發布。

![實際排查與驗收畫面：來源引用、主管核准清單與必填驗收項目](docs/images/repair-flow.png)

*實際系統截圖；設備、工單與手冊均為虛構展示資料。*

```mermaid
flowchart LR
    A[報修與補問] --> B[比較來源]
    B --> C[核准排查清單]
    C --> D[資格與容量派工]
    D --> E[逐項排查與復測]
    E --> F[主管審核]
    F --> G[發布維修案例]
    F -. 退回重修 .-> E
    G -. 下次維修可檢索 .-> B
```

展示情境：「CNC-03 換刀卡住，只發生在特定刀位」。

1. **補齊條件**：填寫機型、警報、發生條件與已查項目，查看缺少哪些資訊。
2. **核對依據**：比較候選手冊與案例的原文，主管核准排查及驗收清單。
3. **決定派工**：設定必要資格與剩餘估時，查看誰合資格、有出勤且有容量。
4. **執行與復測**：切換被指派的工程師，逐項記錄；驗收未通過時，系統阻擋提交。
5. **審核與累積**：主管核對證據，可退回重修；通過案件整理成案例，人工核對後發布。

展示前執行 `scripts/prepare_interview_demo.py`，即可準備專用工程師、資格、當日出勤與已指派工單。[2–3 分鐘展示腳本](docs/interview-demo.md) 提供操作順序與完整流程驗證方式；完整操作見 [操作手冊](docs/repair-flow.md)。目前補問採結構化欄位檢查；比較的是候選來源，尚未自動產生完整維修方案。

## 機台銘牌掃描 Demo

開啟 `/scan.html`，拍攝或上傳銘牌照片，由離線 OCR 讀出設備編號，再整合現況、零件健康、負責人與出勤、進行中的工作、歷史檢修、保養排程、備品與可靠度指標。未接感測器的數值是展示資料；正式模式缺資料時顯示「尚無資料」。

```mermaid
flowchart LR
    A[拍銘牌或選範例] --> B[離線 OCR]
    B --> C{辨識結果}
    C -->|明確匹配| D[機台總覽]
    C -->|模糊或低信心| E[人工確認或手動輸入]
    E --> D
    D --> F[檢索來源與 AI 建議]
```

OCR 使用 RapidOCR 3.10.0、ONNX Runtime 1.31.0 的 CPU 模型，模型隨套件安裝，執行時不需連外網。信心達 0.85 且候選差距至少 0.10 才自動開啟；模糊比對即使分數高也要確認。模型摘要會附上實際存在的來源編號；模型未啟動、逾時或格式不合格時改為「規則產生」。來源存在不代表建議內容已經過工程師驗證，仍需人工核對。

2026-10-19 的 [OCR 評估報告](artifacts/ocr-eval-report.json) 包含 18 台設備 × 5 種變化，共 90 張**合成銘牌**。乾淨、透視、模糊、反光、低對比版本均為 top-1 100%，自動開錯台 0 次；這不代表真實工廠照片的準確率。可用以下指令重跑：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_ocr.py
```

![機台總覽實際畫面，設備與量測皆為展示資料](docs/images/machine-scan.png)

[手機版畫面](docs/images/machine-scan-mobile.png)。

準備歷史檢修展示資料（只可對 demo 資料庫執行；重跑不重複新增）：

```powershell
$env:APP_MODE='demo'
.\.venv\Scripts\python.exe scripts\seed_machine_history.py
.\start.ps1 -Demo
```

開啟 `http://127.0.0.1:8080/scan.html`，點 CNC-07 範例銘牌，應自動看到機台總覽、負責人、維修中的工作與歷史檢修；展開各區段查看細節。範例也會實際執行 OCR。上傳沒有文字的照片，應聚焦到手動輸入欄；輸入 `cnc-12` 應找到 CNC-12。18 張範例與可列印總表位於 [artifacts/demo-nameplates](artifacts/demo-nameplates/)，頁面截圖可由瀏覽器在總覽顯示後擷取。

目前以手機操作展示。手機與筆電連同一個內網 Wi-Fi，再執行：

```powershell
.\start.ps1 -Demo -Lan
```

終端機會印出 `http://<筆電 IPv4>:8080/scan.html`。區網模式關閉免密碼登入，使用既有帳密；首次建立帳號時可在環境變數或未追蹤的 `.env` 設 `BOOTSTRAP_PASSWORD`，既有帳號不會重設。未設定初始密碼的展示帳號資訊在 `data/initial-accounts.json`（已忽略）。照片由檔案輸入的 `capture` 呼叫相機，實際行為依手機瀏覽器而異；檔案上傳可作備案。此 HTTP 模式適合受信任的展示內網；本機 TLS 曾有交接紀錄，手機與企業 HTTPS 環境仍待驗收。

若 Windows 防火牆擋住連線，由使用者自行以系統管理員執行以下指令；啟動腳本只顯示指令，不會修改防火牆：

```powershell
New-NetFirewallRule -DisplayName "PredictFix LAN demo" -Direction Inbound -Protocol TCP -LocalPort 8080 -Profile Private -Action Allow
```

實體手機的連線與拍攝仍待裝置實測；Getac 工業平板僅列入未來選型評估，不屬於目前展示範圍。瀏覽器測試已覆蓋手機版 375×812 與桌面版、範例辨識、無文字圖片及手動輸入。另以 `node tests/scan_race.cjs` 檢查舊 OCR 回應不會蓋掉使用者後續選擇。

面試說法：「目前以響應式網頁展示，先驗證拍照、離線 OCR、維修資料整合與附來源的 AI 建議。後續可用 Capacitor 包裝成 App，或以原生 App 接同一套 API，再整合工業平板掃描器、MDM 派送與離線快取。」這些 App 能力是後續規劃。

## 用了哪些技術，以及為什麼

| 環節 | 技術選擇 | 設計理由與取捨 |
|---|---|---|
| **前端** | HTML／CSS／JavaScript | 直接呈現角色、工單狀態與來源，讓完整操作流程容易追查；未使用大型前端框架。 |
| **銘牌影像辨識** | RapidOCR、ONNX Runtime、Pillow | 本機 CPU 偵測與辨識文字，比對已建檔機台；低信心交由人確認。模型隨套件安裝，不依賴外部 API。 |
| **API 與資料** | FastAPI、Pydantic、SQLAlchemy；本機 SQLite、部署 PostgreSQL 17 | 驗證輸入、維持一致 API 契約並保存工單；SQLite 降低單機啟動成本，PostgreSQL 已用相同情境實測，高並發負載仍需另行壓測。 |
| **知識檢索** | TF-IDF＋BM25 排名融合 | 支援機型、術語與錯誤碼的字詞檢索；合成題比較三種方法目前同分，尚無證據顯示融合更準。未使用 Embedding 或 Vector DB。 |
| **本機 AI** | Gemma 4 E2B Q8_0（Google，Apache 2.0）、llama.cpp 純 CPU；另支援 Ollama | 知識中心由模型選段；浮動助手以 RAG 整理白話建議、引用與操作草稿。操作須人工確認並通過後端權限檢查，模型不核准復機。模型不可用時明示未取得有效模型結果。不需 GPU，選型依據見 [本機模型基準](docs/local-llm-benchmark.md) 與 [模型選型與合規](docs/model-selection.md)。 |
| **工程師推薦** | 規則篩選與排序 | 必要資格、出勤與容量是可核對的條件；目前沒有可用來訓練推薦模型的現場成效資料。 |
| **一致性與權限** | 工作階段、角色、CSRF、版本檢查、冪等請求 | 限制操作身分，避免重送造成重複工單或扣帳，拒絕過期版本覆寫。 |
| **部署** | Docker Compose、PostgreSQL、Caddy 設定 | 分開配置 API、資料庫、模型與 HTTPS；API＋PostgreSQL 有實測紀錄；本機 TLS 與正式環境驗收的界線見 [面試交接](docs/interview-handoff-20261021.md)。 |

### 模型選型與合規

本機模型使用 Google 的 Gemma 4 E2B Q8_0（Apache 2.0），在本機 CPU 執行；除選配的 OpenAI 整合外，工單與手冊不會送出工廠。原本的 Qwen3-0.6B 已於 2026-10-15 淘汰，原因有二：44 題段落選取基準只選對 22.7%（Gemma 為 100%），以及台灣案場對中國開發模型的合規疑慮。台灣自製備案為聯發創新基地的 Llama-Breeze2-3B（選對 88.6%，注入題較弱）。來源、授權、離線與檢核清單見 [模型選型與合規](docs/model-selection.md)。

## 架構

```mermaid
flowchart TD
    UI[主管／工程師瀏覽器] --> AUTH[登入工作階段・角色・CSRF]
    AUTH --> API[FastAPI]

    API --> FLOW[工單・派工・排查驗收]
    API --> OPS[人員出勤・保養・備品]
    FLOW --> DB[(SQLite)]
    OPS --> DB

    API --> FILTER[機型與有效來源篩選]
    MAN[已授權手冊] --> FILTER
    CASE[主管發布案例] --> FILTER
    FILTER --> RET[TF-IDF + BM25]
    RET --> LLM[本機 Gemma 選取段落 ID]
    LLM --> CHECK[格式檢查・原文映射]
    CHECK --> HUMAN[人員核對・主管核准]
    HUMAN --> FLOW

    FLOW --> REVIEW[提交快照・主管審核]
    REVIEW --> DRAFT[案例草稿・人工發布]
    DRAFT --> CASE
```

後端控制流程與資料修改，模型只提供受限的摘錄建議。來源、清單版本、提交結果與審核紀錄各自保存，以便追查一次維修的判斷依據。

主要模組：

| 路徑 | 責任 |
|---|---|
| [backend/maintenance_ai.py](backend/maintenance_ai.py) | 手冊版本、檢索、段落引用、案例草稿與發布。 |
| [backend/repair_flow.py](backend/repair_flow.py) | 報修補問、核准清單、逐項結果、保養與備品異動。 |
| [backend/workforce.py](backend/workforce.py) | 帳號、資格、出勤、工時、派工容量核對。 |
| [backend/auth.py](backend/auth.py) · [backend/evidence.py](backend/evidence.py) | 登入權限、照片與量測證據。 |
| [tests/](tests) · [scripts/](scripts) | 隔離測試、模型／檢索評估、安全報告與備份工具。 |

完整資料流與介面邊界見 [系統架構](docs/system-architecture.md)。

## 工程亮點

**1. 把 AI 引用交給程式驗證。**

模型只能回傳段落 ID，後端檢查欄位、型別、數量及 ID 是否存在，再從來源取出原文。捏造引用或不合法格式會降級，不把自由生成文字當成維修步驟。來源存在仍不等於診斷正確，主管必須核對適用性。

**2. 推薦與實際派工各檢查一次。**

介面上的推薦可能過期；正式模式派工 API 再核對資格與剩餘容量。SQLite 與 PostgreSQL 的並發指派都已實測，避免兩次操作同時把容量用掉。

**3. 結案是一段可回看的流程。**

附清單的工單必須完成排查與驗收才能提交。提交保存當時的來源與結果快照；退回重修要求重新記錄，前次證據仍保留。既有未附清單工單維持原提交規則。

**4. 用攻擊測試重現並修正資料讀取缺口。**

新增安全測試先重現草稿／撤回資料被工程師讀取、已發布案例暴露原始快照、驗證錯誤回傳密碼等問題，再修正權限與輸出。模型攻擊測試同時核對身分與案例狀態，避免只看回答文字就判定安全。

**5. 日常操作也處理重送與並發。**

保養計畫避免重複生成進行中工單；備品領用在 SQLite 內串行核對並扣帳，相同請求不重複扣庫存。低庫存與保養提醒目前呈現在系統內，未接外部通知或採購。

## 驗證成果與適用邊界

| 驗證項目 | 現有結果 | 能證明什麼／不能證明什麼 |
|---|---|---|
| **功能與整合測試** | 148 項 pytest 通過、零跳過，2026-10-19 本機實跑 | 涵蓋權限、派工、驗收、重修、保養、庫存、備份、持久化、展示、LoRA 分組／評分器、引用截斷、檢索快取與工單分頁；不能代表工廠現場驗收。 |
| **本輪面試回歸** | 161 項 pytest 通過、零失敗／錯誤／跳過，2026-10-21 | 包含 `tests` 與 `tools/demo-video/tests`；增加慢啟動的程序清理測試，沒有重跑 GPU／正式部署。見 [JUnit](artifacts/interview-20261021/tests.xml)。 |
| **重新安裝驗證** | GitHub Actions 從乾淨 Git checkout 安裝固定依賴，通過 60 項測試 | 驗證依賴安裝可在另一台機器重現；CI 為 Ubuntu，尚未驗證 Windows 的 `setup.ps1` 安裝流程。 |
| **AI／API 安全** | 45／45 個檢查通過（2026-10-15，Gemma 4 E2B），其中含 8 個真實本機模型攻擊情境 | 測提示詞注入、越權、敏感資料暴露與捏造引用；是有限情境驗證，未完成全面滲透測試。 |
| **檢索方法比較** | 16 題正例 Top-3 命中 15 題（93.75%）；4 題負例均無結果 | TF-IDF、BM25、融合方法同分；開發用合成題，不是獨立保留集，也不是 AI 回答正確率。 |
| **完整展示流程** | 驗收失敗阻擋、復測提交、主管審核、案例發布及再檢索通過 | [流程報告](artifacts/interview-walkthrough-report.json) 是 API 操作證據；[60 秒操作影片](docs/media/predictfix-demo.mp4)為本機展示模式錄影。 |
| **正式資料模式** | 2026-10-07 本機 API、空資料庫、展示功能隔離與模型連線通過 | [本機驗證報告](artifacts/production-live-check.json)；不等於公網或企業上線。 |

[安全測試說明](docs/security-testing.md) · [逐項安全報告](artifacts/security-test-report.json) · [檢索報告](artifacts/retrieval-eval-report.json)

2026-10-21 面試交付狀態見 [交接清單](docs/interview-handoff-20261021.md)；[舊交付檢查報告](artifacts/interview-readiness-report.json) 保留其原始日期與測試範圍。

## 本機部署與 LoRA 微調實驗

以下自動產生區塊保存歷史 Qwen 實驗；最新 Gemma QLoRA 與現用模型的差異見 [面試回答](docs/interview-readiness.md)，不以本區塊判斷即時服務狀態。

<!-- experiment-results:start -->
**歷史本機部署紀錄：deployed。** 當時在 `http://127.0.0.1:8084` 驗證正式資料模式，採獨立資料庫與具有檔案雜湊的版本快照；不代表該服務現在仍開啟。

已驗證登入與主管權限、匿名阻擋、關閉快速登入、重啟後帳號保存，以及 SQLite 備份／新庫還原與工作階段撤銷。尚未部署公網；Docker 映像已由 CI 以正式模式實際啟動驗證，PostgreSQL 已有重啟保存與 `pg_dump` 還原紀錄。本機 TLS 的後續交接與未驗收範圍見 [面試交接](docs/interview-handoff-20261021.md)；本輪不重跑部署。

**LoRA 任務：根據報修問題與候選原文，選取相關段落 ID；無依據時輸出空清單。** 資料為 44 題原創虛構案例，按來源主題分組，訓練／驗證／測試為 24／8／12 題。

實驗狀態：`completed`；模型：`Qwen/Qwen3-0.6B`；run：`cpu-smoke-v1`。

| 同一組 12 題來源主題保留測試 | 原模型 | LoRA 模型 |
|---|---:|---:|
| 段落集合完全符合 | 0.0% | 75.0% |
| 選取 Precision | 0.0% | 100.0% |
| 選取 Recall | 0.0% | 100.0% |
| 合法輸出 | 0.0% | 75.0% |
| 資料不足判斷 | 0.0% | 0.0% |
| 文件注入題正確選取 | 0.0% | 100.0% |
| 平均生成耗時（CPU） | 9.45 秒 | 5.53 秒 |

CPU float32、LoRA rank 4、q_proj/v_proj、batch 1，共 12 步；僅訓練 573,440 個參數。訓練耗時 187.4 秒。

Exact match 變化：**+75.0 個百分點**。這是小規模流程實驗，不能證明現場維修成效；訓練 loss、逐題原始輸出、版本與雜湊均保存。

本實驗使用 Transformers、無 JSON grammar，嚴格拒絕 Markdown 包住的 JSON；現有 llama.cpp 服務有格式約束，這些數字不等於線上服務正確率。生成耗時也受回答長度影響。

**目前保留原服務模型，未自動替換。** 此 adapter 尚未完成量化部署、安全回歸與專家評估。

**失敗分析：3 題資料不足題未正確拒答。** 例如輸出 `{"selected":[""]}`，包含不存在的段落 ID；仍須由後端拒絕與降級。此結果尚不符合替換現有模型的條件。

**歷史 Qwen adapter 曾在 `http://127.0.0.1:8085` 驗證推論。** 當時重新載入保存權重，驗證同題輸出一致與錯誤輸入拒絕；不代表服務現在仍開啟，也不是最新 Gemma QLoRA 的部署證據。這是獨立實驗 API，尚未接入正式維修流程。詳見 [推論部署報告](artifacts/lora-serving-report.json)。

[實驗方法與重跑](docs/lora-training.md) · [部署報告](artifacts/local-deployment-report.json) · [LoRA 完整報告](artifacts/lora-training-report.json) · [資料集](training/selection-dataset.json)
<!-- experiment-results:end -->

### 另外做的 ML 實驗：公開軸承故障分類

使用 CWRU 12 kHz 實驗資料，抽取 14 個時域／頻域特徵，以決策樹分類滾珠、內圈與外圈故障。依負載切分：0／1 hp 訓練、2 hp 驗證、3 hp 測試。

跨負載測試 Accuracy **66.7%**、Macro-F1 **0.556**，內圈類別 Recall **0**，顯示目前模型的泛化不足。保留混淆矩陣與逐類結果，供後續改進；不將此結果換算成 CNC 健康度或故障風險。

資料沒有正常類別，測試只有 3 個獨立檔案，同檔視窗彼此相關。這是獨立的分類實驗，尚未串成現場預測維護。完整內容見 [模型評估報告](artifacts/model-report.json)。

## 快速開始

在 Windows 專案根目錄執行；原始開發環境為 Python 3.12。

```powershell
.\setup.ps1

# 展示模式：虛構資料與角色快速體驗
.\start.ps1 -Demo -Port 8082

# 或正式資料模式：空資料庫與真實帳號登入
.\start-production.ps1 -Port 8083
```

| 入口 | 用途 |
|---|---|
| http://127.0.0.1:8082/workflow.html | 展示報修、排查驗收、保養與備品。 |
| http://127.0.0.1:8082/knowledge.html | 手冊、案例與維修 Copilot。 |
| http://127.0.0.1:8083/ | 正式資料模式的設備、帳號、出勤與工單工作台。 |
| http://127.0.0.1:8082/docs | 本機 Swagger API 文件，僅展示模式提供；正式模式不公開。 |

**以上都是本機網址，外部訪客無法直接開啟。** 安裝工具使用 SQLAlchemy 純 Python 建置並檢查依賴及 SQLite 讀寫；啟動時也會先檢查環境。

服務啟動後另開終端機，準備面試工單：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_interview_demo.py
```

登入畫面會新增「以面試示範工程師體驗」。重跑沿用未完成的示範工單，不清空既有資料。詳見 [面試展示指南](docs/interview-demo.md)。

本機 LLM 與軸承回放為額外安裝項目：

```powershell
.\.venv\Scripts\python.exe scripts\setup_local_llm.py
.\.venv\Scripts\python.exe scripts\prepare_model.py
```

沒有模型服務時，知識中心仍可顯示候選來源，並標示未執行模型。第一次建檔、登入資訊及套件安裝見 [本機安裝指南](docs/local-setup.md)；備份與部署見 [正式環境手冊](docs/production-setup.md)。

## 重跑測試

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_security_checks.py
# 另測真實本機模型（Gemma 4 E2B），需先啟動 8081 模型服務
.\.venv\Scripts\python.exe scripts\run_security_checks.py --live
```

測試建立隔離 SQLite，不寫入運行中的正式資料庫。

PostgreSQL 另用獨立腳本驗證（不放進 pytest，因為本機不一定有 PostgreSQL，而 CI 拒絕跳過的測試）：

```powershell
# 1. 用完即丟的 PostgreSQL 17，密碼只放在這個終端機的環境變數
$env:PGPASSWORD=[guid]::NewGuid().ToString('N')
docker run --rm -d --name pf-verify-pg -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=$env:PGPASSWORD postgres:17-alpine
# 2. 三個情境各自在新的暫存資料庫執行，結束後刪除
.\.venv\Scripts\python.exe scripts\verify_postgres.py scenarios --admin-url postgresql+psycopg://postgres@127.0.0.1:55432/postgres
docker stop pf-verify-pg
# 3. Compose 正式模式：健康檢查、重啟保存、pg_dump 還原到新資料庫；結束時自動 down -v
.\.venv\Scripts\python.exe scripts\verify_postgres.py container
```

兩個指令最後一行都是 JSON，所有值為 `true` 即通過。pytest 項數、安全情境與模型題數不能直接相加；148 項是 2026-10-19 歷史結果。CI 另解析 JUnit，拒絕零測試或跳過測試的結果。面試前依 [隔離驗證方式](docs/interview-demo.md) 取得當次結果。

## 下一步

| 優先序 | 要補的工作 | 完成判準 |
|---|---|---|
| **1．交付紀錄** | 已完成：GitHub Actions 測試與容器檢查通過，見 [執行紀錄](https://github.com/mina201199/predictfix-ai-factory/actions/runs/38553389662)。 | GitHub 確實跑完測試與容器檢查。 |
| **2．展示影片** | 已完成：[60 秒操作影片](docs/media/predictfix-demo.mp4)涵蓋報修、派工、驗收阻擋、審核與案例發布。 | 面試官能快速看完操作，現場也可重新準備工單。 |
| **3．外部可用** | 實測 Docker／PostgreSQL／HTTPS，建立獨立的公開展示環境。 | 外部可開啟、資料可持久化、重啟與備份還原通過；展示與正式資料隔離。 |
| **4．效果評估** | 建立獨立手冊題集與相關性標註；由領域人員評估引用適用性和流程成效。 | 有獨立測試集、逐題錯誤分析與清楚的成效指標。 |

尚未完成：PLC／感測器接入、現場健康度與剩餘壽命預測、完整 PDF 手冊匯入／OCR、企業 SSO、多租戶隔離、真實 ERP／人事串接及工廠現場驗收。機台銘牌 OCR 已實作並做合成評估，不等於完整 PDF 手冊處理。

## 深入閱讀

| 文件 | 內容 |
|---|---|
| [操作手冊](docs/repair-flow.md) | 報修、清單、派工、驗收、保養與備品。 |
| [面試展示指南](docs/interview-demo.md) | 一鍵準備、2–3 分鐘腳本、流程驗證與 CI 邊界。 |
| [本機部署與 LoRA 實驗](docs/lora-training.md) | 部署快照、資料分組、CPU 訓練、基準比較與適用限制。 |
| [Gemma 固定 SFT 實驗](docs/gemma-sft-protocol.md) · [實測結果](docs/gemma-sft-results-20261019.md) · [重跑與驗證](docs/gemma-sft-running.md) | 官方權重、獨立保留集與 adapter 重載；本次 QLoRA 全部拒答，未達可用的選段改善。 |
| [系統架構](docs/system-architecture.md) | 資料流、API、來源管理與實作邊界。 |
| [安全測試](docs/security-testing.md) | 攻擊情境、發現與修正、重跑方式及限制。 |
| [權限設計與矩陣](docs/access-control.md) | 主管／工程師權限劃分、資料歸屬、職責分離、逐路由權限矩陣與面試問答。 |
| [維修知識圖譜](docs/knowledge-graph.md) | 有來源的候選／核准路徑、主管審查、隔離展示與合成評估。 |
| [本機安裝](docs/local-setup.md) · [正式環境與部署](docs/production-setup.md) | 安裝、帳號、出勤、備份還原及伺服器設定。 |
| [歷史開發紀錄](docs/development-history.md) | 過往實作與驗證紀錄，含已被後續版本更新的內容。 |
| [外部工單介接](docs/ticket-integration.md) · [驗收結果](docs/ticket-integration-validation.md) | API 契約、CSV、主管管理頁面與本機模擬器；尚未串接企業系統。 |

第二波三組整合、實際測試與限制見 [整合驗證紀錄](docs/wave2-integration-validation-20261019.md)。
