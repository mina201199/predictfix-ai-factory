# Ticket Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement task-by-task in this existing isolated worktree.

**Goal:** 交付可驗證的外部工單接收、待對應、CSV 與可靠狀態回寫。

**Architecture:** 新表繼承 store.Base，精確 HMAC middleware 接機器 API。主管路由沿用 session/CSRF，outbox 在 Ticket flush 交易內保存，由獨立 worker 傳送。

**Tech Stack:** 現有 FastAPI、Pydantic、SQLAlchemy、SQLite、httpx；不新增依賴。

**Spec:** docs/superpowers/specs/2026-10-19-ticket-integration-design.md

## Global Constraints

只改本組檔案；不 merge/push；不操作 GPU/LLM。新增程式使用 2 空白縮排、camelCase；金鑰只讀環境，fixture 明確標示假資料；不讀其他工作區憑證。SQLite 實跑，PostgreSQL 標示未驗。

### Task 1: 接收與資料一致性

Files: backend/integration_models.py、backend/integration_service.py、backend/integrations.py、backend/auth.py、backend/app.py、tests/integration_scenario.py、tests/test_integrations.py。

Interfaces: `verifyRequest(request)` 產生 service principal 與 raw body；`receiveEvent(db, source, rawBody)` 回傳固定接收結果，呼叫端控制交易；`resolveOrder(db, order)` 解析 mapping。

- [ ] 先寫接收、安全、版本、併發、pending 測試；執行並確認缺少端點而失敗。
- [ ] 實作嚴格 Pydantic body、HMAC、SQLAlchemy 表與交易。
- [ ] 加精確 middleware 銜接，驗證新增測試轉綠。

### Task 2: Outbox 與回寫 worker

Files: backend/integration_worker.py、backend/integration_service.py、tests/integration_scenario.py。

Interfaces: `runOnce(now=None, transport=None)` 以可注入時鐘與 transport claim、傳送、確認一件 outbox；`installOutboxHook()` 只監看有外部映射工單。

- [ ] 先加 rollback、worker lease/retry/dead/排序測試並確認失敗。
- [ ] 實作 flush hook 與 DB claim/lease，提交 claim 後發 HTTP，結果更新需 token 比對。
- [ ] 跑測試並確認復原不丟單且無重複業務事件。

### Task 3: CSV、管理 UI 與模擬器

Files: integrations.html/js/css、scripts/integration_simulator.py、backend/integrations.py、tests/integration_scenario.py。

Interfaces: CSV POST query `source`、`dryRun`；管理 GET records/mappings/outbox、PUT mapping、POST resolve/retry。

- [ ] 先加 CSV BOM/dry-run/逐列錯誤與管理權限測試並確認失敗。
- [ ] 共用 receiveEvent、savepoint 與整批 rollback；UI 使用 textContent 與 authReady，不載入秘密。
- [ ] 模擬器支援 send/receiver，使用環境金鑰與本機資料庫去重，隔離 transport 驗證暫時故障復原。

### Task 4: 矩陣、回歸與交付

Files: tests/access_matrix_scenario.py、docs/access-control.md、docs/ticket-integration.md、README.md。

- [ ] 追加各管理路由及未簽機器入口矩陣；保留路由覆蓋守門。
- [ ] 執行完整 SQLite 測試與語法檢查，修正新失敗；無 skip。
- [ ] 自行 review diff，記錄實際測試與限制，僅提交本組變更，回報 commit SHA。
