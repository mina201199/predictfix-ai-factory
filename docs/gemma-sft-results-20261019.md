# Gemma 4 E2B 固定 SFT 實驗紀錄（2026-10-19）

**狀態：正式 QLoRA 訓練執行中；本文不是最終成效報告。** 原模型基準已完成，品質比較需等待固定 126 步、全新程序重載及保留集評估完成。

本次依使用者選擇，先做 QLoRA 正式實驗；一般 LoRA 僅做資源實測，不填正式品質成績。規則在訓練前凍結並提交 `f254397`，見 [protocol](gemma-sft-protocol.md) 與 [重跑方式](gemma-sft-running.md)。既有 Qwen、3 步可行性及 34 題探索報告均保留。

chat 中斷後確認第一個正式 run 程序已停止，最後落盤 7 steps；確切 OS 退出原因與未落盤的 in-flight 更新無法確認。未留下 adapter／optimizer／RNG 狀態，不能精確恢復。已保留[獨立中斷紀錄](../artifacts/gemma-sft-interrupted-run01-20261019.json)，第二個 run 從相同固定初始化重新執行；兩者步數不合併。初始 adapter SHA 一致，第二個 run 的前 7 筆 loss 與中斷 run 逐筆相同。原模型基準沿用凍結後已完成的 128 題，沒有更換題庫或以保留集調參。

## 固定預算

- 官方 `google/gemma-4-E2B-it`，revision `3e22461f65e89153144f8adb70e3b8c2cc9845a7`，權重 SHA 已核對。
- v2 train 固定 126 題、126 optimizer steps／一個 epoch，101101 序列 tokens、1399 監督 tokens。未使用 v2 剩餘訓練題；不宣稱跑完 504 題完整資料集。
- v2 validation 28 題屬開發驗證；新家族 holdout 100 題屬固定保留評估。候選 8–10 段，金標為 0–3 個段落 ID。
- 同一 prompt、官方 chat template 與 canonical-order JSON token trie；nf4 原模型與 QLoRA 使用同一量化／裝置拆分／解碼條件。只取最終 adapter，不根據保留集挑 checkpoint。

## 已完成的原模型基準

| 組別 | 題數 | Exact match | Precision | Recall | 資料不足拒答 | 注入題 exact match | JSON 合法率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| nf4 原模型／開發驗證 | 28 | 3.57% | 36.00% | 93.10% | 0／9 | 0／4 | 100% |
| nf4 原模型／新保留集 | 100 | 9.00% | 32.71% | 97.78% | 0／40 | 4／20 | 100% |

原始證據：[nf4 基準報告](../artifacts/gemma-sft-base-nf4-20261019.json)。逐題原始輸出、split、kind、family、金標與分組統計均在報告中。

原模型在此解碼條件下傾向多選，recall 高但 precision 與拒答差。這是 nf4 手動拆分與有限 grammar 的特定結果，**不代表既有 llama.cpp GGUF 服務的準確率**。canonical 候選順序限制了生成路徑，不能直接與舊 34 題、Q8_0 或自由輸出數字比較。JSON 合法率由 grammar 保證，不能當作能力改善。

## 工具驗證與限制

普通專案測試 90 passed、無 skip；保留既有 Starlette/httpx deprecation warning。資料守門與實驗流程有 15 項新增測試，包括跨家族外洩、資料／protocol 雜湊、無效 JSON、重複列、基準混入 adapter、重載不一致與超時報告。

[CPU 小型 fixture](../artifacts/gemma-sft-cpu-runtime-check-20261019.json) 實際完成一個更新、保存／重載、快取與完整前綴解碼比較；重載 probe logits 最大誤差 0。這只驗證工具邏輯，不能當作官方權重或 GPU SFT 成果。

[官方 tokenizer 全量檢查](../artifacts/gemma-sft-token-audit-20261019.json) 確認全部固定列符合 1024 cap，沒有截斷、略過或把 validation／holdout 當 train；所有合法 grammar 答案最長 22 tokens。

資料仍為單一作者的規則標註合成案例，沒有維修專家獨立審查與現場驗收。即使保留集改善，也只能主張在此合成選段任務、固定格式與量化條件下改善。
