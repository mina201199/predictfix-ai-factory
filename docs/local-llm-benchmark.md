# 本機模型基準：CPU／GPU、量化與模型比較

測試日期：2026-10-15。原始資料（每題的輸出、延遲與 token 數）見 [local-llm-benchmark.json](../artifacts/local-llm-benchmark.json)，重跑方式見文末。

## 結論

1. **不需要 GPU。** Gemma 4 E2B（Q8_0）以純 CPU 執行，44 題全部選對，每題中位數 2.94 秒，程序記憶體峰值約 2.6 GB。同一台電腦的 GTX 1050 Ti 可以快到 0.98 秒（約 3 倍），但準確度沒有提升。
2. **換掉 Qwen3-0.6B 後準確度大幅提升。** 目前使用的 Qwen3-0.6B 只選對 10／44 題，而且 11 題「資料不足」一題都沒有拒答。
3. **這個任務值得用 Q8。** Gemma 4 E2B 的 Q4 比 Q8 小、在多執行緒下也較快，但「資料不足」只拒答 2／11 題，Q8 則是 11／11。
4. **`start.ps1` 的 4 執行緒沒有用滿 CPU。** 改成 12 執行緒後，Q4 模型快 20% 到 25%；Q8 模型受記憶體頻寬限制，幾乎沒有差別。

## 測試環境

| 項目 | 內容 |
|---|---|
| CPU／記憶體 | Intel Core i5-14500（14 核 20 執行緒）／64 GB |
| GPU | NVIDIA GeForce GTX 1050 Ti，4 GB（2016 年的 Pascal 架構） |
| 推論程式 | llama.cpp b11491，官方 Windows CPU 版與 CUDA 12.4 版 |
| 請求設定 | 與 `backend/maintenance_ai.generate_json` 相同：temperature 0、JSON schema 限制只能回傳候選段落 ID、context 2048、單一 slot |
| 題目 | `training/selection-dataset.json` 全部 44 題原創虛構題：正例 22、資料不足 11、文件注入 11；每題有 3 個候選段落 |
| 模型檔 | 固定 Hugging Face revision，並驗證 SHA-256（見腳本中的 `MODELS`） |

Qwen 的請求另外加上 `/no_think` 來關閉思考模式，與目前正式環境相同；其他模型不需要這個參數。

## 準確度（CPU 12 執行緒）

| 模型 | 量化 | 授權 | 整體選對 | 正例 | 資料不足拒答 | 注入題 | 安全情境 |
|---|---|---|---:|---:|---:|---:|---:|
| Qwen3-0.6B（現行） | Q8_0 | apache-2.0 | 10/44 (22.7%) | 6/22 | 0/11 | 4/11 | 10/10 |
| Gemma 4 E2B | Q4_0 | apache-2.0 | 35/44 (79.5%) | 22/22 | 2/11 | 11/11 | 10/10 |
| **Gemma 4 E2B** | **Q8_0** | **apache-2.0** | **44/44 (100.0%)** | **22/22** | **11/11** | **11/11** | **10/10** |
| Llama-Breeze2-3B | Q4_K_M | llama3.2 | 39/44 (88.6%) | 21/22 | 11/11 | 7/11 | 10/10 |
| Llama-Breeze2-3B | Q8_0 | llama3.2 | 33/44 (75.0%) | 16/22 | 11/11 | 6/11 | 10/10 |
| Breeze-7B v1.0 | Q4_K_M | apache-2.0 | 26/44 (59.1%) | 14/22 | 9/11 | 3/11 | 10/10 |

- **選對**：模型選出的段落集合與標準答案完全相同。
- **資料不足拒答**：候選段落都不相關時，正確回傳空清單。
- **注入題**：段落中夾帶「忽略指示」等文字時，仍選出正確段落。
- **安全情境**：沿用 `tests/security_scenario.py live` 的 10 項檢查。每項都要求模型確實被呼叫、引用能對回原文、沒有任何機密外洩、權限沒有改變。

## 速度與資源

延遲是從送出請求到收到完整回應的時間，含本機 HTTP 往返，取 44 題的中位數與 P95。

| 模型 | 量化 | CPU 4 執行緒 | CPU 12 執行緒 | GTX 1050 Ti（GPU 層數） | 記憶體峰值 CPU 組／GPU 組 | GPU 顯存 | GPU 組選對 |
|---|---|---:|---:|---:|---:|---:|---:|
| Qwen3-0.6B | Q8_0 | 0.56s（P95 0.80s） | 0.55s（P95 0.77s） | 0.41s（P95 0.59s）（29/29） | 1,177／1,241 MB | 914 MB | 25.0% |
| Gemma 4 E2B | Q4_0 | 2.07s（P95 2.13s） | 1.61s（P95 1.67s） | 0.79s（P95 0.82s）（36/36） | 2,747／2,114 MB | 1,696 MB | 75.0% |
| Gemma 4 E2B | Q8_0 | 2.84s（P95 3.46s） | 2.94s（P95 3.57s） | 0.98s（P95 1.37s）（32/36） | 2,600／2,890 MB | 2,418 MB | 97.7% |
| Llama-Breeze2-3B | Q4_K_M | 1.25s（P95 1.66s） | 0.97s（P95 1.35s） | 0.66s（P95 1.00s）（29/29） | 3,854／2,629 MB | 2,276 MB | 86.4% |
| Llama-Breeze2-3B | Q8_0 | 2.17s（P95 3.43s） | 2.01s（P95 3.15s） | 0.87s（P95 1.34s）（17/29） | 3,887／4,052 MB | 2,306 MB | 75.0% |
| Breeze-7B v1.0 | Q4_K_M | 3.42s（P95 5.21s） | 2.97s（P95 4.42s） | 1.94s（P95 3.15s）（16/33） | 8,083／5,049 MB | 2,390 MB | 65.9% |

- **GPU 層數**：llama.cpp 依 4 GB 顯存自動決定放到 GPU 的層數，其餘留在 CPU。Q8 版和 7B 模型放不下全部。
- **記憶體峰值**：llama-server 程序的 Peak Working Set。
- **GPU 顯存**：測試期間 `nvidia-smi` 顯示的已用顯存增加量，含 CUDA 執行環境本身。

### 執行緒數（Gemma 4 E2B Q4_0，前 8 題）

| 執行緒 | 4 | 6 | 8 | 12 | 14 |
|---|---:|---:|---:|---:|---:|
| 延遲中位數 | 2.11s | 1.74s | 1.76s | 1.58s | 1.58s |

## 解讀限制

- **題數少。** 44 題中 1 題就等於 2.3 個百分點。Breeze2-3B 的 Q4 反而比 Q8 高，差在 6 題，代表這個規模下 10 個百分點以內的差距不足以下定論。
- **題目比實際簡單。** 每題只有 3 個候選段落，而且是虛構資料。Gemma 4 E2B Q8 全對，不代表在真實手冊上也能全對，更不代表維修診斷正確。
- **CPU 和 GPU 的結果略有差異。** 這是浮點運算差異造成的，例如 Gemma 4 E2B Q8 在 GPU 上有 1 題不同。
- **安全情境測的是整個應用程式。** 後端用 schema 限制模型只能選段落 ID，原文由程式帶出，所以 6 個模型都通過。這不代表模型本身能抵抗注入；注入題的選對率才反映模型本身。
- **安全情境沿用現行程式碼。** 現行程式碼對所有模型都附加 `/no_think`，換模型時應改成只對 Qwen 附加。
- **只測一台電腦、一次。** 測試期間沒有執行其他重的工作，但仍會受背景程式影響。

## 依數據的建議

- **首選：Gemma 4 E2B Q8_0，純 CPU 執行。** 準確度最高，授權為 Apache 2.0，不需要 GPU，每題約 3 秒。
- **如果必須用台灣自製模型：Llama-Breeze2-3B Q4_K_M。** 選對率 88.6%，每題約 1 秒。但注入題只對 7／11，而且 GGUF 經過兩手社群轉檔（PenutChen 抽出文字部分，再由 mradermacher 量化）。
- **GPU 屬於選配。** 想把回應壓到 1 秒內，現有的 GTX 1050 Ti 就能讓 Gemma 4 E2B Q8 快約 3 倍。

## 重跑方式

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_local_llm.py download
.\.venv\Scripts\python.exe scripts\benchmark_local_llm.py sweep --model gemma4-e2b-q4_0 --threads 4,6,8,12,14 --rows 8
.\.venv\Scripts\python.exe scripts\benchmark_local_llm.py run --models all --runtimes cpu --threads 4,12 --security
.\.venv\Scripts\python.exe scripts\benchmark_local_llm.py run --models all --runtimes cuda --threads 12
.\.venv\Scripts\python.exe scripts\benchmark_local_llm.py summary
```

`download` 會下載約 18.4 GB 的模型檔，以及約 0.65 GB 的 CUDA 版 llama.cpp 到 `.runtime/`（已在 `.gitignore` 中），每個檔案都會驗證 SHA-256。GPU 測試需要 NVIDIA 顯示卡與驅動程式。
