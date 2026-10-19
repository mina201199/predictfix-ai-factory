# Gemma SFT 重跑與驗證

正式規則見 [固定 protocol](gemma-sft-protocol.md)。128 題評估包含 28 題 v2 開發驗證與 100 題新保留集；報告必須分 split 解讀。訓練只有固定的 126 題 v2 train，不能混入 validation 或 holdout。

2026-10-19 使用者選擇先完成 QLoRA 正式實驗（約 3 小時），一般 LoRA 僅做資源實測。因此即使 QLoRA 全部完成，也不代表一般 LoRA 正式訓練完成。

## 本機環境

在此 worktree 執行，不在外層 App 專案根執行。沿用主 repo 獨立環境，不安裝／改動依賴；`.runtime` 與 `.env` 已被忽略。實驗不需要 API key、token 或任何現場資料。

```powershell
$python = 'C:/Users/User/Desktop/ai factory/predictfix-ai-factory/.runtime/qlora-env/Scripts/python.exe'
$runtimeDir = '../predictfix-ai-factory/.runtime'
$env:HF_HUB_OFFLINE = '1'
$env:PYTHONIOENCODING = 'utf-8'
```

## 一次序列執行

每次使用全新 `--run-dir`。工具拒絕覆寫既有實驗，讀取快取時核對官方權重 SHA。以下指令會依序跑原模型 nf4 基準、QLoRA 126 步、全新程序重載及完整評估。外層預算到期只會終止工具自己建立的子程序，不處理既有 llama-cuda 或其他工作。

現行 runner 在 Windows 先 suspended 建立根程序、加入獨立 Job Object，再開始執行；正常父程序退出、逾時與例外都會先收束整組後代，確認 job 無活動程序才返回。POSIX 使用獨立 process group，需 `waitid/WNOWAIT` 與 `ps`，保留 leader 至群組清理完成才回收。不支援或無法確認清理成功時直接失敗，不降級成只清理父程序。這是歷史 GPU 實驗之後的 CPU 驗證修正，見[版本與回歸說明](gemma-sft-results-20261019.md#後續程序監督修正僅-cpu-回歸)；歷史報告與 source hash 保持原樣。

```powershell
& $python scripts/run_gemma_sft_campaign.py --scope qlora --max-hours 3 --runtime-dir $runtimeDir --run-dir .runtime/qlora-campaign-new
```

若已有完整且符合固定 protocol 的原模型基準，可傳 `--baseline-nf4 <baseline-run>/report.json` 重用，不重跑。若要做完整兩種訓練對照，改成 `--scope full --max-hours 8`；這不屬於本次選定的執行預算，需另安排。兩個原模型基準會先於任何訓練，QLoRA 和 LoRA 固定相同步數／資料。基準失敗時對應訓練標為 `blocked_dependency`，不填品質分數。

## 拆開執行

```powershell
& $python scripts/run_gemma_sft.py baseline --mode qlora --runtime-dir $runtimeDir --run-dir .runtime/base-new
& $python scripts/run_gemma_sft.py train --mode qlora --runtime-dir $runtimeDir --run-dir .runtime/train-new --baseline-report .runtime/base-new/report.json
& $python scripts/run_gemma_sft.py reload --mode qlora --runtime-dir $runtimeDir --run-dir .runtime/reload-new --adapter-run .runtime/train-new
```

`train` 成功只會標記 `trained_pending_reload`。`reload` 會從官方基底重新載入 adapter、比對保存前的 train probe，成功後才評估，最終標為 `completed`；`--verify-only` 則只驗證重載。保存前後 adapter hash／參數數量／選段輸出必須相同，有限 logits 誤差需在事前固定容差內。

## 檢查證據

本次完整結果見 [2026-10-19 實測報告](gemma-sft-results-20261019.md)。流程 `completed` 只表示固定步數及評估完成，不能當作品質通過；本次 QLoRA 全部拒答，保留集 recall 為 0%。

1. 開啟 `campaign.json`：正式階段完整時為 `completed`；逾時／失敗則為 `incomplete`，不補填缺失成績。
2. 開啟 train 的 `report.json`：`optimizer_steps_actual=126`，`train_sequence_tokens=101101`、`supervised_tokens=1399`，最後一筆 step 是 126；`adapter_dir` 指向獨立 adapter。
3. 開啟 reload 的 `report.json`：`reload_verification.passed=true`；`results` 恰有 128 題，每題含原始 JSON、金標、split、kind、family；`metrics_by_split.holdout.count=100`。
4. 每個實驗記錄模型 revision／checkpoint SHA、資料／protocol SHA、相依版本、初始／最終 adapter 雜湊與資源。CPU RSS／peak working set、PyTorch allocated／reserved、nvidia-smi 全裝置使用量分開解讀，不能相加或稱為獨占顯存。

## 獨立檢查

```powershell
& $python scripts/audit_gemma_sft_data.py --runtime-dir $runtimeDir --report artifacts/gemma-token-audit-new.json
& $python scripts/check_gemma_sft_runtime.py --report artifacts/gemma-cpu-runtime-new.json
../predictfix-ai-factory/.venv/Scripts/python.exe -m pytest --confcutdir=. --rootdir=. tests -q -p no:cacheprovider --basetemp=.runtime/gemma-tests-new
```

第一行只用官方 tokenizer，檢查所有固定列長度、chat prefix、答案遮罩與 grammar 的 encode/decode。第二行只在 CPU 用隨機小型 Gemma fixture，驗證同初始 adapter、快取解碼、實際更新與保存／重載；不能充當官方 SFT 或 GPU 品質證據。普通測試不需 GPU，不使用 skip。

已記錄 token audit：train 126 題、101101 序列 tokens／1399 監督 tokens、最長 919；validation 28 題、最長 890；holdout 100 題、最長 654。所有合法 grammar 答案最長 22 tokens，低於固定 64 token 解碼上限；沒有截斷或略過題目。
