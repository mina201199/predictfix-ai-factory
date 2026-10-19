# QLoRA 可行性：GTX 1050 Ti 能不能微調 Gemma 4 E2B

## 結論

GTX 1050 Ti 已完成 bitsandbytes nf4 前向／反向檢查，以及依官方設定建立的同尺寸隨機模型 3 步 QLoRA 測試。**官方預訓練權重尚未下載，也未完成實測**，因此目前只能證明此拆分方式的運算路徑與記憶體可行，不能宣稱模型微調有效。

2026-10-19 核對快取時僅有設定與 tokenizer，沒有 safetensors 權重。正式權重測試仍需約 10.25 GB 下載；既有報告保留在原檔，當日 kernel 重測另存 `artifacts/qlora-feasibility-recheck-20261019.json`。

本文只記錄「能否完成」與「顯存」，不記錄速度：測試時本機同時有其他工作，計時不可信。原始數據見 [qlora-feasibility.json](../artifacts/qlora-feasibility.json)。

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
| 同尺寸隨機 E2B，一般 LoRA（fp16） | 失敗，尚待修正後重測 | `expected mat1 and mat2 to have the same dtype`；不能解讀為顯存不足 |
| 同尺寸隨機 E2B，一般 LoRA（fp32） | 完成，但超出實體顯存容量 | PyTorch 配置峰值最高 7,465 MiB；Windows WDDM 可能使用共用記憶體，不能稱為全程放在 4 GB 顯存內 |
| 官方預訓練 E2B 權重 | 尚未測試 | 快取無權重；不可將隨機初始化結果當作預訓練模型微調結果 |

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
- 沒有速度數據。Pascal 沒有 Tensor Core，CPU 端查表與 lm_head 也會拖慢；實際一輪訓練要多久，需要在沒有其他工作時另外量測。
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
