# 外部工單介接設計

本設計依第二波已核准方向實作；目前沒有真實企業工單系統。SQLite 是本波驗證平台，PostgreSQL 未驗證。

## 邊界與方案

採用獨立 integration 表、精確單一路徑 HMAC service principal、transactional outbox 與獨立 worker。相較於把外部呼叫塞進工單交易，outbox 可在接收端故障時保存待送資料；相較獨立訊息平台，此方案不增加部署依賴。主管設定仍走原本 session/CSRF，不把服務偽裝成主管。

## 契約

唯一機器入口 `POST /api/integrations/work-orders`。HMAC-SHA256 簽章輸入為 UTF-8 `v1\nPOST\n/api/integrations/work-orders\n{source}\n{keyId}\n{timestamp}\n{eventId}\n` 接原始 body bytes。Headers 為 `X-Integration-Source`、`X-Integration-Key`、`X-Integration-Timestamp`、`X-Integration-Event`、`X-Integration-Signature`（小寫 hex）。timestamp 為 Unix 秒，允許正負 300 秒。來源及 key ID 固定由環境設定允許，無預設金鑰；服務主體只能新增待指派工單及更新外部事件紀錄。

body 最多 16 KiB，欄位嚴格限制為 externalId/eventId/version/machineCode/alarm/symptoms/occurredAt。ID 使用安全 ASCII，version 從 1 逐次遞增；首件非 1、跳號、過期版本、同版本不同事件回 409，需來源依序重送。時間必須含時區，正規化 UTC；不使用時間判斷事件順序。拒絕 role/engineer/status/URL 等額外欄位。

## 儲存與流程

來源＋外部單號唯一對照；來源＋事件 ID 唯一收件紀錄，原始 body SHA256 用於相同事件重送，回傳原接收結果。同事件不同內容回 409。SQLite `BEGIN IMMEDIATE` 與 unique constraints 防止併發重單。主管 CSV 使用相同驗證及 ingest，來源由 query 指定，body hash 為固定 JSON 序列化，dry-run 整批交易 rollback，逐列使用 savepoint 回報錯誤。

未知機台或已停用映射保留 pending reason；主管先建 mapping，再 resolve 指定外部單。resolve 只用最新已接收版本，重複呼叫仍只產生一張工單。已建立的內部工單只保存後續來源快照，不讓外部更新覆寫人工作業、核准或結案。建單同既有報修路徑使用 active machine 檢查、待指派 Ticket 與 report_context，後續清單、派工、送審與驗收沿用原路由。

SQLAlchemy before_flush hook 僅監看有外部映射的 Ticket status/engineer，與變更交易一起新增 outbox。稽核與外部收件、人工對應同交易；回滾不留虛假事件。outbox 保存 payload/event ID、attempts、nextAttempt、lease token/deadline、lastError 與 dead 狀態。worker 一次 claim 一件、交易提交後才送 HTTP，成功後依 lease token 確認；crash 到期重送，至少一次傳遞，收件者必須 event ID 去重。每張工單依 outbox sequence 順序送，dead 會阻擋後續事件，主管可稽核重試。

## 網路與權限

來源金鑰及固定 outboundUrl 僅 `INTEGRATION_SOURCES` 環境設定，不給瀏覽器。URL 僅明確部署設定可指定；內網 HTTP 需 allowHttp=true，禁止 userinfo/fragment，HTTP client 禁止 redirects、環境 proxy，timeout 5 秒。管理 GET/PUT/POST 全部主管限定；CSV 與 retry/resolve 均驗 CSRF。管理回應不含金鑰、目的地 URL 或 HTTP 回應內容。

## 驗收

先跑 baseline，再測有效與錯誤簽章、body 改動、撤銷 key、時間窗、重送/併發、version 衝突、pending 解析、CSV BOM/重複/逐列錯誤/dry-run、主管與工程師權限、CSRF、outbox atomic rollback、lease/restart/backoff/dead-letter/retry。HTTP 使用隔離 transport，不碰外部企業、LLM 或 GPU。提供 CLI 來源模擬器及可暫時失敗的本機接收器。
