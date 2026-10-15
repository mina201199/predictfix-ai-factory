# 本機安裝與啟動

本專案在 Windows 本機展示。以下指令在專案根目錄執行；先安裝 Python（原始開發說明使用 Python 3.12）。

2026-10-07 已修復 SQLAlchemy `_processors_cy` DLL 載入阻擋，展示與正式資料模式皆恢復。安裝工具採用 [SQLAlchemy 官方支援的純 Python 建置](https://docs.sqlalchemy.org/en/20/intro.html)，透過 `DISABLE_SQLALCHEMY_CEXT=1` 與來源套件安裝，未更改 Windows 安全政策。

## 第一次安裝

```powershell
.\setup.ps1
```

工具建立 `.venv`、安裝固定版本依賴，再檢查 Python 3.12、主要套件匯入與 SQLite 讀寫。已有環境若仍使用 SQLAlchemy 原生擴充，會重新安裝純 Python 版本。啟動腳本也會先執行環境檢查，失敗時停止並顯示原因。

如需展示公開軸承資料的模型回放，以及本機 Gemma 4 E2B 模型：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_model.py
.\.venv\Scripts\python.exe scripts\setup_local_llm.py
```

這兩個腳本會下載公開資料、模型與官方執行工具；本機檔案放在 `data/`、`artifacts/` 與 `.runtime/`。沒有本機 LLM 時，知識中心顯示候選來源並標示降級狀態。

## 展示版

```powershell
.\start.ps1 -Demo -Port 8082
```

- 設備總覽：http://127.0.0.1:8082/
- 維修流程：http://127.0.0.1:8082/workflow.html
- 出勤與人員管理：http://127.0.0.1:8082/console.html
- 維修 AI 中心：http://127.0.0.1:8082/knowledge.html

登入畫面提供主管／工程師快速體驗。展示資料庫為 `data/predictfix.db`；新排查流程仍需主管建立出勤與資格，才會有可派工程師。

面試展示可另開終端機執行 `.\.venv\Scripts\python.exe scripts/prepare_interview_demo.py`，準備獨立示範工單、專用工程師與當日出勤。詳見 [面試展示指南](interview-demo.md)。

如需三筆已完成的合成維修案例，在展示服務啟動後執行 `python scripts/seed_knowledge_demo.py`。重跑不重複建立相同事件；請依腳本的 URL 設定連到展示服務。這些資料會保存到展示庫。

## 正式資料環境

```powershell
.\start-production.ps1 -Port 8083
```

開啟 http://127.0.0.1:8083/。正式環境從空資料庫開始，不載入展示資料或快速登入。首次管理員帳號與隨機密碼存放於未納入 Git 的 `data/production-access.json`。

帳號管理、出勤、備份還原與部署設定見 [正式環境手冊](production-setup.md)。服務目前僅綁定 localhost；關機或結束程序後需重新啟動。

## 測試

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

測試使用隔離資料庫，不寫入本機正式資料。完整開發與模型限制見 [歷史開發紀錄](development-history.md)。
