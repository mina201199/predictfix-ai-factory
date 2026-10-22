# 模型選型與合規

查證日期：2026-10-16。標示「未查證」的項目是查不到可靠來源或尚未實測，不代表已確認。

2026-10-21 狀態整理：現行預設仍為 Gemma Q8_0。Gemma QLoRA 已另完成 GPU 訓練與新題評估，但尚不採用；見 [最新數據與界線](interview-readiness.md)。以下外部來源、授權及政策的查證日期仍為 2026-10-16，本輪未更新法律查證，不能據此保證個別案場合規。

## 結論

- **現用模型：Gemma 4 E2B Q8_0。** Google 開發、Apache 2.0 授權，以 llama.cpp 在本機 CPU 執行，不需要 GPU。
- **Qwen3-0.6B 已於 2026-10-15 淘汰。** 原因有二：44 題段落選取基準只選對 22.7%；Qwen 由中國阿里巴巴開發，在台灣案場有合規疑慮。
- **台灣自製備案：Llama-Breeze2-3B Q4_K_M。** 聯發創新基地開發，選對 88.6%，但注入題較弱，GGUF 也不是官方發行。

## 現用模型

| 項目 | 內容 | 依據 |
|---|---|---|
| 模型 | `gemma-4-E2B-it`（指令微調版）GGUF，Q8_0 量化 | `scripts/setup_local_llm.py`、`start.ps1` |
| 開發者 | Google（美國）；模型卡列出的作者為 Google DeepMind | [Hugging Face 模型卡](https://huggingface.co/google/gemma-4-E2B-it) |
| 授權 | Apache 2.0 | 模型卡與 [Gemma 4 授權頁](https://ai.google.dev/gemma/docs/gemma_4_license) |
| 檔案來源 | [`ggml-org/gemma-4-E2B-it-GGUF`](https://huggingface.co/ggml-org/gemma-4-E2B-it-GGUF)，由 llama.cpp 所屬的 ggml-org 從 `google/gemma-4-E2B-it` 轉檔；固定 revision `b4243c1`，下載後驗證 SHA-256 | `scripts/setup_local_llm.py` |
| 推論程式 | llama.cpp b11491 官方 Windows CPU 版，`llama-server` 只聽 `127.0.0.1:8081`；另可改用 Ollama（`gemma4:e2b-it-q8_0`） | `start.ps1`、`compose.yaml` |
| 能否完全離線 | **設計上可以，但未查證。** 模型檔與執行檔下載後都放在 `.runtime/`，推論請求只送往本機；前端也沒有載入外部 CDN。首次安裝需要連網下載，尚未在斷網環境實測整套流程。 | `start.ps1`、`*.html` |
| 資料不出廠 | 本機模型路徑不會把工單或手冊送出。例外是選配的 OpenAI 整合：設定 `OPENAI_API_KEY` 才會呼叫 `api.openai.com`，此時問題文字會送出；手冊原文受 `OPENAI_DOCUMENT_ACCESS` 控制，預設 `none`。要確保資料不出廠，部署時讓 `OPENAI_API_KEY` 留空，或設 `OPENAI_ENABLED=0`。 | `backend/openai_runtime.py`、`.env.example` |

## 為什麼換掉 Qwen3-0.6B

### 1. 準確度

數據來自 [本機模型基準](local-llm-benchmark.md)：44 題原創虛構題，CPU 12 執行緒，2026-10-15 測試。

| 模型 | 整體選對 | 正例 | 資料不足拒答 | 注入題 | 延遲中位數 | 記憶體峰值 |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3-0.6B Q8_0（已淘汰） | 10/44（22.7%） | 6/22 | 0/11 | 4/11 | 0.55 秒 | 1,177 MB |
| **Gemma 4 E2B Q8_0（現用）** | **44/44（100%）** | **22/22** | **11/11** | **11/11** | **2.94 秒** | **2,600 MB** |

Qwen 最大的問題是候選段落都不相關時一題都沒拒答，代表沒有依據的問題也會被選出段落當作來源。換成 Gemma 的代價是每題慢約 2.4 秒、記憶體多約 1.4 GB；以維修查詢來說，每題約 3 秒仍可接受。

### 2. 台灣案場合規

Qwen3 由阿里巴巴的 Qwen 團隊開發，2025-04-29 發布（[Simon Willison 的發布紀錄](https://simonwillison.net/2025/Apr/29/qwen-3/)）。它本身是 Apache 2.0 授權，**問題在開發來源，不在授權條款**。專題指導老師的建議是，在台灣案場盡量不要使用中國開發的模型。

已查證的公部門規範：

- 2025-01-31 數位發展部提醒公務機關與關鍵基礎設施限制使用 DeepSeek；2025-02-03 行政院宣布公務機關原則全面禁用 DeepSeek AI 服務，依據是 2019 年的「各機關對危害國家資通安全產品限制使用原則」（[中央社](https://cna.com.tw/news/aipl/202502030237.aspx)）。
- 教育部說明，依該原則，公務機關及公立學校不得採購或使用大陸廠牌資通訊產品，包含軟體、硬體及服務（[工商時報](https://www.ctee.com.tw/news/20250206701025-431401)）。

未查證：

- 上述規範目前的最新版本。有單一來源提到原則已改依《危害國家資通安全產品審查辦法》辦理，尚未向主管機關確認。
- 下載後離線執行的開源權重，是否屬於「大陸廠牌資通訊產品」。
- 民間工廠是否有一般性的禁止規定。

本專案的做法是不等法規釐清，直接不使用中國開發的模型，避免在客戶的資安或採購審查時成為爭點。

## 台灣自製備案：Llama-Breeze2-3B

| 項目 | 內容 |
|---|---|
| 開發者 | 聯發創新基地（MediaTek Research，台灣）；Breeze 2 系列於 2025-01-24 發布，以 Meta Llama 3.2 為基礎，加強繁體中文（[MR-Models](https://github.com/mtkresearch/MR-Models)、[官方說明](https://www.mediatek.com/zh-tw/tek-talk-blogs/%E8%81%AF%E7%99%BC%E5%89%B5%E6%96%B0%E5%9F%BA%E5%9C%B0%E5%85%A8%E9%9D%A2%E9%96%8B%E6%BA%90mediatek-research-breeze-2%E5%A4%9A%E6%A8%A1%E6%85%8B%E5%9F%BA%E7%A4%8E%E6%A8%A1%E5%9E%8B%E7%BE%A4%E5%AF%A6%E7%8F%BE%E7%B9%81%E4%B8%ADai%E5%8A%A9%E7%90%86)） |
| 授權 | Llama 3.2 Community License（Meta）。條款比 Apache 2.0 多，正式採用前需請法務確認商用義務；本文未逐條查證。 |
| 基準（Q4_K_M） | 選對 39/44（88.6%）、正例 21/22、資料不足拒答 11/11、注入題 7/11；延遲中位數 0.97 秒；記憶體峰值 3,854 MB |

注意事項：

- **注入題只對 7/11**，低於 Gemma 的 11/11。後端仍用 JSON schema 限制模型只能選段落 ID，所以應用層的 10 項安全情境都通過，但模型本身較容易被文件中的指令帶偏。
- **GGUF 經社群二次轉檔。** 官方的 [`MediaTek-Research/Llama-Breeze2-3B-Instruct`](https://huggingface.co/MediaTek-Research/Llama-Breeze2-3B-Instruct) 是多模態模型；社群使用者 PenutChen 抽出文字部分（[`PenutChen/Llama-Breeze2-3B-Instruct-Text`](https://huggingface.co/PenutChen/Llama-Breeze2-3B-Instruct-Text)），再由 mradermacher 量化成 GGUF（[`mradermacher/Llama-Breeze2-3B-Instruct-Text-GGUF`](https://huggingface.co/mradermacher/Llama-Breeze2-3B-Instruct-Text-GGUF)）。固定 revision 和 SHA-256 只能保證檔案一致，不能保證轉檔正確。
- **Q8_0 反而只選對 33/44（75.0%）。** 題數少，10 個百分點內的差距不足以判斷高低，切換前要重跑基準。

客戶明確要求台灣自製模型時才切換；切換前要重跑 `scripts/benchmark_local_llm.py` 與 `scripts/run_security_checks.py --live`。同屬聯發創新基地的 Breeze-7B v1.0（Apache 2.0）只選對 26/44（59.1%），記憶體峰值約 8 GB，不列為備案。2026-02 發布的 MR Breeze 3 系列尚未納入基準，型態與授權未查證。

## 選型檢核清單

之後換模型時，逐項確認：

1. **來源**：開發者與所屬國家；權重是否由原開發者或可信組織發布；轉檔經過幾手。
2. **授權**：授權類型、商用限制與標示義務，是否需要法務確認。
3. **離線**：下載後能否在本機執行、不需連網；推論服務是否只聽本機位址；最好實際斷網測一次。
4. **資安測試**：`scripts/run_security_checks.py --live` 全數通過，並確認每個探測都由新模型回應；注入題選對率。
5. **基準結果**：`scripts/benchmark_local_llm.py run` 的整體選對、資料不足拒答、注入題、延遲與記憶體，與現用模型比較。
6. **固定版本**：把 revision 與 SHA-256 寫進 `scripts/setup_local_llm.py`，避免下載到未測試的檔案。

| 檢核項目 | Gemma 4 E2B Q8_0 | Llama-Breeze2-3B Q4_K_M | Qwen3-0.6B Q8_0 |
|---|---|---|---|
| 來源 | Google（美國），GGUF 由 ggml-org 轉檔 | 聯發創新基地（台灣），GGUF 經兩手社群轉檔 | 阿里巴巴（中國），官方 GGUF |
| 授權 | Apache 2.0 | Llama 3.2 Community License | Apache 2.0 |
| 離線 | 可本機執行；斷網未實測 | 可本機執行；斷網未實測 | 可本機執行；斷網未實測 |
| 資安測試 | 45/45（2026-10-15 live） | 基準中的 10 項安全情境通過；整套 45 項未測 | 45/45（2026-10-06 live，歷史紀錄） |
| 基準結果 | 44/44（100%） | 39/44（88.6%），注入 7/11 | 10/44（22.7%），資料不足拒答 0/11 |
| 結論 | **現用** | 台灣自製備案 | **已淘汰**，只作對照組 |

## 仍提到 Qwen 的地方

以下保留是為了留下歷史紀錄，不代表 Qwen 仍是選項：

| 位置 | 為什麼保留 |
|---|---|
| [開發紀錄](development-history.md)、[安全測試](security-testing.md) 的 2026-10-06／07／14 段落 | 當時的實際紀錄，已在文中標明淘汰 |
| [本機模型基準](local-llm-benchmark.md)、`scripts/benchmark_local_llm.py` | Qwen 是換模型時的對照組，保留才能重現比較 |
| `artifacts/local-llm-benchmark.json`、`llm-smoke-report.json`、`knowledge-live-smoke.json`、`interview-readiness-report.json` | 當時產生的原始證據，修改內容等於竄改紀錄 |
| `tests/test_local_llm_request.py` | 回歸測試，確保 Qwen 專用的 `/no_think` 不會再送給現用模型 |
| README 的歷史 LoRA 段落、[LoRA 實驗](lora-training.md)、`training/model-revision.json` | 保留 Qwen3-0.6B 的歷史 CPU 實驗；Gemma QLoRA 結果另存，兩者都不代表現用 Q8_0 服務已微調 |

## 面試時怎麼回答「為什麼選這個模型」

1. **準確度**：同一組 44 題，Gemma 4 E2B Q8 全對，原本的 Qwen3-0.6B 只對 22.7%，而且不會拒答資料不足的問題。
2. **來源與採購考量**：依既有模型紀錄改用 Google 的 Gemma，避開 Qwen 來源帶來的採購疑慮；客戶適用政策與授權要求仍需個別確認，不能說已取得案場合規認證。
3. **部署成本**：既有 44 題基準的 CPU 延遲中位數約 3 秒，可不配置專用推論 GPU；尚無採購費或耗電實測。關閉選配 OpenAI 後採本機推論，完整斷網驗收仍未實測。
4. **有備案**：客戶要求台灣自製時可換 Llama-Breeze2-3B，代價是注入題較弱、GGUF 非官方轉檔，切換前要重跑基準與資安測試。
5. **限制**：44 題是虛構題，只在一台電腦測一次；斷網執行還沒實測。
