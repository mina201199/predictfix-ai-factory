# 段落選取題庫 v2

本題庫共 **728 筆合成案例**：訓練 504、驗證 112、測試 112。每題有 8–10 個候選段落，正解為段落 ID 清單，無充分依據時為空清單。

既有 `evals/oem-support` 的 420 個客服案例已列入來源盤點，但只有章節定位，不能直接充當逐段選取金標。本題庫另行生成虛構機型、警報、料號與段落，參考客服題庫的問法；沒有將客服案例直接計入 728 筆。

| 類型 | 筆數 |
|---|---:|
| 有答案 | 390 |
| 資料不足 | 182 |
| 文件注入 | 156 |

其中 182 題需要選取多個段落。干擾段落包括不同機型、警報、發生條件與提問目的。答案位置打散；以零件家族分組切分資料，並檢查跨組題目與特定段落文字是否重複。不同組仍共享生成模板，所以不能據此宣稱現場泛化能力。

題庫位於 `training/selection-dataset-v2.json`。保留原先的 44 題 v1，現行訓練腳本不會自動改用 v2。正式實驗必須明確指定題庫路徑，固定模型與資料雜湊，且不可根據測試組結果調參。

## 驗證

在此 worktree 執行；下方沿用主專案的 Python 環境：

```powershell
../predictfix-ai-factory/.venv/Scripts/python.exe scripts/build_selection_dataset_v2.py --check
../predictfix-ai-factory/.venv/Scripts/python.exe -m pytest --confcutdir=. --rootdir=. tests/test_selection_dataset_v2.py -q -p no:cacheprovider
```

第一行應回報 `OK: file matches a fresh build` 與 504／112／112；第二行應全部通過。測試涵蓋最少筆數、候選數、有效答案 ID、注入不當正解、跨組外洩、答案位置與 tokenizer 長度紀錄的雜湊一致性。

## 評測紀錄限制

`artifacts/selection-v2-gemma-sample.json` 保存了早期題庫的 34 題探索性評測。其題庫 SHA-256 與目前 728 筆檔案不同，**不能用其中的準確率代表目前題庫**。它還看過部分測試組；正式保留測試應另建未被用來決策的情境組，再執行一次固定版本的完整基準。

合成標註由生成規則產生，尚未經維修領域專家獨立審查。結構檢查與可重現生成不代表維修知識正確。
