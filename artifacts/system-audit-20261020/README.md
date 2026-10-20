# 系統稽核報告（2026-10-20）

範圍為 `ai factory` 目錄的 14 個 Git 工作區與影片工具，涵蓋安全、功能、SQLite/PostgreSQL 介接、Compose 設定與 CPU 訓練煙霧測試。入口為 [summary.json](summary.json)，各 JSON 的 SHA-256 位於 [checksums.json](checksums.json)。

已修正登入節流的並行競爭、Origin/CSRF 異常輸入、PATCH 未提供欄位被清空、PostgreSQL 重複介接與 CSV 鎖定順序、反向代理信任範圍、生產介接 worker 設定、訓練套件已知漏洞，以及影片工具的排班資料準備。

## 證據

| 檔案 | 內容 |
|---|---|
| `full-pytest-summary.json` | 稽核當時 15 個工作目錄共 1946 個測試通過 |
| `sqlite-integration-summary.json` | 18 次執行，共 972 個測試通過 |
| `postgres-integration-summary.json` | 9 個介接工作區各 54 個測試通過，共 486 個 |
| `dependency-audit.json` | 修正後 84 組套件版本，OSV 查詢未回報已知漏洞 |
| `dependency-audit-before-upgrade.json` | 升級前的查詢結果 |
| `static-audit.json`、`compose-audit.json` | 靜態檢查與部署組態檢查 |
| `cpu-training.json`、`gemma-cpu-buildtools.json` | CPU 模型 backward、儲存與重載證據 |
| `fixture-audit.json` | 展示資料檢查 |

上述 1946 個測試包含各工作目錄原有的未提交修改，與本輪提交範圍不同。提交前另從 Git 暫存樹匯出乾淨目錄執行完整測試；各提交訊息記錄對應的 Git tree 與測試數量。未將其他原有修改一併提交。

## 重現

依各分支 README 安裝該分支的測試依賴，在專案根目錄執行：

```powershell
& .venv/Scripts/python.exe -m pytest tests -q
```

主線另外執行 `tools/demo-video/tests`。資料庫介接需要依 README 啟用對應設定與測試用資料庫，再執行 `tests/integration_scenario.py`；避免指向正式資料庫。

這些結果不保證不存在其他漏洞，也不代表已部署、既有 Python 環境已升級或 GPU 訓練已通過。報告不包含資料庫、憑證、模型權重、原始工作區快照或影片輸出。完整影片本次未重新錄製。
