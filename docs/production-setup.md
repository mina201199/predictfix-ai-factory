# 正式資料環境與部署

更新：2026-10-06。本版可處理真實設備、帳號、排班、出勤、工單、工時、維修證據、主管審核與授權手冊。這是單一企業的維修管理版本；尚未完成企業現場驗收，也沒有接入 PLC、ERP、人事系統或感測器。

## 本機使用

執行 `./start-production.ps1 -Port 8083`，開啟 <http://127.0.0.1:8083/>。程式只綁定本機，資料庫 `data/factory.db`。首次建立的管理員帳號是 `supervisor`，隨機密碼保存在未納入 Git 的 `data/production-access.json`。首次登入後從「修改密碼」更新密碼，並刪除初始密碼檔。更新密碼會撤銷全部登入工作階段。此檔案是本機明文初始憑證，不是密碼保管庫。

`./start.ps1 -Demo -Port 8082` 使用 `data/predictfix.db` 展示資料庫。兩種模式分開。環境變數 `DATABASE_URL` 可覆寫預設；正式環境會拒絕含展示初始化或快速登入紀錄的資料庫。直接啟動 uvicorn 時，預設是 production；空資料庫的首次啟動必須提供至少 16 字元的 `BOOTSTRAP_PASSWORD`，不會產生展示帳號。既有 supervisor 不會被啟動密碼覆蓋。

系統在目前電腦運行時，關機、休眠或結束程序會中止服務。開機後重新執行啟動腳本即可恢復資料；沒有將桌面電腦設定成全天候伺服器。

## 第一次實際作業

1. 主管新增設備，填寫設備編號、名稱、機型、廠商與序號。没有資料的健康值、溫度、振動與風險為未知。
2. 在「人員與帳號」建立工程師，填技能與內部授權資格。名稱不可重複；指派以目前既有工單的顯示名稱保存，帳號名稱目前不可更改。
3. 在「出勤與派工」建立帶日期的班次，確認是否到班。本機介面輸入時間為台灣時區，API 必須提供時區；支援跨日班次、請假與未到班。同一工程師不可有重疊班次。
4. 建立待指派工單，主管填剩餘維修工時與必要資格，再查詢推薦。確認出勤、技能及需求後由主管派工；系統不會自動承諾到場或核准復機。
5. 工程師開始維修、登錄本次實際工時、提交文字、量測與照片。主管查看證據並審核通過或退回；只有通過案件可建立案例草稿。
6. 在維修 AI 中心匯入已授權 TXT／Markdown 手冊，確認版本與機型。案例由主管補齊條件、原因狀態、處置及驗收後發布。

工程師推薦為可解釋規則：技能符合占 60 分、剩餘容量占 40 分。未到班、缺必要資格、存在未估時案件或容量不足者標示不可派工。非主要專長人員會明確標示需要主管確認，主管仍可在容量及必要資格符合時選擇。正式派工 API 會再次核對，防止介面上的舊推薦直接派出。排班的可維修分鐘可低於總班長，供扣除會議、休息等預留；計算剩餘容量為 `min(本班預留維修分鐘,距離班末分鐘) - 未審核案件剩餘估時`，是容量估計，不是逐時段排程。待主管審核案件保留於未結案筆數，但不占維修估時。實際工時不自動扣除剩餘估時，因為花 60 分鐘不代表原任務只剩 60 分鐘；由主管更新。

正式資料庫不載入內建示範手冊；正式匯入與案例編輯拒絕合成標記，檢索也再排除合成來源。這只能避免已標記的合成資料混入；系統不會辨識人員將假資料誤標成真實的情況。正式環境關閉舊展示聊天、實驗回放和展示前端資產。

## SQLite 備份與還原

```powershell
.\.venv\Scripts\python.exe scripts/backup_database.py backup --source data/factory.db --destination backups/factory-20261006.db
.\.venv\Scripts\python.exe scripts/backup_database.py restore --source backups/factory-20261006.db --destination data/factory-restored.db
```

備份使用 SQLite online backup API，可在服務運作時建立一致快照；檢查完整性與 schema，附 SHA-256 manifest。還原驗證雜湊，只允許新目的檔，絕不覆蓋既有資料庫；還原後清除登入工作階段。備份涵蓋帳號雜湊、工單、照片、工時、文件與案例，應儲存在只有管理員可讀的位置，再另存異地。此腳本沒有加密或自動異地保存；應以企業的備份工具管理。

切換前停止應用程式，先保留原庫備份，設定 `DATABASE_URL=sqlite:///C:/.../factory-restored.db`，再以 `start.ps1 -Port 8083` 啟動（不加 Demo）。登入後檢查工單及照片，不要直接覆蓋原檔。`start-production.ps1` 固定使用 factory.db，恢復到其他檔名時使用 start.ps1。

## 伺服器部署設定

`compose.yaml` 是明確的本機展示設定。正式部署使用獨立檔案 `compose.production.yaml`，以 PostgreSQL、Ollama、Caddy HTTPS 與獨立 volume 運行；数据库及模型服務不對外開 port，只有 HTTPS proxy 暴露。API 以非 root 帳號執行，附 DB readiness、程序重啟及日誌輪替。

先將 `deploy/production.env.example` 複製成未納入 Git 的 `.env.production`，填真實網域、隨機資料庫密碼、正確 URL encoding 的 DATABASE_URL 及初始主管密碼。DNS 指向伺服器；HTTPS 需要外部可達的 80/443 與有效網域。不得把範例值當正式密碼。

```powershell
docker compose --env-file .env.production -f compose.production.yaml up -d --build
docker compose --env-file .env.production -f compose.production.yaml exec ollama ollama pull qwen3:0.6b
docker compose --env-file .env.production -f compose.production.yaml ps
docker compose --env-file .env.production -f compose.production.yaml logs --tail 100 api
```

LLM 尚未下載或不可用時，AI 中心顯示檢索候選來源，不會假稱模型已完成整理。0.6B 模型適合目前段落選取的串接驗證，正式回答能力需以企業問題獨立評估。

PostgreSQL 備份採原生 `pg_dump`；SQLite 腳本不可用於 PostgreSQL。以下先在容器內產生 archive，再複製檔案，避免 Windows PowerShell 重導向 binary 而破壞內容：

```powershell
docker compose --env-file .env.production -f compose.production.yaml exec db pg_dump -U predictfix -d predictfix -Fc -f /tmp/predictfix.dump
docker compose --env-file .env.production -f compose.production.yaml cp db:/tmp/predictfix.dump backups/predictfix.dump
```

還原時建立獨立測試資料庫，將 dump 複製進容器後用 `pg_restore`，驗證資料與照片，再依企業切換程序更換連線。不要對使用中的正式資料庫執行清空還原。正式 PostgreSQL 還原後應清除 login_sessions。

## 驗證與尚未完成項目

`python -m pytest -q` 覆蓋正式環境空資料啟動、弱初始密碼拒絕、展示污染庫拒絕、權限、出勤、重疊排班、負荷和資格阻擋、完整維修流程、工時、密碼重設撤銷登入、真實標記文件檢索、備份還原與重啟持久化。測試資料只在暫存資料庫，不會混入本機正式库。

本機使用 SQLite 驗證；Docker daemon 此次不可用，因此正式 PostgreSQL、Caddy TLS、容器重啟及 pg_dump／pg_restore 路徑尚未實際驗證。部署設定不能當成已部署雲端的證據。

schema_versions 記錄目前第 1 版 schema，新增表採 create_all；不接受較新的資料庫版本。未建立一般欄位變更的完整 migration／downgrade 流程。現有案例草稿使用版本衝突檢查，仍需補強高並發編輯驗證。派工及排班在 SQLite 以寫入鎖串行核對，PostgreSQL 使用帳號列鎖，但 PostgreSQL 並發路徑未驗收。

企業正式交付前還需真實手冊／案例與領域人員驗收、伺服器與網域部署驗證、異地備份演練、監控告警接收人與容量測試。備品入庫／領用／退料與日曆式保養到期清單已實作，詳見 [維修流程手冊](repair-flow.md)；尚未提供採購、ERP 同步或背景自動建立保養工單。多企業租戶隔離、SSO、PDF/OCR、ERP/HR/PLC 串接、預測性維護與 RUL 不是本版已完成能力。AI 是依據查找與原文整理工具，尚未驗證故障診斷正確率或節省工時。

2026-10-07 已透過 SQLAlchemy 純 Python 安裝恢復本機兩模式；正式模式健康檢查、空資料庫、展示功能隔離與模型連線通過，見 [本機檢查報告](../artifacts/production-live-check.json)。兩份 Compose 設定已通過語法與環境代入檢查，Dockerfile 已補齊維修流程頁面資產。

Docker Desktop 啟動仍失敗：引擎無法重新命名 `sailor-ingest.sock`，Windows 回報無法存取該檔案。保留原檔的復原嘗試也遭相同錯誤阻擋；未刪除 Docker 資料或修改安全設定。須在可運作的 Docker 引擎驗證容器、PostgreSQL、HTTPS 與還原流程。目前沒有公開部署網址。
