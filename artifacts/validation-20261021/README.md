# 驗證證據索引（2026-10-21）

本目錄區分歷史模型實驗與本次程式／流程驗證。沒有執行模型訓練或重新量測 CPU/GPU 基準。

| 檔案 | 性質 |
|---|---|
| `source-manifest.json` | 原始實驗來源 commit、路徑與 SHA-256；副本逐位元核對 |
| `selection-independent-v5-comparison-20261020.json` | 訓練分支既有 100 題合成評估，原樣複製；`modelReady: false` |
| `qlora-coverage-train-20261020.json` | 訓練分支既有 504 步訓練紀錄，原樣複製；其中本機路徑為歷史記錄，並未移動 adapter |
| `knowledge-graph-evaluation.json` | 本輪重跑的固定快照 SQLite 評估，品質與權限門檻通過 |
| `tests.xml` | 本輪完整測試，161 passed，0 failures/errors/skipped |
| `verification-summary.json` | 測試指令與摘要、文件連結及來源雜湊核對、測試修正的驗證範圍 |
| `live-rehearsal-02.json` | 本輪成功的 localhost HTTP 演練，`passed: true`；無模型、無 GPU |
| `live-rehearsal.json` | 第一次演練的部分紀錄；驗證腳本把關係欄位誤寫為 `kind`，修正為既有 `relation` 後才有第二次成功結果，不當作全流程通過 |

CPU/GPU 的 44 題測試仍引用原位置的 [原始基準](../local-llm-benchmark.json)。PostgreSQL 與部署修正引用 [2026-10-20 稽核](../system-audit-20261020/README.md)，不當作今日重測。模型副本逐位元對照來源工作樹；Git blob 與工作樹的換行格式不同，manifest 同時保留兩者 SHA-256，並以解析後 JSON 確認來源 commit 內容一致。

新 100 題報告內有先前規劃階段遺留的「future evaluator」限制文字；其實已保存逐題評分與比較。此處保留原檔，不改寫歷史；解讀以已完成結果、`modelReady: false` 及 [README 的 Gemma QLoRA 兩輪結果](../../README.md#gemma-qlora-兩輪結果) 為準。
