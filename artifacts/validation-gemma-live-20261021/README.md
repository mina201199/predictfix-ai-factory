# Gemma 現場 RAG 實跑結果

2026-10-21 在目前 Windows 電腦啟動 Gemma 4 E2B Q8_0，實際透過瀏覽器及應用程式 API 完成檢索、模型選段與原文引用。網站與模型於交付時保留執行；入口為 `http://127.0.0.1:18962/knowledge.html`。

## 啟動與環境

- 模型：`predictfix-ai-factory/.runtime/models/gemma-4-E2B-it-Q8_0.gguf`，4,967,497,152 bytes。
- SHA-256 實際核對：`996d08777aadc6bfd3c7375ef70ba25a0f55240075860754fdb18d6d860aa63a`，符合專案固定版本。
- llama.cpp：build 11491，commit `9b4ed0ca5`；CPU 12 執行緒、GPU layers 0、context 8192、單一 slot。
- 模型健康端點回報 `ok`；`/v1/models` 回報 `gemma-4-E2B-it-Q8_0` 與 Q8_0。
- 網站：`127.0.0.1:18962`；模型：`127.0.0.1:18964`；隔離資料庫沿用 `.runtime/interview-20261021/demo.db`。
- `OPENAI_ENABLED=0`，沒有呼叫雲端模型、重新下載權重或進行微調。產品程式未改動，只重新啟動本輪展示服務以使用 Gemma。

## 實際結果

瀏覽器先在維修工作台勾選 AI，畫面顯示「本機 AI 已執行」和 Gemma 模型名稱。接著在 AI 中心輸入：

> 特定刀位換刀卡住，應先核對哪些資料？

機型為 `PF-INTERVIEW-DEMO`，零件為「換刀」，勾選虛構資料與 AI 選段。畫面顯示「AI 原文整理」、三段帶引用編號的原文，以及「本機模型已執行 · gemma-4-E2B-it-Q8_0 · 10466.51 ms」。展開手冊引用後可看到 v1、適用機型及行 2–11 的原文。

另外透過 `/api/assist` 同題重跑兩次，兩次均有：

```json
{
  "llm_used": true,
  "model": "gemma-4-E2B-it-Q8_0",
  "provider": "llamacpp",
  "answer_method": "llm_selected_verified_excerpts",
  "citation_checks": {"accepted": 3, "rejected": 0},
  "selected_excerpt_ids": ["S1:P1", "S2:P1", "S3:P1"]
}
```

上方為摘錄摘要，`selected_excerpt_ids` 是由回應 `steps[].excerpt_id` 整理的欄位。完整回應與核對結果見 [live-rag.json](live-rag.json)。每段引用均逐字等於對應來源段落，來源機型也符合查詢；沒有只憑模型名稱或成功 HTTP 狀態認定完成。

本題候選包含兩個先前演練發布的相似案例，以及一份重複句較多的合成手冊；模型三段都選到。這證明模型確實執行、輸出能回查來源，不等於它能排除所有無關來源，也不是正式維修資料的正確率評估。原始合成資料未為了展示而改寫。

## 等待時間

| 請求 | 時間 | 量測口徑 |
|---|---:|---|
| 啟動後第一筆工作台查詢 | 12.16 秒 | llama.cpp 記錄的 prompt processing 加 generation，非完整瀏覽器延遲 |
| 第一次 AI 中心查詢 | 10.47 秒 | 畫面顯示的應用程式 `elapsed_ms`，不含人員操作及畫面繪製 |
| 相同題目 API 重跑 1 | 3.33 秒 | HTTP 客戶端完整往返；可能受模型提示快取影響 |
| 相同題目 API 重跑 2 | 3.50 秒 | HTTP 客戶端完整往返；可能受模型提示快取影響 |

不能把同題重跑速度當首次請求速度，也不能直接套用舊 44 題基準的三秒；本次輸入與 context 設定不同。

15 秒是展示時的切換門檻，不是效能保證或 API timeout。超過時可先切到工單、不重送，稍後返回查看；若顯示降級或失敗應如實標示。

## 證據與重現

- [模型名稱、耗時與引用畫面](rag-citations.png)
- [瀏覽器可見結果文字](rag-visible-state.txt)
- [API 原始回應及逐段核對](live-rag.json)
- [模型程序日誌快照](model-server.log)
- [測試報告](tests.xml)：模型請求、展示準備與維修流程共 4 項通過，零失敗／錯誤／跳過，終端機耗時 13.55 秒。
- [啟動與操作步驟](../../docs/gemma-live-validation.md)

本輪沒有測試多使用者並發、真實設備診斷、GPU 推論或新的 QLoRA 模型。來源引用驗證只證明原文及版本能對上，不能取代專業維修判斷。
