# 面試準備執行計畫

**目標：** 完成使用既有資料即可處理的面試準備；正式上線工作、模型重訓與簡報檔案修改不在範圍內。

**依據：** 使用者已同意先完成面試前清單中可直接執行的項目。此為既有功能的文件整理與測試可靠性修正，沿用現有架構。

**工作版本：** 在原 `predictfix-wave2-main` 工作樹，以 `2c9e38f` 為基底建立 `codex/interview-readiness`。不切換其他工作樹、不合併訓練分支、不推送。

## 待辦

- [x] 調查 `tests/test_gemma_sft_protocol.py` 心跳等待失敗，以受控啟動延遲重現；只在證據支持時修正測試，保留實際後代程序清理斷言。
- [x] 新增 `docs/interview-readiness.md`，包含角色表、CPU/GPU/QLoRA 數字、介接及圖譜邊界、業務回答與需要使用者提供的資料。
- [x] 更新 `README.md` 與 `docs/interview-demo.md` 的展示入口、版本與驗證方式；校正 `docs/model-selection.md`、`docs/access-control.md`、`docs/ticket-integration.md`、`docs/ticket-integration-validation.md`、`docs/knowledge-graph.md`、`docs/repair-flow.md`、`docs/lora-training.md`、`docs/gemma-sft-results-20261019.md` 的過時敘述。歷史紀錄保留並標日期。
- [x] 新增 `docs/interview-handoff-20261021.md` 作為面試交接；不覆寫工作區根目錄的歷史交接。
- [x] 將最新訓練分支的選定原始報告原樣複製到 `artifacts/interview-20261021/`，記錄來源 commit 與 SHA-256，不改寫舊報告。
- [x] 以新建隔離 SQLite 驗證維修流程、介接與圖譜操作；使用既有工具，不連企業端點，不啟動 GPU，不改動既有服務或資料庫。
- [x] 執行完整 `tests` 與 `tools/demo-video/tests`、檢查文件連結與差異；獨立審查後記錄結果。

## 驗證方式

在工作樹根目錄使用 `../predictfix-ai-factory/.venv/Scripts/python.exe`，指定 `--confcutdir=. --rootdir=.` 及全新的 `.runtime` 暫存路徑，避免 Windows 預設 pytest 暫存目錄權限干擾。

先跑失敗案例與受控延遲案例，再跑完整測試。報告保存本輪執行的日期、指令、退出碼與測試數；不將舊 GPU、PostgreSQL、TLS 或 CI 紀錄宣稱為本輪重測。

## 等待使用者提供

- 面試簡報：才能同步原始投影片。
- 展示方式、電腦與可用時間：目前先按此 Windows 電腦的本機展示編寫。
- 實際報修／派工／查資料／驗收流程：才能寫真實場景與成效，現階段不填節省百分比。
