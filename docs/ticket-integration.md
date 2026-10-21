# 外部工單介接

這是外部 API、CSV 與狀態回寫的可操作子系統，目前對接的是本機模擬器，尚未串接真實企業工單系統。SQLite 有實際測試；2026-10-20 已補 PostgreSQL 介接測試與事件／CSV 鎖定修正，見 [稽核證據](../artifacts/system-audit-20261020/README.md)。主線的 `compose.production.yaml` 已包含 `INTEGRATION_SOURCES` 與背景 worker；設定存在不等於企業部署驗收。服務不呼叫 LLM，不使用 GPU。

2026-10-21 面試展示使用 [共同隔離展示步驟](interview-demo.md)，不覆寫專案根目錄既有 `.env` 或正式資料庫。下方歷史驗收的 SQLite 範圍仍按原日期解讀。

## 設定與啟動

金鑰及固定回寫目的地只放 `.env`，已由 `.gitignore` 排除；不放在前端、CSV 或資料表。`INTEGRATION_SOURCES` 是單行 JSON，例如下列結構（占位字串不是有效金鑰）：

```dotenv
INTEGRATION_SOURCES={"mes-demo":{"keys":{"v1":"REPLACE_WITH_GENERATED_SECRET"},"outboundKeyId":"v1","outboundUrl":"http://127.0.0.1:8097/events","allowHttp":true}}
```

每個來源只接受其 `keys` 列出的 key ID，secret 至少 32 字元。新增 key 後讓來源切換，再移除舊 key 即完成撤銷；驗證每次讀取環境設定，已執行的服務需重新載入部署環境才能套用檔案修改。若環境變數已設定，launcher 保留環境值。`.env` loader 只接受明確的 KEY=VALUE，可使用單／雙引號包住整個值，不做 shell 展開或執行，不支援多行及行尾註解。

以下指令在本專案根目錄執行。worktree 沒有 `.venv` 時，可把 `$python` 換成既有主 repo 的 Python 絕對路徑。先用獨立展示資料庫，避免將展示資料寫入正式資料庫：

```powershell
$python = '.\.venv\Scripts\python.exe'
New-Item -ItemType Directory -Force .runtime | Out-Null
# 以 exclusive create 建立；若已存在 .env，會停止，避免覆寫既有設定。
@'
import json,secrets
from pathlib import Path
config={'mes-demo':{'keys':{'v1':secrets.token_urlsafe(48)},'outboundKeyId':'v1','outboundUrl':'http://127.0.0.1:8097/events','allowHttp':True}}
with Path('.env').open('x',encoding='utf-8') as f:
  f.write('APP_MODE=production\nDEMO_MODE=0\nDATABASE_URL=sqlite:///'+str(Path('.runtime/integration-demo.db').resolve()).replace('\\','/')+'\n')
  f.write('BOOTSTRAP_PASSWORD='+secrets.token_urlsafe(32)+'\nINTEGRATION_SOURCES='+json.dumps(config)+'\n')
'@ | & $python -
& $python scripts/integration_run.py --env-file .env serve --port 8096
```

這個 launcher 只啟動 FastAPI，不啟動／重啟模型服務。開啟 `http://127.0.0.1:8096/console.html`，用 `supervisor` 與 `.env` 中的 BOOTSTRAP_PASSWORD 登入，先建檔真實／隔離測試設備。再開 `/integrations.html`，填來源 `mes-demo`、外部機台 `SIM-CNC-01` 與該內部設備，保存映射。工程師只會看到需要主管權限的訊息，不載入管理資料。

另開終端機啟動接收器與 worker（須使用相同 `.env`／DATABASE_URL）：

```powershell
& $python scripts/integration_run.py --env-file .env simulator receiver --source mes-demo --port 8097 --db .runtime/receiver-demo.db --fail-first 1
& $python scripts/integration_run.py --env-file .env worker
# 單次取件，便於重啟／展示：
& $python scripts/integration_run.py --env-file .env worker --once
```

`--fail-first 1` 讓每個尚未接收的 event 首次回 503；attempt 與成功收件均存 SQLite，停止後用同一 db 重新啟動會保留紀錄。worker 失敗後等退避時間再處理，UI 可查看最後錯誤。不要同時啟動兩個 receiver 佔同一 port；worker 可多程序 claim，但本波只實跑 SQLite 的併發測試。

## Inbound API 契約

`POST /api/integrations/work-orders`、JSON raw body 最多 **16 KiB**。只有精確這支 POST 使用 HMAC；主管管理端點一律 session＋CSRF。登入 Cookie 不能代替簽章，簽章不能代替主管身分。

| 欄位 | 限制與用途 |
| --- | --- |
| externalId | 來源內工單 ID，1–60 ASCII 字元 |
| eventId | 來源內事件 ID，1–60 ASCII 字元，須與 header 一致 |
| version | JSON integer，1–2147483647；不可用字串或 boolean |
| machineCode | 外部機台代號，1–60 ASCII 字元，交由映射對應 |
| alarm | 警報原文，最多 200 字元，可省略／空字串 |
| symptoms | 去除頭尾空白後 3–160 字元 |
| occurredAt | ISO 8601 含時區、最多 40 字元；保存成 UTC |

三種 ID 均須符合 `[A-Za-z0-9][A-Za-z0-9_.:-]{0,59}`。拒絕其他欄位，例如 role、engineer、status、callbackUrl；不接受外部指定核准、結案或復機。事件順序只依 version，不依 occurredAt 猜測。

Headers：`X-Integration-Source`、`X-Integration-Key`、`X-Integration-Timestamp`（Unix 秒）、`X-Integration-Event`、`X-Integration-Signature`（小寫 hex）。來源、key ID 與 event ID 同上 ID 格式，timestamp 正負 300 秒內。簽章是以下 prefix 的 UTF-8 bytes 接上 **原始 body bytes**，以 secret 計算 HMAC-SHA256：

```text
v1\nPOST\n/api/integrations/work-orders\n{source}\n{keyId}\n{timestamp}\n{eventId}\n
```

`\n` 表示單一 LF。raw body 包含所有空白與換行，重新序列化後必須重新簽章。使用 constant-time digest 比對。錯誤只回固定訊息，不回傳秘密／完整輸入。正常機器呼叫不帶瀏覽器 Origin；現有跨站 Origin 防線仍有效。

回應為 `orderId/source/externalId/version/ticketId/state/reason`。state 是 linked 或 pending；reason 是 unknown_machine_code 或 mapped_machine_inactive。相同來源＋eventId＋完全相同 body 重送，回傳原結果；同 ID 不同 body 回 409。若原結果是 pending，主管後來解析後，重送仍回原 pending 接收結果，最新關聯請由管理 records 查詢。

來源＋externalId 唯一；新單 version 必須為 1，後續必須等於上一版＋1。過期、跳號、同版本換 event ID 一律 409，不寫入成功事件。來源先重送缺少版本，再送下一版。外部工單不可改 machineCode；後續事件保存最新外部快照，不覆寫內部工單描述、人員或狀態。映射修改只影響尚未關聯的單，已建立工單不搬機台。

| HTTP | 意義／來源應對 |
| --- | --- |
| 200 | 已接收或同事件重送；pending 也代表資料已保存 |
| 401 | 來源／key／簽章／時間窗失效；先修正設定，不盲目重試 |
| 403 | 管理端權限、CSRF 或跨站 Origin 不符 |
| 404 | 主管指定的 order/outbox 不存在 |
| 409 | 版本、事件內容或競爭衝突；同事件競爭可重送，其餘先修正順序 |
| 413 | body 過大 |
| 422 | 欄位、時間格式、CSV 格式或映射設備不符 |

## 待對應、CSV 與管理 API

未知／停用機台會保留 ExternalOrder 的最新事件、原因與接收紀錄，不會自動建立真機或猜機型。主管建立有效 mapping 後呼叫 resolve，只產生一張待指派工單，重複及併發解析均不重單。工單含 report_context 與 integration 來源關聯，接著使用原本的清單、估時、派工、維修、送審與驗收 API；未完成核准清單時，原送審規則仍會拒絕。

| API | 功能 |
| --- | --- |
| GET /api/integrations/mappings | 查看映射，不包含來源設定或秘密 |
| PUT /api/integrations/mappings | body：source、machineCode、machineId；驗證有效內部設備 |
| GET /api/integrations/records | orders 最新快照／原因與 events 原始結果／SHA256 |
| POST /api/integrations/orders/{orderId}/resolve | 使用目前有效映射解析一次 |
| GET /api/integrations/outbox | 狀態、payload、嘗試、下次時間、最後錯誤；無 lease token |
| POST /api/integrations/outbox/{outboxId}/retry | 僅 dead-letter；保留原 eventId，次數歸零並記稽核 |
| POST /api/integrations/csv?source=mes-demo&dryRun=true | CSV 原始 body；預設 dry-run |

各 GET 接受 `limit=1..1000`（預設 200）及 offset；UI 每區 100 筆並提供翻頁。全部管理 API 主管限定，寫入須 `X-CSRF-Token`。

CSV 須 UTF-8／UTF-8 BOM、最多 256 KiB、1–200 列，七欄必須完整且不得重複；版本由 CSV 字串轉成 integer 後沿用相同正規化與 receiveEvent。逐列 savepoint：格式／版本衝突列失敗，其他成功列保留。dry-run 在整批結束 rollback，不建立工單、稽核或 outbox，預覽 ID 不保證與正式匯入相同。CSV 使用排序、無多餘空白的 JSON 產生 hash；要與 API 共用 event ID，API 也須送相同 canonical JSON bytes。沒有 CSV API key 欄。

產生含兩筆重複事件的範本，再由 UI 預覽及匯入：

```powershell
& $python scripts/integration_simulator.py csv > .runtime/orders.csv
```

預覽應兩列成功但沒有建單；實際匯入後只有一張單。錯誤列包含 row（CSV 實體資料列編號，自 2 起）、status、error；成功列包含 result。

## Outbound 與資料表

四張新表宣告於 `backend/integration_models.py`，未改 store.py：

| 表 | 唯一性與內容 |
| --- | --- |
| integration_machine_mappings | source＋machineCode 唯一，對應內部 machineId |
| integration_orders | source＋externalId 唯一、ticketId 唯一；最新 version／payload／pending reason |
| integration_inbound_events | source＋eventId 唯一；raw SHA256、固定接收結果、接收時間 |
| integration_outbox | 自增順序 ID、eventId 唯一；payload、state、attempts、nextAttempt、lease token／截止、lastError |

現有 ORM 路徑的指派、開始、送審、退回與完成會由受限 `before_flush` hook 在**同一筆交易**新增 outbox；只監看已有外部對照的 Ticket status／engineer。初次介接建單也在同一筆交易新增事件。其他內部工單不產生外部回寫。直接 SQL／bulk update 不經此 hook；未來新增這類工單變更路徑時必須補交易內 hook。

payload：eventId、source、externalId、ticketId、externalVersion、status、engineer。回寫沿用相同 HMAC headers 與 prefix，但 path 換成預設目的地的 path（模擬器為 `/events`）。只有 HTTP 2xx 算成功；收件者須依 source＋eventId 去重且同 ID 不同內容拒絕。這是**至少一次傳遞**，不是 exactly-once。應用程式可能在收件成功但本地確認前中斷，租約過期後會再送同一事件。

worker claim 的交易先提交，再發 HTTP；租約 60 秒、timeout 5 秒、最多 5 次嘗試，失敗等待 10／20／40／80 秒；達上限進 dead。第 5 次 claim 後程序中斷，租約過期也會進 dead，等待主管判斷重試。每張單按 outbox ID 依序傳送；前一件 pending/sending/dead 會擋住後件，其餘工單仍可送。只有 lease token 仍相同的 worker 能確認結果，避免舊 worker 蓋過新租約。HTTP response body 與 exception 內容不存入日誌或管理回應，僅保存固定錯誤代號。

目的地只能由部署設定的 outboundUrl 指定；inbound body 不接受 URL。HTTPS 預設可用，明確 `allowHttp:true` 才允許工廠內網 HTTP。禁止 userinfo、query、fragment；不跟隨 redirect、不讀環境 proxy，內網位址允許但部署人員必須確實掌握固定目的地。來源／目的地設定有管理主機權限的人才能變更，尚無前端編輯服務秘密功能。

稽核種類：integration_received、integration_linked、integration_mapping、integration_resolved、integration_status、integration_csv、integration_delivery、integration_retry。使用現有 Audit 表，保存 actor／source／event／內外 ID、摘要及結果，不含金鑰。成功接收／工單狀態稽核與原交易一起提交；被拒絕的驗簽／欄位請求不寫成功接收紀錄。資料保留與外部不可竄改稽核尚未接入，需正式部署另訂政策。

## 可重現情境與驗證

所有 simulator send 指令只接受明確 localhost HTTP origin，避免誤送企業 URL。每次執行會產生 occurredAt，重送情境應使用 `--scenario replay` 在同次執行重送完全相同 bytes；若跨指令重用 event ID 又改變時間，應預期 409。

```powershell
& $python scripts/integration_run.py --env-file .env simulator send --target http://127.0.0.1:8096 --source mes-demo --scenario replay --external-id SIM-REPLAY --event-id EVT-REPLAY
& $python scripts/integration_run.py --env-file .env simulator send --target http://127.0.0.1:8096 --source mes-demo --scenario update --external-id SIM-UPDATE --event-id EVT-UPDATE
& $python scripts/integration_run.py --env-file .env simulator send --target http://127.0.0.1:8096 --source mes-demo --scenario out-of-order --external-id SIM-ORDER --event-id EVT-ORDER
```

其他 scenario：normal、missing、bad-signature、expired、unknown。每次選新 external-id/event-id，避免前次資料影響；預期 missing 422、bad-signature／expired 401、out-of-order 409、unknown 200 pending。unknown 依 external-id 產生 `UNKNOWN-` 加摘要的機台代號，避免先前通用代號已完成映射而影響展示；主管 mapping＋resolve 後才建工單。worker 重啟使用同一 `.env` 與 DB，receiver 重啟使用同一 `--db`。

自動測試（不使用 GPU／真實外部網路）：

```powershell
& $python -m pytest --confcutdir=. --rootdir=. tests -q -p no:cacheprovider --basetemp=.runtime/integration-verification
```

詳細實際結果與限制見 [驗收報告](ticket-integration-validation.md)。設計與計畫位於 `docs/superpowers/specs/2026-10-19-ticket-integration-design.md` 與 `docs/superpowers/plans/2026-10-19-ticket-integration.md`。
