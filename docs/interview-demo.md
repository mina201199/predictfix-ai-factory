# 面試展示與交付

## 準備

```powershell
.\setup.ps1
.\start.ps1 -Demo -Port 8082
```

另開一個 PowerShell，在專案目錄執行：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_interview_demo.py
```

初始化工具只接受本機、且必須明確開啟展示模式。建立 `DEMO-INTERVIEW` 設備、虛構手冊、專用 `interview_demo` 工程師、當日出勤、資格、30 分鐘估時、已核准且已派工的排查／驗收清單、到期保養計畫及五個示範備品。專用工程師透過展示登入使用，不輸出或保存其隨機密碼；正式環境沒有快速登入。

重跑會沿用未完成的面試工單；完成後重跑才建立新的一張。不清空既有資料，不重新入庫或重複建立保養計畫，不改動原有工程師的任務。已存在但身分不符的保留帳號、專用工程師的無關未估工單會使工具停止，避免覆寫。

出勤仍有時間範圍；開始面試前重跑準備工具，重新確認目前班次與容量。保養計畫保留原到期日，過期時可展示「逾期」提醒。

## 2–3 分鐘展示腳本

入口：<http://127.0.0.1:8082/workflow.html>。這是本機網址。

| 時間 | 操作 | 要說的重點 |
|---|---|---|
| 0:00–0:30 | 主管登入，選面試設備，描述「特定刀位換刀卡住」，查找來源；故意少填一個條件。 | 補問來自必要欄位；引用能核對機型與原文，AI 不判定復機。 |
| 0:30–1:00 | 在「執行與驗收」選 `INTERVIEW DEMO` 工單，打開清單引用與推薦原因。 | 主管核准來源，工程師要有資格、出勤與剩餘容量。此工單已預先準備。 |
| 1:00–1:45 | 登出，再點「以面試示範工程師體驗」；逐項記錄，把驗收填未通過，嘗試提交，再補完成復測。 | 提交由後端阻擋；記錄的是虛構測試條件與結果。 |
| 1:45–2:30 | 切回主管，在工單工作台核對量測／紀錄並審核；到 AI 中心建立案例草稿。 | 審核可退回；案例需補齊並人工核對後發布，才能被下一次檢索。 |
| 2:30–3:00 | 展示保養、備品清單，再開安全報告。 | 日常功能、冪等與權限同樣有驗證；45 個安全情境不是安全認證。 |

切換角色要先登出，不共用主管身分執行工程師操作。最後一步發布案例如超出時間，可先展示已完成的自動操作結果，現場走到主管審核即可。

## 完整流程自動驗證

```powershell
.\.venv\Scripts\python.exe scripts/prepare_interview_demo.py --walkthrough
```

此指令真的執行驗收失敗阻擋、重新復測、提交、主管審核、案例發布及檢索；會完成目前那張示範工單。結果存於 [完整流程報告](../artifacts/interview-walkthrough-report.json)，準備狀態另存 [展示準備報告](../artifacts/interview-demo-report.json)。之後再次執行不帶 `--walkthrough` 的準備指令，留下新工單供面試操作。

這些是 API 操作證據；操作過程另見 [60 秒操作影片](media/predictfix-demo.mp4)。尚未部署公開網址；不能把本機地址分享給面試官並稱為線上 Demo。

## CI 與容器

[GitHub Actions](../.github/workflows/ci.yml) 分成完整測試、容器與 PostgreSQL 三個 job：

- 測試 job 安裝固定套件、檢查依賴、跑全套 pytest，解析 JUnit，要求確實執行測試且零失敗、零錯誤、零跳過。
- 容器 job 建置 Dockerfile，再分別啟動正式及展示模式，檢查頁面／JS／CSS、嚴格 CSP、匿名 API 阻擋及手機展示資產。正式模式的 API 文件與手機展示回傳 404。
- PostgreSQL job 執行並發派工、正式模式、維修流程情境，以及 Compose 重啟與備份還原。未涵蓋 TLS，新增圖譜／外部工單的 PostgreSQL 路徑也尚未驗收。

本機可先跑：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=.runtime/tests.xml
.\.venv\Scripts\python.exe scripts/check_test_report.py .runtime/tests.xml
```

歷史主線已有 GitHub Actions 成功紀錄；本次整合應核對推送提交的實際結果，見 [2026-10-20 交付驗證](release-validation-20261020.md)。

## 現況與下一步

本機兩模式已恢復，可進行面試流程。Windows SQLAlchemy 使用官方支援的純 Python 安裝；Docker 與 PostgreSQL 已在後續版本完成既有情境驗證。獨立手機展示只使用瀏覽器資料，實機操作影片與截圖產品介紹皆已保存。

2026-10-07 已新建 Python 3.12 環境，重新安裝固定依賴，全套 38 項測試通過、零跳過；再以該環境啟動隔離正式模式，頁面資產、API 文件與匿名存取阻擋通過。這是在目前工作目錄進行，尚未驗證另一台電腦或乾淨 Git checkout。完整狀態見 [交付檢查報告](../artifacts/interview-readiness-report.json)。

上述 2026-10-07 紀錄中的 Docker socket 阻擋屬歷史環境狀態，不能用來判斷目前 CI 或其他電腦的引擎狀態。

後續還需：驗證 HTTPS、圖譜／外部工單的 PostgreSQL 路徑，選定公開後端展示環境與網域，加入監控和異地備份演練。真實感測器、現場診斷與成效評估是另一階段。
