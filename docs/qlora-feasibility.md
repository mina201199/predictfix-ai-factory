# QLoRA 可行性：GTX 1050 Ti 能不能微調 Gemma 4 E2B

## 結論

GTX 1050 Ti 已使用 **Gemma 4 E2B 官方預訓練權重完成 3 步 QLoRA**。採 CPU embedding、GPU nf4 decoder 的拆分方式，序列長度為 801／895／897 tokens；PyTorch 配置記憶體峰值為 **1,764 MiB**，保留記憶體峰值為 **2,128 MiB**。這證明本機可完成此訓練路徑，尚未評估微調後的選段準確率。

2026-10-19 經同意下載 10,246,621,918 bytes 官方權重並驗證 SHA-256：`2db5482b20d746879bb3ef79b5203e9075a2e2b98f54ec7c2f281c1477ddc550`。模型 revision 固定為 `3e22461f65e89153144f8adb70e3b8c2cc9845a7`，文字權重載入檢查沒有缺失或尺寸不符。

官方權重結果另存 [qlora-pretrained-20261019.json](../artifacts/qlora-pretrained-20261019.json)。歷史隨機權重報告保留在原檔，當日 kernel 重測另存 [qlora-feasibility-recheck-20261019.json](../artifacts/qlora-feasibility-recheck-20261019.json)。

本文只記錄「能否完成」與「顯存」，不記錄速度：測試時本機同時有其他工作，計時不可信。歷史原始資料見 [qlora-feasibility.json](../artifacts/qlora-feasibility.json)。

## 測試環境

- GPU：NVIDIA GeForce GTX 1050 Ti，4 GB，Pascal，compute capability 6.1，driver 582.66，WDDM（同時接螢幕）
- CPU：i5-14500；記憶體 64 GB；Windows 10
- 獨立環境：`.runtime/qlora-env`（已在 `.gitignore`），不動專案 `.venv`。直接相依見 [qlora-requirements.txt](../training/qlora-requirements.txt)，完整版本見 [qlora-environment-lock.txt](../training/qlora-environment-lock.txt)
- 主要版本：torch 2.14.1+cu126、transformers 5.20.0、peft 0.21.2、bitsandbytes 0.50.2、accelerate 1.15.0

## 逐項結果

| 檢查 | 結果 | 證據 |
|---|---|---|
| torch 支援 sm_61 | 可以 | `torch.cuda.get_arch_list()` 含 `sm_61` |
| bitsandbytes nf4 在 sm_61 | 可以 | 4 種組合（compute fp32／fp16 × 有無 double quant）前向與反向皆完成，輸出與反量化權重的參考計算一致 |
| Gemma 4 E2B 是否 gated | 不需要同意授權 | Hugging Face API 回傳 `gated: false`，授權 Apache-2.0，不需要 token |
| 迷你 Gemma 4 + nf4 + LoRA 訓練 3 步 | 可以 | 結構比照 E2B 的隨機小模型，PEFT 成功包住 `Linear4bit`，loss 有限 |
| 同尺寸隨機 E2B，QLoRA，短序列 3 步 | 完成 | 172–181 tokens，PyTorch 配置峰值最高 1,303 MiB |
| 同尺寸隨機 E2B，v2 題庫長度 | 完成 | 801–897 tokens，PyTorch 配置峰值最高 1,764 MiB |
| 同尺寸隨機 E2B，一般 LoRA（fp16） | 型別錯誤已修正；觀察到 1 步完成，後續中止 | 801 tokens，配置峰值 4,046 MiB、保留峰值 4,268 MiB；中止是為了釋放 GPU，不是 OOM，也不是完整 3 步通過 |
| 同尺寸隨機 E2B，一般 LoRA（fp32） | 完成，但超出實體顯存容量 | PyTorch 配置峰值最高 7,465 MiB；Windows WDDM 可能使用共用記憶體，不能稱為全程放在 4 GB 顯存內 |
| 官方預訓練 E2B，v2 題庫長度 | 完成 3 步 QLoRA | 801／895／897 tokens；loss 為 4.5377／1.4153／0.0384，配置峰值最高 1,764 MiB |

fp16 中止紀錄另存 [qlora-fp16-recheck-20261019.json](../artifacts/qlora-fp16-recheck-20261019.json)，步驟數字轉錄自停止前的實際 stdout。它與官方 QLoRA 的權重、完成步數不同，不當作同條件成效比較。

配置與保留記憶體是 PyTorch allocator 指標，不含全部 CUDA context、桌面或其他服務。官方測試開始前 `nvidia-smi` 顯示其他程式已占用 2,713 MiB，且另有 llama-cuda 服務。Windows WDDM 可能使用共用記憶體，因此不能把配置峰值直接當作獨占實體顯存需求，也不使用本次速度作效能比較。

## 為什麼 embedding 要留在 CPU

Gemma 4 E2B 的文字部分約 46.3 億參數，但其中 23.5 億是 Per-Layer Embeddings（PLE）表，4.0 億是一般詞嵌入，真正的 decoder 線性層只有 18.8 億。bitsandbytes 只量化線性層、不量化 embedding，所以：

| 情境 | 權重大小 |
|---|---|
| fp32 LoRA，全部放 GPU | 17.24 GiB |
| fp16 LoRA，全部放 GPU | 8.62 GiB |
| fp16 LoRA，embedding 放 CPU | 3.50 GiB |
| QLoRA（bitsandbytes 預設，embedding fp16 在 GPU） | 6.06 GiB |
| QLoRA，embedding 放 CPU | 0.93 GiB |

這些數字由官方 `config.json` 在 meta device 建模計算，只算權重，未含 CUDA context、中間張量與 optimizer。GPU 總共 4 GB；CUDA 初始化前 `nvidia-smi` 曾顯示約 1.2 GB 占用，初始化後 CUDA API 回報約 3.3 GB 可用。兩者的查詢時間與 WDDM 計帳方式不同，不能直接相減比較。

transformers 的 `device_map` 雖然可以把 embedding 標成 `cpu`，但 accelerate 會在 forward 時把權重搬上 GPU，對 4.7 GB 的 PLE 表沒有幫助（已用迷你模型確認：被標成 `cpu` 的模組參數變成 meta device，由 hook 在執行時搬移）。因此腳本改為手動拆分：

1. 以 bf16 在 CPU 載入文字解碼器（`key_mapping` 只取 `model.language_model.*`，不載入視覺與音訊）。
2. 每一層 decoder 的 `nn.Linear` 換成 bitsandbytes `Linear4bit`（nf4、double quant、compute dtype fp32）後搬上 GPU。
3. `embed_tokens`、PLE 表與共用權重的 `lm_head` 留在 CPU；查表結果再送上 GPU，以 `inputs_embeds` 與 `per_layer_inputs` 傳入。
4. 詞彙表有 262,144 個，只對答案 token 在 CPU 計算 logits 與 loss。

compute dtype 選 fp32，因為 Pascal 沒有原生 bf16（`is_bf16_supported(including_emulation=False)` 為 False）。fp16 在這張卡上的速度本次沒有量測。

## 限制與不確定

- 只跑 3 步，驗證「能跑、放得下」，不代表訓練效果。正式訓練要另外規劃步數、驗證與對照組。
- 沒有速度資料。Pascal 沒有 Tensor Core，CPU 端查表與 lm_head 也會拖慢；實際一輪訓練要多久，需要在沒有其他工作時另外量測。
- 手動拆分不是 Hugging Face `Trainer` 的標準路徑。正式訓練若沿用，需要同樣的拆分與 adapter 存取流程，並重新驗證存回的 adapter 能被推論端載入。
- 桌面占用的顯存會隨開啟的程式變動，顯存餘裕以實測當下為準。

## 若改用雲端 T4

Kaggle 與 Colab 的免費 T4 有 16 GB 顯存、支援 fp16 Tensor Core。依上表估算，bitsandbytes 標準 QLoRA 路徑（embedding 也在 GPU）權重約 6.06 GiB，應可直接用 `from_pretrained(quantization_config=...)` 訓練，不需要手動拆分。這部分本次**未實測**。使用時：

- 權重不需 token（未 gated）；若改用其他需要授權的模型，token 放平台的 Secrets，不寫進 notebook。
- 只上傳 `training/selection-dataset-v2.json` 這類虛構資料，不上傳 `.env`、資料庫或任何現場紀錄。
- 免費額度有使用時數與閒置中斷限制，實際機型與額度以平台當下公告為準（本次未登入確認），需要定期存 checkpoint。

## 重跑

```powershell
uv venv .runtime/qlora-env --python 3.12
uv pip install --python .runtime/qlora-env/Scripts/python.exe "torch==2.14.1+cu126" --index-url https://download.pytorch.org/whl/cu126
uv pip install --python .runtime/qlora-env/Scripts/python.exe -r training/qlora-requirements.txt
$env:PYTHONIOENCODING='utf-8'
.\.runtime\qlora-env\Scripts\python.exe scripts/check_qlora_feasibility.py env
.\.runtime\qlora-env\Scripts\python.exe scripts/check_qlora_feasibility.py kernels
.\.runtime\qlora-env\Scripts\python.exe scripts/check_qlora_feasibility.py tiny
.\.runtime\qlora-env\Scripts\python.exe scripts/check_qlora_feasibility.py estimate
# 第一次需加 --allow-download，會下載約 10.25 GB 權重到 .runtime/hf-cache
.\.runtime\qlora-env\Scripts\python.exe scripts/check_qlora_feasibility.py real --mode qlora --allow-download
.\.runtime\qlora-env\Scripts\python.exe scripts/check_qlora_feasibility.py real --mode fp16
.\.runtime\qlora-env\Scripts\python.exe scripts/check_qlora_feasibility.py real --mode fp32
```

未加 `--allow-download` 時只使用本機快取，避免未經同意就下載大型權重。

本次 worktree 使用主專案既有的獨立環境與快取。要重跑官方權重測試，可在此 worktree 執行以下指令，每次使用新的報告檔名：

```powershell
$env:HF_HUB_OFFLINE='1'
../predictfix-ai-factory/.runtime/qlora-env/Scripts/python.exe scripts/check_qlora_feasibility.py real --mode qlora --weights pretrained --steps 3 --seq-len 1024 --rank 8 --dataset training/selection-dataset-v2.json --label v2len --runtime-dir ../predictfix-ai-factory/.runtime --report artifacts/qlora-pretrained-new-run.json
```

開啟產出的 JSON，`real_qlora_pretrained_v2len.status` 應為 `completed`、`weights` 為 `pretrained`，`steps` 有 3 筆；`checkpoint_loading.missing_keys` 與 `mismatched_keys` 應為空清單。資料雜湊應對應目前 v2 題庫的 LF 正規化 UTF-8 內容。3 筆 loss 有限只代表此測試可執行，不能推論維修效果。
