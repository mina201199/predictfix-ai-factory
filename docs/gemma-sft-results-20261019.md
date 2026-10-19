# Gemma 4 E2B 固定 SFT 實驗紀錄（2026-10-19）

**QLoRA 已完成固定 126 步並通過全新程序重載，但品質未達可用：128 題全部輸出空選段。** 新保留集 exact match 從 9% 變為 40%，完全來自空金標題答對；有答案題全部漏選，recall 從 97.78% 降為 0%。不能宣稱選段能力改善，也不應採用這個 adapter 替換現有服務。

本次依使用者選擇，先做 QLoRA 正式實驗；一般 LoRA 僅做資源實測，不填正式品質成績。規則在訓練前凍結並提交 `f254397`，見 [protocol](gemma-sft-protocol.md) 與 [重跑方式](gemma-sft-running.md)。既有 Qwen、3 步可行性及 34 題探索報告均保留。

chat 中斷後確認第一個正式 run 程序已停止，最後落盤 7 steps；確切 OS 退出原因與未落盤的 in-flight 更新無法確認。未留下 adapter／optimizer／RNG 狀態，不能精確恢復。已保留[獨立中斷紀錄](../artifacts/gemma-sft-interrupted-run01-20261019.json)，第二個 run 從相同固定初始化重新執行；兩者步數不合併。初始 adapter SHA 一致，第二個 run 的前 7 筆 loss 與中斷 run 逐筆相同。原模型基準沿用凍結後已完成的 128 題，沒有更換題庫或以保留集調參。

## 固定預算

- 官方 `google/gemma-4-E2B-it`，revision `3e22461f65e89153144f8adb70e3b8c2cc9845a7`，權重 SHA 已核對。
- v2 train 固定 126 題、126 optimizer steps／一個 epoch，101101 序列 tokens、1399 監督 tokens。未使用 v2 剩餘訓練題；不宣稱跑完 504 題完整資料集。
- v2 validation 28 題屬開發驗證；新家族 holdout 100 題屬固定保留評估。候選 8–10 段，金標為 0–3 個段落 ID。
- 同一 prompt、官方 chat template 與 canonical-order JSON token trie；nf4 原模型與 QLoRA 使用同一量化／裝置拆分／解碼條件。只取最終 adapter，不根據保留集挑 checkpoint。

## 固定評估結果

| 組別 | 題數 | Exact match | Precision | Recall | 資料不足拒答 | 注入題 exact match | JSON 合法率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| nf4 原模型／開發驗證 | 28 | 3.57% | 36.00% | 93.10% | 0／9 | 0／4 | 100% |
| QLoRA／開發驗證 | 28 | 32.14% | 0%* | 0% | 9／9 | 1／4 | 100% |
| nf4 原模型／新保留集 | 100 | 9.00% | 32.71% | 97.78% | 0／40 | 4／20 | 100% |
| QLoRA／新保留集 | 100 | 40.00% | 0%* | 0% | 40／40 | 10／20 | 100% |

*沒有預測正例時，計分器將 precision 設為 0；分母為 0，不代表量到精確率。資料不足包含所有空金標題，因此與純 `no_answer` kind 的數量不同。

| 新保留集類別 | 題數 | 原模型 EM | QLoRA EM | 原模型 recall | QLoRA recall |
|---|---:|---:|---:|---:|---:|
| positive | 50 | 10%（5／50） | 0% | 97.14% | 0% |
| no_answer | 30 | 0% | 100% | 不適用 | 不適用 |
| document_injection | 20 | 20%（4／20） | 50%（10／20） | 100% | 0% |

注入題有 10 題空金標、10 題非空金標；QLoRA 只答對前者。新保留集兩組都未選入注入段落，不能把 QLoRA 的 50% 注入題 EM 解讀成更強抗注入能力。開發驗證原模型有 1／4 注入題選入注入段落，QLoRA 為 0／4，同樣伴隨全部拒答。保留集 10 個新家族各 10 題，QLoRA 全部都是 40% EM／0% recall。

原始證據：[nf4 基準](../artifacts/gemma-sft-base-nf4-20261019.json)、[QLoRA 完整評估](../artifacts/gemma-sft-qlora-eval-20261019.json)、[按 split／kind／family 比較](../artifacts/gemma-sft-comparison-20261019.json)。完整 128 題都有原始輸出與金標；比較統計不混合 validation 與 holdout。

代表錯誤：`holdout-energy-meter-00` 金標 `S2:P1`，原模型多選 `S2:P1,S4:P1,S9:P1`，QLoRA 選 `[]`；`holdout-energy-meter-05` 空金標，原模型錯選三段，QLoRA 正確拒答。此處總 EM 的增加掩蓋了正例辨識的退步。

原模型在此解碼條件下傾向多選，recall 高但 precision 與拒答差。這是 nf4 手動拆分與有限 grammar 的特定結果，**不代表既有 llama.cpp GGUF 服務的準確率**。canonical 候選順序限制了生成路徑，不能直接與舊 34 題、Q8_0 或自由輸出數字比較。JSON 合法率由 grammar 保證，不能當作能力改善。

這個固定單次實驗無法分離樣本量、更新設定與受限解碼對全拒答的影響，不能據此推論所有 QLoRA 都會失敗；也沒有以保留集結果調參重跑來追求較高分數。

## 訓練、重載與資源

[正式訓練紀錄](../artifacts/gemma-sft-qlora-train-20261019.json) 保留 126 筆順序一致、有限 loss／gradient norm 的更新，最後 loss 為 0.0468174。低訓練 loss 沒有轉化成保留集選段能力；本次不依結果調參或改選 checkpoint。訓練約 115.25 分鐘，重載及 128 題評估約 5.44 分鐘；併發工作量未受控，這些只是本次耗時，不能當成速度比較。

新程序從官方基底載入最終 adapter，參數數量、adapter／config 雜湊與 probe 輸出一致，logits 最大絕對誤差 **0**，通過事前固定 `atol=rtol=1e-4`。共有 410 個有限 LoRA tensors、12,079,104 個參數，adapter 檔案 48,370,272 bytes；checkpoint 126 與 final adapter 雜湊相同，見 [完整性紀錄](../artifacts/gemma-sft-adapter-integrity-20261019.json) 與 [campaign 紀錄](../artifacts/gemma-sft-campaign-20261019.json)。這證明保存／重載一致，不能證明品質可用。

| 階段 | 題數／步數 | CUDA peak allocated | CUDA peak reserved | CPU peak working set |
|---|---:|---:|---:|---:|
| nf4 原模型推論 | 128 題 | 1228 MiB | 1400 MiB | 10583.65 MiB |
| QLoRA 正式訓練 | 126 步 | 1782 MiB | 2082 MiB | 10581.27 MiB |
| QLoRA 重載及推論 | 128 題 | 1282 MiB | 1486 MiB | 10581.45 MiB |

CPU embedding／PLE／tied lm_head 使用 bfloat16，GPU decoder 為 nf4、計算 float32，adapter float32；這是 CPU／GPU 手動拆分結果。GTX 1050 Ti 4 GiB／sm 6.1、WDDM，套件版本見 [環境快照](../artifacts/gemma-sft-environment-20261019.json)。PyTorch allocated／reserved 是程序配置器高水位；nvidia-smi 為全裝置使用量，且與 `mem_get_info` 採樣時間／口徑不同，不能相加、相減推估其他程序，或宣稱獨占顯存。也不能把訓練與推論記憶體當作 LoRA／QLoRA 的相同工作負載比較。

只載入官方 checkpoint 的文字模型；不使用的多模態權重記為 1400 個 unexpected keys，missing／mismatched keys 均為空，並非以隨機權重補齊缺失文字層。

最終 adapter 位於工作樹 `.runtime/qlora-campaign-formal-02/qlora_train/adapter`，未加入 Git。SHA256：`af5f9f42178f223c9daecfb1a00ad043e24dee76964c88b14570196bba13eb0a`。每 18 步的 checkpoint 也留在該 run；移除／封存工作樹前須另行保存這些忽略檔。沒有保存 optimizer／RNG 狀態，不能聲稱可精確續訓。

一般 fp16 LoRA 的[限時資源實測](../artifacts/gemma-sft-lora-fp16-resource-20261019.json) 完成兩題推論及 **2 個 optimizer steps**，狀態 `cost_probe_only`、正常退出且未逾時。兩步耗時約 117.94／115.03 秒；初始化 adapter 雜湊與正式 QLoRA 相同。沒有保存用於品質比較的 LoRA adapter，也沒有完整 LoRA／fp16 原模型的 128 題評估，因此不填正式 LoRA 品質成績。

其 CUDA peak allocated／reserved 為 **4160／4316 MiB**，CPU peak working set 為 **10581.46 MiB**；結束採樣 `mem_get_info` free 為 0 MiB，nvidia-smi 全裝置用量為 3929 MiB。配置器高水位已超過顯卡標示的 4096 MiB，不能解讀為全部常駐實體顯存，或宣稱一般 LoRA 完整訓練可順暢容納於 4 GiB。這個 WDDM 實測只能證明兩步完成；沒有發生 OOM，也無法推論後續步數必然成功或失敗。兩步與正式 QLoRA 的 126 步工作量不同，不拿來計算公平的顯存／速度改善倍率。

## 工具驗證與限制（GPU 實驗交付時）

普通專案測試 **93 passed、無 skip**（67.93 秒）；保留既有 Starlette/httpx deprecation warning。資料守門與實驗流程有 18 項新增測試，包括跨家族外洩、資料／protocol 雜湊、無效 JSON、重複列、基準混入 adapter、重載不一致、原子報告寫入與逾時程序樹清理。清理測試使用 CPU fixture，確認不終止不相關的程序，並涵蓋 PID reuse 與已退出程序的競態。

[CPU 小型 fixture](../artifacts/gemma-sft-cpu-runtime-check-20261019.json) 實際完成一個更新、保存／重載、快取與完整前綴解碼比較；重載 probe logits 最大誤差 0。這只驗證工具邏輯，不能當作官方權重或 GPU SFT 成果。

[官方 tokenizer 全量檢查](../artifacts/gemma-sft-token-audit-20261019.json) 確認全部固定列符合 1024 cap，沒有截斷、略過或把 validation／holdout 當 train；所有合法 grammar 答案最長 22 tokens。

資料仍為單一作者的規則標註合成案例，沒有維修專家獨立審查與現場驗收。即使保留集改善，也只能主張在此合成選段任務、固定格式與量化條件下改善。

## 後續程序監督修正（僅 CPU 回歸）

獨立審查另發現舊 runner 的生命週期缺陷：直接父程序退出後，`runBounded` 會回傳，但後代可能仍執行；清理時的後代快照也無法涵蓋之後出生的程序。CPU 心跳 fixture 在成功與錯誤退出兩種案例都重現此問題。這項缺陷不能由先前的「逾時時父程序仍存活」測試排除。

現行 Windows runner 先以 suspended 狀態建立程序，加入禁止 breakaway、設定 kill-on-close 的 Job Object 後才 resume。正常退出、逾時或例外都會終止該 job，確認 active process count 為 0 才返回。POSIX 使用獨立 process group；以 `waitid(..., WNOWAIT)` 保留 leader，送出終止訊號後限時確認整組沒有非 zombie 成員，最後才回收 leader，避免 PGID 重用。無法確認清理成功會拋錯，campaign 不會繼續下一階段。

GPU 實驗與 fp16 資源實測均在這次修正之前執行，使用舊 runner；**沒有重跑 GPU、修改原始實驗報告、回填歷史 source hash 或變更品質結論**。新的 runner 原始碼與歷史執行版本不同，不應用新程式碼雜湊冒充當時版本。

Windows 上完整普通回歸為 **96 passed、無 skip**（90.75 秒，1 個既有 warning），其中流程測試 21 項。涵蓋父程序退出碼 0／9、逾時、`KeyboardInterrupt`、啟動後較晚出生的後代，以及不相關程序的心跳持續更新。見 [CPU 回歸紀錄](../artifacts/gemma-sft-lifecycle-verification-20261019.json)。POSIX 實作已完成靜態審查，但本次 Windows 主機沒有實跑 POSIX；仍需整合後的 Ubuntu CI 驗證，不能把本機 96 項通過當成跨平台實測完成。
