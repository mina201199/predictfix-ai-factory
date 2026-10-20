# 版本整合與回歸驗證（2026-10-20）

## 版本來源

本次整合以 GitHub `main` 的 `2c9e38f7e7dafb53e13cfa88dd30453534940a83`
為基礎，工作分支為 `codex/release-regression-20261020`。
原工作目錄停在 `15a8b1c`，與遠端已有不同提交歷史；未將舊目錄直接覆蓋
主線，未 force-push。原始未提交資料完整保留。

## 整合內容

- 納入獨立手機展示 HTML／CSS／JS、啟動工具與 2026-10-15 歷史驗證報告。
- 將手機頁內嵌樣式移至外部 CSS，沿用主線嚴格 CSP。
- FastAPI 僅在展示模式提供 `/mobile.html`、`/app.js`、`/app.css`；
  正式模式均為 404。手機頁以 localStorage 模擬流程，沒有後端資料同步。
- 容器包含手機展示資產，CI 增加展示模式啟動檢查；正式模式仍檢查
  API 文件與展示資產阻擋。未放寬登入或安全政策。
- 納入 60 秒截圖產品介紹的字幕、分鏡、腳本及本機成品雜湊。
  額外 MP4／封面保留本機；遠端沿用原主線的中文旁白實機操作影片，
  傳輸限制見 [影片說明](product-video.md)。
- 更新 README、系統架構與面試展示文件，修正舊版的「沒有向量檢索」、
  「沒有排班／OCR」與「CI／Docker／PostgreSQL 全未驗證」敘述。

## 本次驗證

完整 pytest：**161 passed，462.87 秒，零 failures／errors／skipped**。
唯一警告為既有 Starlette/httpx TestClient 棄用提示。
原始 [JUnit](../artifacts/release-tests-20261020.xml) 已通過非零測試／零跳過檢查。
另有 **35／35** [應用安全檢查](../artifacts/security-regression-20261020.json)通過。
Node 語法檢查及掃描請求順序檢查通過，pip check 無依賴衝突。

使用新的 Python 3.12 虛擬環境，
依 `requirements.txt` 安裝固定版本；Windows SQLAlchemy 使用純 Python
建置。測試使用隔離資料庫，停用付費 API，不修改現有工單或模型服務。

受限執行環境的首次安全子程序逾時，首次全套測試已中止，未算作成功；
以上結果來自一般本機權限的完整重跑。

## GitHub CI：三組通過

[PR #10](https://github.com/mina201199/predictfix-ai-factory/pull/10)
將這 23 個檔案發布至既有公開儲存庫的 `codex/release-regression-20261020` 分支。
程式提交 `8c9559f079dab4fa45bc8f5cd877c0563b5fa1b5` 的 Git tree
與本機已驗證提交 `d73c4a0` 完全一致（`ba5942763d5e2c7a9e8d777eb95836050dca4f62`）。

2026-10-20 的 [GitHub Actions 執行 #55](https://github.com/mina201199/predictfix-ai-factory/actions/runs/39452377590)
已完成且結論為 `success`：

| Job | 結果 | 實際驗證 |
| --- | --- | --- |
| tests | success | Ubuntu／Python 3.12：161 passed，151.62 秒；JUnit 確認 failures、errors、skipped 皆為 0；既有棄用警告 1 個。 |
| container | success | 建置映像；正式及展示兩模式頁面與資產、嚴格 CSP、匿名 API 阻擋；正式模式隱藏手機展示及 API 文件。 |
| postgres | success | PostgreSQL 17 三個維修情境、Compose 正式服務、重啟保存、pg_dump 備份及新資料庫還原。 |

此後文件紀錄更新也會觸發相同三個 job，最新提交狀態以
[PR checks](https://github.com/mina201199/predictfix-ai-factory/pull/10/checks) 為準。
僅在失敗時執行的容器診斷步驟被略過是正常流程，不是 pytest 跳過測試。
本次未合併 main，也未部署正式服務；發布範圍不含 `.env`、憑證、
正式／展示資料庫、本機 MP4 與封面。

## 本機重現

```powershell
.\.venv\Scripts\python.exe scripts/check_runtime.py
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest --confcutdir=. --rootdir=. -q -p no:cacheprovider --basetemp=.runtime/regression-20261020-unrestricted --junitxml=.runtime/regression-20261020.xml
.\.venv\Scripts\python.exe scripts/check_test_report.py .runtime/regression-20261020.xml
node tests/scan_race.cjs
node --check sites/predictfix-mobile/dist/app.js
node --check scripts/serve_mobile_demo.cjs
```

## 驗證範圍

全套 pytest 不重訓官方模型，也不重跑付費 OpenAI 或真實本機模型攻擊情境。
歷史模型品質與安全報告保留原日期。CI 的 PostgreSQL job 驗證既有三個
維修情境及 Compose 重啟／備份還原；新增圖譜與外部工單的 PostgreSQL
驗收、HTTPS、真實手機拍攝、企業現場試用仍屬後續工作。
