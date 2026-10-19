# 機台銘牌掃描總覽與 PostgreSQL 上線：設計文件

日期：2026-10-16
狀態：待確認

## 1. 目的與背景

PredictFix 是面試與展示用的作品。這次有兩件獨立的工作，依序進行：

- **A. PostgreSQL 上線驗證**：README 目前寫著「Compose 的 PostgreSQL 尚未實測」，要把這個缺口補起來。
- **B. 機台銘牌掃描總覽**：補強作品中「AI 影像」這一塊，展示 OCR 能力，並把專案中分散的資料用機台編號串起來。

情境設定：維修人員或主管站在機台前，用手機或 Getac 工業平板拍下機台銘牌，系統用 OCR 讀出機台編號，接著顯示這台機台的完整資訊與 AI 建議。工廠有內部 Wi-Fi，但**不能連外網**，因此所有功能都必須能離線運作。

主要目的是在面試時呈現 AI 影像能力，並且要求完成度高，不是真的導入工廠現場。

## 2. 目標、非目標、反目標

### 目標

- A：API 實際連上 PostgreSQL 17 運作，並通過既有的情境驗證。
- B：展示時能完整走完「拍照 → OCR 辨識編號 → 機台總覽 → AI 摘要與建議」，每一步都要穩定成功。
- B：機台總覽涵蓋的資訊面向要廣（見 5.4 節）。

### 非目標（這次不做）

- 拍照判斷機台異常：排在第二階段。
- 原生 App、PWA、QR code 標籤。
- HTTPS 或 Caddy `tls internal`：拍照改用檔案輸入（見 5.2 節），不需要 HTTPS。
- Alembic：繼續沿用現有的 `create_all` 加 `schema_versions`。
- 正式部署到公網，或串接真實的感測器。

### 反目標（即使功能能動，發生這些情況也算失敗）

- 展示時 OCR 辨識失敗，流程就卡住、走不下去。
- AI 建議沒有附上依據來源。
- 必須連外網才能運作，包括在執行時才去下載 OCR 模型。
- 把模擬資料說成真實的工廠資料。

## 3. 限制

- 技術沿用現有架構：Python 3.12、FastAPI、Pydantic、SQLAlchemy；前端是原生 HTML/CSS/JS，不使用框架。
- `backend/app.py` 設有嚴格的 CSP（`script-src 'self'`），新頁面不能有 inline script 或 inline style，也不能使用外部 CDN。
- 新的前端檔案要加進 `backend/app.py` 的 `STATIC` 清單。Dockerfile 用萬用字元複製檔案，不需要修改。
- CI 會拒絕「零測試」或「有測試被跳過」的結果，所以 OCR 套件必須能在 CI 安裝，相關測試不能用 skip。
- 程式風格跟著周圍既有檔案走；註解用正體中文，只說明「為什麼這樣寫」。
- API key 和密碼不可以寫進程式碼。

## 4. Part A：PostgreSQL 上線驗證

### 現況

- 主程式都透過 SQLAlchemy ORM 存取資料庫，`DATABASE_URL` 已支援 `postgresql+psycopg`，預期不相容的地方不多。
- 已知只支援 SQLite 的地方：
  - `scripts/backup_database.py`：使用 `sqlite3` 和 `PRAGMA integrity_check`。
  - `backend/openai_runtime.py`：本機的 OpenAI 預算與向量快取使用獨立的 sqlite 檔案，不屬於主資料庫，**維持原狀**。
- 所有 pytest 都使用隔離的 SQLite。
- `tests/*_scenario.py` 是端對端情境腳本，其中 `dispatch_concurrency_scenario.py` 用來驗證並發派工，而 README 寫著 PostgreSQL 的並發路徑尚未驗收。

### 要做的事

情境腳本是在程式內用 `TestClient(app)` 執行的，不是 HTTP client，而且要求正式模式、空的資料庫和 `BOOTSTRAP_PASSWORD`。因此驗證拆成兩層（我的判斷）：

1. **程式內驗證**：新增 `scripts/verify_postgres.py`，讓 `DATABASE_URL` 指向一個用完即丟的空 PostgreSQL 資料庫，以正式模式執行既有情境（至少要有並發派工、正式模式、維修流程這三個）。
   - `production_scenario.py` 中直接用 `sqlite3` 開檔案做備份還原的那一段，要改成依資料庫種類分流。
2. **容器驗證**：用 Compose 以正式模式啟動「API 映像＋PostgreSQL」，執行既有的 `scripts/check_container.py --url`，再加上「重啟後資料仍然保存」的檢查。
3. 修正上述過程中發現的不相容問題。
4. **備份與還原**：讓 `backup_database.py` 支援 PostgreSQL。`pg_dump` 一律在 PostgreSQL 17 容器內執行，做法和 `docs/production-setup.md` 一樣，用 `docker compose exec`。原因是本機沒有 `pg_dump`，而 CI runner 的版本可能比 PostgreSQL 17 舊。還要驗證備份能還原到新資料庫。
5. **不放進 pytest**：CI 會拒絕被跳過的測試，而本機不一定有 PostgreSQL，所以 PostgreSQL 驗證獨立成腳本。
6. （我的判斷）在 CI 新增一個 job，用 `postgres:17` service container 執行 `verify_postgres.py`，避免之後又退化。
7. 依實測結果更新 README 中「PostgreSQL 尚未實測」的敘述。

## 5. Part B：機台銘牌掃描總覽

### 5.0 模式（我的判斷）

掃描、總覽和 AI 摘要在 demo 模式和正式模式都可以使用；展示時以 demo 模式為主。

- 正式模式下，機台的 `temp`、`risk`、零件健康度等欄位可能是 `None`，機台編號也不一定是 `CNC-NN` 格式。所以總覽的每個區塊都要能處理缺值，顯示「尚無資料」，比對編號時也不能假設固定格式。
- 新的路由不放進 `DEMO_ONLY_PATHS`。
- 「示範資料」標示只在 demo 模式顯示。
- demo 模式的 `index.html` 和正式模式的 `console.html`，導覽列都要加上「掃描機台」入口。

### 5.1 流程

拍照或選擇圖片 → `POST /api/scan/nameplate` 進行 OCR 並比對機台編號 → 依信心分數決定下一步：

- 高信心：直接開啟總覽。
- 低信心：列出候選機台，讓使用者確認。
- 完全辨識不出來：讓使用者手動輸入。

確認機台後，呼叫 `GET /api/machines/{mid}/overview` 取得總覽資料，再呼叫 `POST /api/machines/{mid}/ai-summary` 取得 AI 摘要與建議。

### 5.2 前端（新頁面 `scan.html`、`scan.js`、`scan.css`）

- 以手機版面為主，在筆電上也要能正常操作。
- 拍照使用 `<input type="file" accept="image/*" capture="environment">`（我的判斷）。手機會直接開啟相機，而且不需要 HTTPS；在筆電上則可以選擇檔案或拖放。
- 提供「範例銘牌」選單，讓展示時不必真的拍照（見 5.6 節）。
- 版面由上到下依序是：
  1. OCR 結果：辨識出的編號、信心分數，以及「修正」按鈕。
  2. 一眼摘要：AI 用三行說明這台機台現在最需要注意的事。
  3. 可收合的分段：現況 → 人員與進行中的工作 → 歷史檢修 → 保養與備品 → 可靠度指標。
  4. 操作按鈕：「建立工單」「問 AI」，連到既有頁面。
- 從現有的導覽列加入「掃描機台」入口。
- 介面需標示「示範資料」，避免被誤認為真實的工廠資料。

### 5.3 OCR（伺服器端）

- 預設引擎是 RapidOCR，也就是 PaddleOCR 模型的 ONNX Runtime 版本，可以用 CPU 離線執行（我的判斷）。實作前要先確認三件事：能在 Python 3.12 安裝、模型可以隨套件或 Docker 映像打包、執行時不會連網下載。任一項做不到就改用 Tesseract，並在文件中寫明原因。
- 版本要固定寫進 `requirements.txt`。
- 上傳的處理方式沿用 `backend/evidence.py`：有大小上限、用 Pillow 驗證圖片、防範 decompression bomb。
- **比對機台編號**：
  - 先正規化文字：轉大寫、去除空白，並在數字位置把 `O` 修正成 `0`、`I`/`l` 修正成 `1`。
  - 用 regex 找出類似編號的字串，再和資料庫中啟用的機台編號比對；比不到時用 `difflib` 做模糊比對。regex 不能寫死 `CNC-NN`，因為正式模式的編號可能是 `MILL-001`、`M01` 這類格式。
  - 信心分數由 OCR 分數和比對相似度組合而成，門檻值由實作者決定。
- 回傳內容：候選清單（機台編號、信心分數、原始文字）、OCR 全文、處理時間。
- 權限：`engineer` 和 `supervisor` 都可以使用。

### 5.4 機台總覽 `GET /api/machines/{mid}/overview`

把現有資料依機台編號整合起來，不建立新的資料表：

| 面向 | 內容 | 資料來源 |
|---|---|---|
| 機台身分 | 編號、名稱、類型、安裝日期、累計工時 | `machines.payload` |
| 即時現況 | 狀態、風險分數、溫度、振動、稼動率 | `machines.payload`（模擬資料） |
| 零件健康 | 健康度、已使用與壽命、上次更換日 | `machines.payload` 的 `parts`、`part_dates` |
| 負責人員 | 負責人、今天是否在班、手上未結的工單數、上次檢核人與檢核日 | `responsible`、`inspector`、`engineer_duties`、`tickets` |
| 正在進行 | 這台機台未結的工單、處理人、狀態、累計工時、最新一筆工作紀錄 | `tickets`、`work_logs` |
| 歷史檢修 | 已結工單的時間軸、問題、處理人、結案說明、照片數、相關的已發布案例 | `tickets`、`ticket_evidence`、`repair_cases` |
| 保養排程 | 這台機台的保養計畫、下次到期日、是否逾期、下次檢核日 | `maintenance_plans`、`next_inspection` |
| 備品庫存 | 用零件名稱比對庫存品項名稱，有比對到的顯示庫存量和安全庫存；比不到就不顯示（我的判斷） | `stock_items` |
| 可靠度指標 | 故障次數、MTBF、MTTR | `tickets` 加上 workflow 中的核准時間 |

- MTTR 以「工單建立」到「主管審核通過結案」的時間計算。結案時間取自 workflow 的 `reviews[].at`，也就是核准那一筆，或是 audit 中 `ticket_completed` 的紀錄。**不要**使用 workflow 的 `approved_at`，那是作業程序核准的時間，不是結案時間。資料太少時顯示「樣本不足」，不要硬算出數字。
- 查詢時要避免 N+1 問題（`store.ticket_dict` 中已經有相關處理可以參考）。

### 5.5 AI 摘要與建議 `POST /api/machines/{mid}/ai-summary`

- 輸入總覽資料，並用 `maintenance_ai.search()` 檢索相關的手冊段落，再用既有的 `maintenance_ai.generate_json()` 呼叫本機模型（預設 llama.cpp）。
- 輸出三行摘要，以及 2 到 4 條建議。每條建議都必須標明依據，可以是零件資料、工單編號或手冊編號。
- 模型無法使用或輸出不合格時，改用規則產生摘要，例如列出快到壽命的零件、逾期的保養、未結的工單，並在畫面上標示「規則產生」。這和專案現有的退回做法一致。

### 5.6 展示素材與評估

- 新增 `scripts/generate_nameplates.py`：用 Pillow 為 18 台模擬機台（`CNC-01` 到 `CNC-18`）各產生一張銘牌圖片。
  - 銘牌上除了機台編號，還有虛構的製造商、型號、序號、電壓等文字，用來展示「從一堆字中找出機台編號」的能力。
  - 另外產生透視變形、模糊、反光、低對比等變化版本，用來做評估。
  - 輸出到 `artifacts/demo-nameplates/`，並附一張可以列印的總表。
- 新增 `scripts/evaluate_ocr.py`：對所有圖片執行 OCR 和比對，輸出 `artifacts/ocr-eval-report.json`，內容包含各種變化版本的準確率和處理時間。報告要註明是合成資料。
- 確認 `scripts/seed_demo_work_orders.py` 灌入的歷史工單足以讓總覽各個面向都有內容；不足的話，擴充灌入的資料，而不是在程式中寫死。

### 5.7 測試

- 單元測試：編號正規化與比對，包含容易混淆的字元、多個候選、完全找不到的情況。
- API 測試：
  - `scan/nameplate`：用產生的銘牌圖片實際執行 OCR，不使用 mock。
  - `overview`：在灌入資料後，確認各面向的內容都正確。
  - `ai-summary`：確認模型無法使用時會退回規則摘要。
  - 權限：確認未登入的請求會被阻擋。
- 全部測試必須通過、零跳過。

### 5.8 區網模式（選用，你決定的）

讓手機或平板可以透過同一個 Wi-Fi，連到筆電上的系統拍照。

- `start.ps1` 新增 `-Lan` 參數。沒有加這個參數時，系統照舊只綁定 `127.0.0.1`，行為完全不變。
- 加上 `-Lan` 時：
  - uvicorn 改綁定 `0.0.0.0`，但 llama.cpp 和 Ollama 仍然只綁定 `127.0.0.1`，不對外開放。
  - 後端透過環境變數得知目前是區網模式，並**關閉** `/api/auth/demo` 免密碼登入。`/api/auth/config` 也要回報這個狀態，讓前端不顯示快速登入按鈕。
  - 區網模式一律用帳號密碼登入。展示帳號的密碼從 `.env` 讀取，不寫進程式碼。實作者要確認 demo 模式現有的帳號能否設定密碼。
  - 啟動時印出手機可以連線的網址，也就是筆電的區網 IP 加上 port。
- **Windows 防火牆**：腳本不會自動修改防火牆，因為那屬於系統安全設定（我的判斷）。腳本只會印出一行指令，由使用者以系統管理員身分自己執行。這條規則只允許「私人網路」連線，而且只開放這一個 port。
- 區網模式使用 HTTP。拍照是透過檔案輸入（`capture`）完成，不需要 HTTPS。
- 測試：區網模式下，`/api/auth/demo` 要被拒絕，`/api/auth/config` 要回報快速登入已關閉。

### 5.9 README

- 新增「機台銘牌掃描」說明、OCR 評估結果、驗證方式，以及區網模式的啟動步驟與防火牆指令。
- 加入面試說法：目前以網頁形式展示，因為這是 demo，重點在驗證 AI 流程；之後可以用 Capacitor 包裝，或另外寫原生 App 接同一套 API，並整合工業平板的掃描器、MDM 派送與離線快取。

## 6. 留給實作者決定

OCR 信心門檻、圖片前處理方式、API 回傳的確切欄位、檔案怎麼切分、介面細節（沿用現有頁面的視覺風格）、銘牌圖片的外觀，以及 CI job 的寫法。
