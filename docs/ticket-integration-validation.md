# 外部工單介接驗收報告

驗證日期：2026-10-19（Asia/Taipei）。分支 `codex/wave2-ticket-integration`，基底 `ad3fc63`。這份報告記錄本機模擬與隔離 SQLite 的實際結果，未對接企業系統，也未執行 PostgreSQL／GPU／LLM 測試。

後續狀態：2026-10-20 已另有 [PostgreSQL 介接與部署設定稽核](../artifacts/system-audit-20261020/README.md)，2026-10-21 面試演練見 [本輪證據](../artifacts/interview-20261021/README.md)。下方數字與「未驗證／未合併」均描述 2026-10-19 當時狀態，原始結果不改寫。

## 測試結果

| 階段 | 實際結果 |
| --- | --- |
| 修改前完整 baseline | 68 passed、0 skipped，132.87 秒 |
| 最終完整 regression | 70 passed、0 failed、0 skipped，142.31 秒 |
| 正式模式介接子程序 | 53 passed、0 skipped |
| 展示模式介接子程序 | 53 passed、0 skipped |
| 相關介接／矩陣／CSP 回歸（日期修正後） | 9 passed，60.27 秒 |
| JavaScript 語法 | `node --check integrations.js`，exit 0 |
| Python 語法 | 新增六個 Python 模組 compileall，exit 0 |
| diff 檢查與秘密排除 | `git diff --check` 通過；`.env`、隔離環境檔與 proof 圖片均由 gitignore 排除 |

完整測試的 70 項包含既有 68 項與兩個介接包裝測試；包裝測試再各以新 SQLite 執行 53 個情境，不把它們混成同一層計數。包裝測試會讀 child JUnit 並拒絕 skipped，沒有使用 skip 掩蓋缺測。一項原有 `StarletteDeprecationWarning`（httpx／httpx2）仍存在；本波未改共用依賴。秒數是本次測試執行時間，不是受控效能比較。

執行指令（worktree 使用既有主 repo 的 Python，未修改其依賴）：

```powershell
python -m pytest --confcutdir=. --rootdir=. tests -q -p no:cacheprovider --basetemp=.runtime/integration-release-check --junitxml=.runtime/integration-release-check.xml
```

結構化結果：[artifacts/ticket-integration-validation.json](../artifacts/ticket-integration-validation.json)。該檔案包含兩種模式的實際案例名稱、CLI 回應與重啟結果，不含秘密。JUnit 原始檔保存在忽略的 `.runtime/integration-release-check.xml` 與各子目錄 `child-report.xml`。

## 自動情境實際結果

| 情境 | 觀察結果 |
| --- | --- |
| 未登入但有效 HMAC | 200，服務來源接收成功，未建立主管身分 |
| body 改動、錯 secret、未知 source、撤銷 key、event header 改動 | 401，未寫入成功收件，回應無秘密 |
| 過期／未來 timestamp | 假時鐘下超過 300 秒均 401，無依賴長 sleep |
| role／engineer／status／URL 額外欄位 | 422，不能設定權限或內部狀態 |
| 缺欄位、錯時區、空症狀、過長警報／body、字串或 boolean version | 422／413，沒有成功收件 |
| 相同事件完全重送 | 回原結果，只一張工單、一筆接收事件 |
| 相同 event ID 改內容 | 409，既有結果不變 |
| 六個併發相同事件 | 全部 200，ticketId 相同，只建立一張工單 |
| 首版非 1、過期／跳號版、同版換事件 | 409；v1→v2 成功且保留同張內部單 |
| 未知機台與停用映射 | 200 pending，保留原因，不建未知真機 |
| pending 最新版＋主管解析 | 使用最新症狀建一張待指派單；重複與四個併發 resolve 均同 ticketId |
| 工程師／未登入呼叫管理 API | 403／401；有效 HMAC 也不能取代主管 session |
| 主管管理寫入缺 CSRF | 403 |
| CSV BOM、重複列、錯誤列 | 逐列成功／失敗，重複只建一張；dry-run 無事件、工單或 outbox |
| CSV 大小／列數／編碼／表頭 | 413／422；多欄、超長版本回逐列錯誤 |
| 極端 UTC 轉換溢位 | inbound 422；CSV 該列 422，前面的有效列仍保存 |
| 接收交易 rollback | ExternalOrder／InboundEvent／Ticket／Outbox 全部未留下 |
| 工單狀態 flush 後 rollback | outbox 與狀態一起回滾 |
| 原 API 的完整人工作業 | 指派→開始→送審→退回→再送審→主管完成，outbox 狀態依序一致；清單未填不能送審 |
| worker 503／backoff／dead／主管 retry | 五次後 dead；主管 retry 保留 eventId；恢復後 sent |
| lease／程序中斷／舊 worker 回覆 | 未過期不取件；過期可重送；舊 token 不能覆寫新 lease |
| 第五次 claim 後程序中斷 | 租約過期後 dead，事件保留，未做第六次傳送 |
| 每單順序與 redirect | 前件退避阻擋後件；302 不跟隨外部 URL |
| 缺目的地／傳送期間資料庫寫入 | 事件留 pending；網路回呼期間其他 DB 交易可成功 |
| 模擬器接收端重啟 | 同 SQLite 保留嘗試與去重；相同事件 200，不同內容 409 |

## 本機 HTTP 與瀏覽器展示

測試服務為獨立 `127.0.0.1:8096`／receiver `127.0.0.1:8097`，使用 `.runtime` 下的隔離資料庫與假憑證，沒有讀寫主 repo 的運行資料或啟停使用者 LLM。

實際 CLI 回應：normal 200 linked；replay 兩次 200 且同 ticketId；update v1／v2 兩次 200 且同 ticketId；out-of-order 409；missing 422；bad-signature 401；expired 401。unknown 首次 UI 展示為 200 pending，主管保存 mapping 並 resolve 後才建立待指派單。

後續 CLI unknown 曾因通用 `SIM-UNKNOWN` 已被上述操作映射而回 linked，並非接收端遺失驗證。已將模擬器改成依單號摘要產生獨立代號，重新實跑 `CLI-unknown-specific`，結果 **200 pending、ticketId=null、unknown_machine_code**；原觀察與修正後結果均保留在 JSON 報告。

回寫端第一次刻意回 **503**，worker 佇列顯示 pending、attempts=1、http_status_503。稍後以新 worker 程序執行 `--once`，回寫成功為 **sent、attempts=2**。接收器程序停止後以相同 SQLite 重新啟動，手動重送同一 outbox raw payload，回 **200**，成功收件數維持 **1**。

瀏覽器實際登入主管、保存映射、解析 pending，畫面可見內部單與 sent 事件；登入工程師後只顯示需要主管權限，不顯示映射／紀錄。使用 in-app browser 驗證；agent-browser 因本機 headless CDP 啟動失敗，未把該工具失敗當作產品測試結果。

本機截圖（忽略檔，不納入 Git）：`artifacts/integration-ui-proof.png`、`artifacts/integration-engineer-proof.png`。截圖只有合成設備／工單資料，無秘密。

## 審查與限制

獨立 read-only code review 找到一項 P2：日期轉 UTC 可能 OverflowError，造成 CSV 有效列也 rollback。已先加入上下界重現測試，再轉成 Pydantic 驗證錯誤；審查者複查確認該項關閉。自測另修正 CSV 多欄／超長版本的逐列錯誤，以及未知機台模擬重現性。

- 真實企業 API／欄位契約、網路環境、TLS 與 PostgreSQL 未驗證；不宣稱企業介接完成。
- Outbox 為至少一次傳遞，收件端必須持久化 event ID 去重；dead 需要主管判斷並重試。
- 既有 ORM 工單路徑有交易內 outbox；直接 SQL／bulk 工單更新不在 hook 支援範圍。
- 最新外部快照不會自動覆寫內部工單，外部改機台需另開單或由人工處理。
- 稽核與接收／outbox 的保留政策、外部不可竄改稽核、企業網路層防護由正式部署另行設定。
- 瀏覽器驗證為桌面主管／工程師操作；未做完整手機與無障礙稽核。

整合時由協調者依序處理 app.py 註冊／STATIC 與權限矩陣附加區塊；本分支沒有 merge 主 repo、push 或建立 PR。
