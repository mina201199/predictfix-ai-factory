# Knowledge Graph Implementation Plan

> **For agentic workers:** Execute inline with executing-plans; existing isolated worktree is verified. Review using requesting-code-review after implementation.

**Goal:** 建立有來源、須主管核准的輕量維修圖譜與可重跑評估。

**Architecture:** 獨立模型、來源轉接、查詢及 API。所有查詢即時核對來源，不改原搜尋器。

**Tech Stack:** FastAPI / SQLAlchemy / SQLite / 原生 HTML、CSS、JS。

**Spec:** docs/superpowers/specs/2026-10-19-knowledge-graph-design.md

## Global Constraints

- 所有操作限本 worktree，無 GPU／LLM／新依賴；程式使用 2 空白。
- 新路由全部納入現有權限矩陣；主管寫入、工程師僅查核准有效路徑。
- 固定合成評估，保留逐題結果；PostgreSQL 未驗證。

### Task 1: 來源與圖譜核心

Files: backend/graph_models.py、backend/graph_sources.py、backend/knowledge_graph.py、tests/test_knowledge_graph.py。

- [x] 新測試以隔離 SQLite 驗證 `createCandidate(db, body, actor)`、`reviewRelation(db, id, body, actor)`、`queryGraph(db, body)`。先呼叫 `/api/graph/query` 斷言 200，確認現況 404。
- [x] 加來源快照／模型、逐字引文驗證、候選冪等、版本鎖、有界有向查詢，跑新測試。
- [x] 新測試覆蓋來源撤回／改版、案例草稿、錯機型、引用、持久化、重建。

### Task 2: API 與前端

Files: backend/app.py、graph.html、graph.js、graph.css、tests/access_matrix_scenario.py、docs/access-control.md。

- [x] `register(app)` 註冊 sources/candidates/rebuild/review/query/assist；app 只補 import、register 與 STATIC。
- [x] 新權限矩陣列以真實登入驗證每路由；執行 tests/test_access_matrix.py。
- [x] 操作頁使用 textContent、來源本地連結、外部腳本與樣式；執行 CSP 檢查。

### Task 3: 評估及交付

Files: evals/knowledge-graph/、scripts/evaluate_knowledge_graph.py、artifacts/knowledge-graph-evaluation.json、docs/knowledge-graph.md。

- [x] 固定資料包含多跳、錯機型、同碼異義、撤回、草稿、資料不足、越權及來源注入，對實際搜尋與圖譜保存逐題結果。
- [x] `python scripts/evaluate_knowledge_graph.py` 產出可重跑報告，誠實報告沒有改善的指標。
- [x] 全套 pytest、diff 檢查、獨立 review，修正後重驗證並只提交本分支。
