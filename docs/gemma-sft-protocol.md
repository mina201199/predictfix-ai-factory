# Gemma 4 E2B 第二波固定 SFT protocol

本實驗研究合成 CNC 維修段落選取，並非維修根因生成。事前固定 126 筆 SFT、一次完整 epoch（126 optimizer steps），不能把成本試跑的 1–3 步當正式訓練。改善不是預設結論。正式系統與 GGUF serving 均不變更。

## 已核准範圍與實作計畫

1. 新增 `scripts/build_selection_holdout.py`、`training/selection-holdout-v3.json`：10 個新情境家族各 10 題，共 100 題，每題 8–10 段，含單選、多選、資料不足及文件注入。所有機型、警報與段落為虛構，標註依機型／警報／條件／意圖規則；未經外部專家審查。
2. 新增 `scripts/gemma_sft_protocol.py` 與 `training/gemma-sft-protocol-v1.json`：凍結 seed、資料／prompt SHA、列 ID、參數與解碼條件。保留 v1／v2 原檔，v2 舊 validation／test 及探索評測不稱為盲測。
3. 新增 `scripts/run_gemma_sft.py`：讀取既有官方模型快取，四個 arm 序列執行；原模型基準先於微調。訓練與評估入口分開，adapter 保存於本 worktree `.runtime`，報告另存 artifacts，不覆寫歷史。
4. `tests/test_gemma_sft_protocol.py`：先驗證新功能不存在時失敗，再驗證分組與雜湊守門、嚴格 JSON 指標、grammar 與 adapter 重載比較。普通 CI 不需要 GPU、不使用 skip。GPU 結果需另有實測證據。
5. 執行成本 probe、完整基準、同預算兩種 SFT、全新 process 重載驗證、validation／holdout 評測，保存逐題輸出及限制；最後跑專案測試與程式碼 review。

## 不變的實驗條件

模型 `google/gemma-4-E2B-it`，revision `3e22461f65e89153144f8adb70e3b8c2cc9845a7`。checkpoint SHA-256 應為 `2db5482b20d746879bb3ef79b5203e9075a2e2b98f54ec7c2f281c1477ddc550`。只讀主 repo 已驗證快取；`HF_HUB_OFFLINE=1`，不下載權重，不改環境版本。

seed 20261019。v2 train 的 18 個家族，各固定抽 positive 4、no_answer 2、document_injection 1，共 126 題；其餘 train 不使用。v2 validation 的 4 個家族依相同比例抽 28 題作開發驗證。新 holdout 100 題全部評測；不得以其結果調參、挑 checkpoint 或修改題目。v2 原 test 不納入新保留評估。

一般 LoRA 和 QLoRA：rank 8、alpha 16、dropout 0.05，targets 為 q/k/v/o_proj 與 gate/up/down_proj；AdamW，lr 2e-4，weight_decay 0.01，grad clip 1.0，batch 1，無梯度累積，126 steps／1 epoch，固定相同列順序，sequence cap 1024，不截斷、不悄悄捨棄題目。兩個 arm 的 adapter A 均以獨立 CPU fp32 generator、固定 seed、Kaiming uniform（a=√5）初始化，B 為 0，複製後均為 fp32；排除 nf4 建層與 base dtype 對 RNG 的影響，記錄初始 adapter hash。只對答案與 chat 結束 token 算 loss。使用最終 checkpoint，不做超參數搜索或 early stopping。完整記錄實際 steps、序列／監督 token 數及每步 loss；失敗、中止均保留，不補填分數。

## 比較與解碼

四個 arm：`base_fp16`（原模型 fp16 decoder）、`base_nf4`（原模型 nf4 decoder）、`lora_fp16`、`qlora_nf4`。embedding／PLE 與 tied lm_head 均留 CPU bf16；fp16 decoder 的輸入為 fp16，nf4 compute fp32。量化前後差異由兩個原模型 arm 補充；QLoRA 必須與 base_nf4 比較、LoRA 必須與 base_fp16 比較，不能把量化差異歸因於訓練。

全部使用相同 `prepare_lora_data.prompt` 與官方 chat template、greedy decoding、最多 64 新 tokens。相同 token trie 限制 canonical JSON：selected 為候選順序的一個 0–3 元素子集合，無重複。訓練答案也採候選順序。grammar 只看候選 ID，不看金標；所有合法子集合都可生成。這是有限 JSON grammar，選段及生成路徑與自由生成不同；JSON 合法率接近 100% 是格式限制的結果，不應宣稱為模型能力提升。原始選段／注入錯誤仍可發生。

評估記錄 exact match（集合相等且 schema 合法）、micro precision／recall、資料不足拒答（所有金標為空的題目）、文件注入 exact match／誤選注入率、JSON／schema 合法率，分 kind 與 family，保存逐題原始輸出。無效 JSON 不視為空答案答對；零分母 precision／recall 定義為 0。

## 保存與重載

最終 adapter 保存 safetensors，記錄 adapter config／權重 SHA 與實際 trainable parameter 數。保存前於固定 train probe（不是 holdout）記錄 constrained output 及第一個有選擇的 grammar 分岔 logits；關閉程序。獨立 `reload` 命令重新載入全新官方模型及 adapter，核對雜湊與參數，輸出相等且有限 logits 在 atol／rtol 1e-4 內才允許評估。實驗入口不等於 GGUF serving 已支援 adapter。

## 資源與成本

GPU GTX 1050 Ti 4 GB（sm61）、CPU i5-14500、RAM 64 GB，共用機器有既有 llama-cuda／安全評估工作。不得停止其他服務。分開記錄 PyTorch allocated／reserved peak、nvidia-smi 全裝置使用量、CPU process RSS／peak working set。WDDM 可借用共享記憶體，成功分配不代表全在獨占 4 GB 顯存內。

先以未微調原模型跑少量 **train** 題的成本 probe，單獨記錄 wall clock 估算完整預算，不拿延遲做受控效能比較。若預估數小時以上，向使用者提出實測估算及具體選項；等待期間完成工具、資料檢查與測試。probe 不列正式保留測試結果，訓練 probe adapter 不能當成最終模型。

2026-10-19 成本 probe 使用官方權重完成 2 個 optimizer steps，約 68.0／59.7 秒；兩個 train 題推論約 6.39／6.33 秒。原始報告在 `artifacts/gemma-sft-cost-probe-nf4-20261019.json`，**只供預算估算**。此 probe 在 canonical adapter 初始化修正前執行，沒有保存正式 adapter／品質評估；後續正式 run 記錄實際 source SHA 與初始 adapter hash。原始報告在 CUDA 初始化後的 `used_by_others_mib` 是舊欄位名稱，實際為 nvidia-smi 全裝置使用量，包含本程序；新工具已更正為 `device_used_mib`。不改寫歷史報告。

使用者已選擇「先完成 QLoRA：約 3 小時；一般 LoRA 僅做資源實測並另報限制」。本次不宣稱完成兩種正式 SFT 的品質對照；完整一般 LoRA 仍需另一次執行預算。
