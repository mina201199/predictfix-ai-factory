# 本機部署與 LoRA 實驗

## 部署範圍

`scripts/deploy_local.py` 建立具有逐檔 SHA-256 的版本快照，以獨立 SQLite 在 localhost 啟動正式資料模式。此版本不載入展示資料、不提供快速登入；LLM 暫停使用，維持候選來源降級功能。原本 8082 Demo 與 8083 正式資料服務不受影響。

```powershell
.\.venv\Scripts\python.exe scripts/deploy_local.py --port 8084
```

入口為 <http://127.0.0.1:8084/>。首次帳密只保存於未納入 Git 的 `.runtime/local-deploy/data/initial-access.json`；不可分享此檔案。資料庫、快照與日誌放在 `.runtime/local-deploy/`。已占用的服務不會被覆蓋，重跑需改用空閒連接埠。

結果見 [本機部署報告](../artifacts/local-deployment-report.json)。這是本機原生 Python 部署，不是 Docker、公網或 HTTPS 上線。Docker 引擎目前無法連線，PostgreSQL／TLS 與異地還原仍未驗證。

## 訓練目標與資料

本實驗讓 Qwen3-0.6B 依「問題＋候選段落」輸出相關段落 ID；無相關來源時回傳空清單。保留應用程式的引用檢查、角色限制與人工核准，不以微調模型直接派工或判定復機。

[資料集](../training/selection-dataset.json) 共 44 題，皆為本專案原創虛構文字，沒有現場紀錄、OEM 手冊、帳號或個資。24 題訓練、8 題驗證、12 題測試。依 11 個來源主題分組，不同 split 不共用主題；同主題的正例、改寫、無答案與文件注入情境留在同一組。段落順序以固定亂數種子打散，答案 ID 不固定在第一個位置。

這是少量、自行標註的流程實驗；分組不代表獨立專家驗收或涵蓋真實工廠問題。來源主題不同仍共用相似寫作模板，不能宣稱已證明跨廠泛化。

## 重跑

使用獨立環境，避免改動 Demo 的依賴。PyTorch 從 [官方 CPU 套件來源](https://pytorch.org/get-started/locally/) 安裝；LoRA 使用 [PEFT](https://huggingface.co/docs/peft/quicktour)。

```powershell
.\.venv\Scripts\python.exe -m venv .runtime/lora-env
.\.runtime\lora-env\Scripts\python.exe -m pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
.\.runtime\lora-env\Scripts\python.exe -m pip install -r training/requirements.txt
.\.venv\Scripts\python.exe scripts/prepare_lora_data.py
.\.runtime\lora-env\Scripts\python.exe scripts/train_lora.py --steps 12 --threads 2 --run-id cpu-smoke-v1
```

第一次會下載 [官方 Qwen3-0.6B Hugging Face 權重](https://huggingface.co/Qwen/Qwen3-0.6B)，不使用既有 GGUF 作訓練輸入。快取及 adapter 都放在未納入 Git 的 `.runtime/`。此設定使用 CPU float32、LoRA rank 4、q_proj/v_proj、batch 1、固定 seed 42，僅訓練 assistant 回應的 token。不是 QLoRA，也不是完整參數微調。資料超過長度限制時停止，不靜默截斷。

首次實測的來源 revision 保存於 [模型版本](../training/model-revision.json)；精確重跑時在訓練指令加入 `--revision c1899de289a04d12100db370d81485cdf75e47ca`，並使用新的 run-id。訓練只使用 train split，固定執行 12 步，不依本次測試結果改參數。

報告記錄模型 revision、依賴版本、資料集雜湊、訓練參數、每步 loss／耗時／程序記憶體、adapter 雜湊與逐題輸出。重跑使用新的 run-id，先保留上一份報告；若同名歷史報告存在則停止，避免覆蓋。

## 如何解讀結果

原模型與 LoRA 模型使用相同問題、來源、chat template 與 greedy decoding，關閉 thinking，沒有 JSON grammar 約束，以測量模型本身的格式與選取能力。驗證與測試結果不拿來選本次 checkpoint 或調整超參數。

**與運行中服務的差異：** 既有 llama.cpp 路徑會要求 JSON schema。本實驗使用 Transformers、未加 grammar，嚴格拒絕 Markdown 包住的 JSON；因此原模型格式錯誤可能造成分數為零，不能將它解讀為現有服務的正確率為零，或將格式改善直接稱為維修能力提升。

- Exact match：格式合法且選取的 ID 集合完全符合標註。
- Precision／Recall：僅計算有效 ID 的段落選取；無效格式仍記為錯誤，正例計入漏選。
- 資料不足正確率：無答案题需輸出有效空陣列。
- 文件注入 exact match：遇到文件內指令，仍應選取真正相關段落；不是全面安全認證。
- 平均延遲：同機 CPU 實測，包含模型生成，不代表伺服器負載測試。

另提供字串相似度比較器，明確標示為 SequenceMatcher；不是應用程式 TF-IDF/BM25 的檢索評估。原有檢索結果仍見 [檢索報告](../artifacts/retrieval-eval-report.json)，不能與本實驗不同題目、不同指標直接比較。

LoRA 結果尚未經量化後 serving、安全回歸或專家標註驗證，因此不自動替換目前運行的模型。結果變差或持平也保留於 README，不將訓練 loss 下降解讀為效果提升。

## 獨立 adapter 推論服務

完成訓練後，可重新載入保存的 adapter，在獨立的 localhost 8085 提供 `/healthz` 與 `/predict`。此服務使用 CPU float32，沒有接入 8082／8083／8084 的 LLM 路徑；這是訓練成品的載入與 API 驗證，尚未通過正式 serving 安全驗收。

```powershell
.\.runtime\lora-env\Scripts\python.exe scripts/serve_lora_experiment.py --port 8085
# 另開終端機
.\.venv\Scripts\python.exe scripts/verify_lora_serving.py
```

啟動先核對 adapter SHA-256 與模型 revision，使用本機已下載快取，不自動下載另一個模型。推論限制輸入大小、候選數、token 長度與輸出 token 數。驗證工具檢查重新載入後與訓練報告同一題的原始輸出一致，並拒絕空候選輸入；此結果不另算新增測試題命中率。

## 2026-10-20 訓練相依安全更新

CPU 安裝設定已更新為 PyTorch 2.14.1、Transformers 5.20.0、PEFT 0.21.2、Accelerate 1.15.0 與 setuptools 83.0.0，以排除舊版本的已知安全公告。`training/environment-lock.txt` 是新建隔離 CPU 環境的版本固定清單。既有環境不會因修改安裝檔而自動更新，請建立新環境驗證後再切換。

已用隨機微型 Qwen3 CPU 模型確認有限 loss／梯度、一次 optimizer step、safetensors adapter 保存與重新載入輸出一致；未下載正式權重、未重跑品質評估，也不會改寫歷史成果。可在新訓練環境執行 `python tests/lora_runtime_scenario.py --report .runtime/lora-runtime-new.json` 重跑，報告路徑必須尚未存在。

安全公告：[Transformers 模型載入](https://github.com/advisories/GHSA-29pf-2h5f-8g72)、[Accelerate 權重路徑](https://github.com/advisories/GHSA-4j2p-28q2-5m79)、[setuptools 路徑穿越](https://github.com/advisories/GHSA-5rjg-fvgr-3xxf)。
