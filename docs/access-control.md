# 權限設計：主管與工程師怎麼劃分

**結論：系統只有「主管」與「工程師」兩個角色，用三層防線劃分權限，並由測試逐路由驗證。**

1. **RBAC 管「能做什麼」**：派工、人員負荷與出勤查詢、核准清單、審核結案、帳號、手冊與案例發布只限主管。
2. **資料歸屬管「能碰哪一筆」**：工程師只能操作指派給自己的工單，只看已發布案例與有效手冊；他人照片只看已提交的。
3. **職責分離管「執行者不能審核自己」**：工程師提交，主管審核。主管核准清單後，由負責工程師填寫結果；主管不能被指派，因此也不能自己執行再自己審核。
4. **AI 不能改權限、不能結案**：模型只負責選段落、給建議。身分一律由伺服器端 session 決定，任何 AI 回應都不會改變工單、帳號或案例狀態。

全部路由（方法＋路徑）都列在下方矩陣。[`tests/test_access_matrix.py`](../tests/test_access_matrix.py) 在正式與展示兩種模式下，分別以未登入、工程師、主管實際呼叫每個路由；需要資料歸屬的路由再加一位非指派工程師。新增圖譜後共 88 個路由、每種模式 298 次呼叫。如果新增 API 卻沒有寫進矩陣，CI 就會失敗。

## 三層設計

### 知識圖譜（獨立附加區塊）

| 方法 | 路徑 | 未登入 | 工程師 | 主管 | 資料範圍／備註 | 檢查位置 | 模式 |
|---|---|---|---|---|---|---|---|
| GET | `/api/graph/sources` | 401 | 403 | ✓ | 目前有效來源，含模板、備品、資格目錄；不含個人履歷 | `knowledge_graph.py:sources` | 兩者 |
| GET | `/api/graph/candidates` | 401 | 403 | ✓ | 最近 500 筆關係及來源是否仍有效 | `knowledge_graph.py:candidates` | 兩者 |
| POST | `/api/graph/candidates` | 401 | 403 | ✓ | 逐字來源／機型／型別驗證；只建立候選 | `knowledge_graph.py:candidate` | 兩者 |
| POST | `/api/graph/rebuild` | 401 | 403 | ✓ | 結構化來源規則轉換，不自動核准；可重跑 | `knowledge_graph.py:rebuild` | 兩者 |
| POST | `/api/graph/relations/{relationId}/review` | 401 | 403 | ✓ | 核准／撤回需 revision，操作者取 session | `knowledge_graph.py:review` | 兩者 |
| POST | `/api/graph/query` | 401 | ✓ | ✓ | 限核准、當下有效、明確機型、出向最多 3 hop；不公開孤立節點 | `knowledge_graph.py:queryGraph` | 兩者 |
| POST | `/api/graph/assist` | 401 | ✓ | ✓ | 純字詞或加圖譜，可追溯引用，不呼叫 LLM／不執行工單動作 | `knowledge_graph.py:assistGraph` | 兩者 |

`/graph.html`、`/graph.js`、`/graph.css` 屬現有 `/{filename}` 靜態白名單；頁面可載入，API 仍強制登入與角色檢查。草稿與失效來源只保留於主管的審查紀錄，工程師不能由圖鄰接取得。

| 層 | 回答的問題 | 做法 | 程式位置 |
|---|---|---|---|
| RBAC | 這個角色能不能呼叫這個功能？ | 主管限定的路由，函式第一行就呼叫 `auth.supervisor(request)`。角色來自資料庫 `users.role`，不讀 header 或 body。 | `backend/auth.py:37-38` |
| 資料歸屬 | 能不能碰「這一筆」資料？ | 工單操作呼叫 `auth.assigned(request, ticket)`，比對負責人；照片、案例、手冊依擁有者與發布狀態過濾。 | `backend/auth.py:39-40`、`evidence.py:80-92`、`maintenance_ai.py:106-116` |
| 職責分離 | 同一個人能不能自己做、自己審？ | 開始維修、填清單結果、提交完工只限負責工程師；核准清單與審核完工只限主管。派工對象必須是工程師帳號，主管不會成為負責人。 | `operations.py:105-121`、`repair_flow.py:316, 341`、`workforce.py:116`、`app.py:200, 237` |
| AI 邊界 | AI 能不能替人決定？ | 模型只能從後端列出的段落 ID 中選擇，多出的欄位整筆拒絕；案例建議逐字比對原文且不自動保存；對話查詢只使用唯讀 SQL 範本。 | `maintenance_ai.py:395-424, 552-564`、`chat.py:157-158` |

主管限定、但「負責工程師也不能做」的操作，正是職責分離的重點：例如負責這張工單的工程師呼叫 `POST /api/tickets/{tid}/review`，同樣回 403。

## 身分與連線機制

| 機制 | 防範的情況 | 程式位置 |
|---|---|---|
| Session cookie：`HttpOnly`、`SameSite=strict`，一般登入 8 小時、快速登入 1 小時；資料庫只存 token 的 SHA-256 | 前端腳本讀不到 token；資料庫外洩也拿不到可用的 session | `auth.py:84, 102-105` |
| CSRF token：非 GET 請求必須帶 `X-CSRF-Token`，與 session 綁定 | 跨站偽造請求 | `auth.py:56` |
| 跨站 Origin 檢查 | 從其他網域送出的寫入請求 | `auth.py:45-47` |
| 登入失敗限流：同一來源＋帳號，5 分鐘內失敗 5 次回 429 | 暴力猜密碼 | `auth.py:90-91, 96` |
| PBKDF2-SHA256 310,000 次＋隨機 salt；帳號不存在時也計算一次雜湊 | 密碼雜湊外洩後的破解；用回應時間猜帳號是否存在 | `auth.py:10-12, 93-94` |
| 停用帳號立即失效：每個請求都重新讀取 `users.active`，停用時同時撤銷 session | 離職或停權人員繼續使用舊 session | `auth.py:53`、`workforce.py:169` |
| 改密碼、重設密碼後撤銷該帳號所有 session | 密碼外洩後，舊 session 仍可使用 | `workforce.py:179, 189` |
| 至少保留一位主管、不能停用自己、停用前須交接未結案工單 | 系統被鎖死、工單無人負責 | `workforce.py:166-168` |
| 稽核紀錄：帳號、派工、審核、清單核准、案例、庫存異動都寫入 `audit`，並記錄操作者；只有主管能讀 | 事後追查是誰做的 | `app.py:96-101, 285-290`、`maintenance_ai.py:34-36`、`workforce.py:14-15` |
| 審核人姓名取自 session，不採用 body 的 `reviewer` 欄位 | 冒名審核 | `operations.py:119` |
| 展示模式隔離：`DEMO_ONLY_PATHS` 由最外層 middleware 回 404；正式模式設定 `DEMO_MODE=1` 會拒絕啟動；展示資料庫不能拿來當正式資料庫 | 展示用的快速登入、範例資料與 API 文件流入正式環境 | `app.py:42-44, 74-82`、`config.py:10-11`、`auth.py:71` |
| 驗證錯誤不回傳原始輸入；CSP 與安全標頭 | 錯誤訊息洩漏密碼；注入腳本 | `app.py:55-61, 84-87` |

## 權限矩陣

圖例：`✓` 允許（2xx）、`401` 需先登入、`403` 拒絕、`404` 不顯示。「負責人」指工單負責工程師，「非負責人」指其他工程師。程式位置都在 `backend/` 底下。標 ⚠ 的列是工程師可見範圍偏大、待決定的項目，見下一節。

展示限定的路由在正式模式一律回 404（未登入也一樣），因為最外層 middleware 會先擋下，不會進到登入檢查。

### 公開頁面、登入與系統

| 方法 | 路徑 | 未登入 | 工程師 | 主管 | 資料範圍／備註 | 檢查位置 | 模式 |
|---|---|---|---|---|---|---|---|
| GET | `/healthz` | ✓ | ✓ | ✓ | 只檢查資料庫連線 | `app.py:90`（非 `/api` 路徑） | 兩者 |
| GET | `/` | ✓ | ✓ | ✓ | 展示模式回 `index.html`，正式模式回 `console.html` | `app.py:313` | 兩者 |
| GET | `/{filename}` | ✓ | ✓ | ✓ | 只提供 `STATIC` 白名單檔案；`index.js` 等展示頁面在正式模式回 404 | `app.py:306-321, 74-76` | 兩者（部分檔案展示限定） |
| GET | `/openapi.json`、`/docs`、`/docs/oauth2-redirect`、`/redoc` | ✓ | ✓ | ✓ | FastAPI 內建文件；正式模式不讓未登入者看到完整 API 結構 | `app.py:72-76` | 展示限定 |
| GET | `/api/auth/config` | ✓ | ✓ | ✓ | 只回傳模式與是否開放快速登入 | `auth.py:48, 58` | 兩者 |
| POST | `/api/auth/login` | ✓ | ✓ | ✓ | 失敗限流 | `auth.py:48, 88-105` | 兩者 |
| POST | `/api/auth/demo` | ✓ | ✓ | ✓ | 快速登入；正式模式一律 403 | `auth.py:71` | 展示限定（正式 403） |
| GET | `/api/auth/me` | 401 | ✓ | ✓ | 只回傳自己 | `auth.py:53` | 兩者 |
| POST | `/api/auth/logout` | 401 | ✓ | ✓ | 只刪除自己的 session | `auth.py:108-113` | 兩者 |
| PUT | `/api/auth/password` | 401 | ✓ | ✓ | 只能改自己的密碼，需輸入目前密碼 | `workforce.py:187-189` | 兩者 |
| GET | `/api/health` | 401 | ✓ | ✓ | 含模型名稱與服務狀態 | `auth.py:53` | 兩者 |
| GET | `/api/openai/budget` | 401 | 403 | ✓ | | `app.py:132` | 兩者 |
| GET | `/api/audit` | 401 | 403 | ✓ | 最近 30 筆稽核紀錄 | `app.py:293` | 兩者 |
| GET | `/api/model/report` | 401 | ✓ | ✓ | 軸承分類實驗報告 | `app.py:74` | 展示限定 |
| GET | `/api/replay` | 401 | ✓ | ✓ | | `app.py:74` | 展示限定 |
| POST | `/api/predict` | 401 | ✓ | ✓ | | `app.py:74` | 展示限定 |
| POST | `/api/copilot` | 401 | ✓ | ✓ | AI；只回傳分析，不寫工單 | `app.py:74` | 展示限定 |
| POST | `/api/chat` | 401 | ✓ | ✓ | AI；唯讀 SQL 範本。⚠ 可查任何人員的未結案工單 | `app.py:74`、`chat.py:157-158` | 展示限定 |
| GET | `/api/documents` | 401 | ✓ | ✓ | 內建示範文件 | `app.py:74` | 展示限定 |

### 工單

| 方法 | 路徑 | 未登入 | 工程師 | 主管 | 資料範圍／備註 | 檢查位置 | 模式 |
|---|---|---|---|---|---|---|---|
| GET | `/api/tickets` | 401 | ✓ | ✓ | ⚠ 所有登入者都看得到全部工單與流程紀錄 | 無角色檢查（`app.py:188`） | 兩者 |
| POST | `/api/tickets` | 401 | ✓ | ✓ | 工程師只能建立「待指派」或指派給自己的工單；指派給他人回 403 | `app.py:198` | 兩者 |
| PATCH | `/api/tickets/{tid}/assign` | 401 | 403 | ✓ | 正式模式另檢查出勤、資格與剩餘工時 | `operations.py:86`、`workforce.py:113-121` | 兩者 |
| POST | `/api/tickets/{tid}/start` | 401 | 負責人 ✓／非負責人 403 | 403 | | `operations.py:105` | 兩者 |
| PUT | `/api/tickets/{tid}/report-context` | 401 | 負責人 ✓／非負責人 403 | ✓ | 補問資訊；不可更換設備 | `repair_flow.py:295-296` | 兩者 |
| PUT | `/api/tickets/{tid}/procedure` | 401 | 403 | ✓ | 主管核准排查／驗收清單，負責工程師也不能核准 | `repair_flow.py:316` | 兩者 |
| PUT | `/api/tickets/{tid}/procedure/results` | 401 | 負責人 ✓／非負責人 403 | 403 | 主管不能代填結果 | `repair_flow.py:341` | 兩者 |
| PUT | `/api/tickets/{tid}/estimate` | 401 | 403 | ✓ | | `workforce.py:246` | 兩者 |
| POST | `/api/tickets/{tid}/work-logs` | 401 | 負責人 ✓／非負責人 403 | 403 | | `workforce.py:265` | 兩者 |
| GET | `/api/tickets/{tid}/work-logs` | 401 | ✓（含非負責人） | ✓ | ⚠ 任何工程師都能讀任何工單的工時 | 無角色檢查（`workforce.py:271`） | 兩者 |
| POST | `/api/tickets/{ticket_id}/complete` | 401 | 負責人 ✓／非負責人 403 | 403 | 附上的照片必須是本人上傳、屬於這張工單 | `app.py:237`、`evidence.py:25` | 兩者 |
| POST | `/api/tickets/{tid}/review` | 401 | 403（負責人也一樣） | ✓ | 偽造 `X-Demo-Role` 標頭或 `reviewer` 欄位無效 | `operations.py:110, 119` | 兩者 |

### 照片與量測

| 方法 | 路徑 | 未登入 | 工程師 | 主管 | 資料範圍／備註 | 檢查位置 | 模式 |
|---|---|---|---|---|---|---|---|
| POST | `/api/tickets/{tid}/photos` | 401 | 負責人 ✓／非負責人 403 | 403 | | `evidence.py:34, 51` | 兩者 |
| POST | `/api/tickets/{tid}/measurements/import` | 401 | 負責人 ✓／非負責人 403 | 403 | | `evidence.py:61` | 兩者 |
| GET | `/api/tickets/{tid}/photos` | 401 | 負責人看全部；非負責人只看已提交的 | 全部 | | `evidence.py:80-83` | 兩者 |
| GET | `/api/evidence/{eid}` | 401 | 上傳者 ✓；其他人：已提交 ✓、未提交 403 | ✓ | | `evidence.py:90-92` | 兩者 |

### 設備與模板

| 方法 | 路徑 | 未登入 | 工程師 | 主管 | 資料範圍／備註 | 檢查位置 | 模式 |
|---|---|---|---|---|---|---|---|
| GET | `/api/machines` | 401 | ✓ | ✓ | 加上 `include_inactive=true` 也能看到停用設備 | `auth.py:53` | 兩者 |
| POST | `/api/machines` | 401 | 403 | ✓ | | `operations.py:150` | 兩者 |
| PATCH | `/api/machines/{mid}/asset` | 401 | 403 | ✓ | | `operations.py:124` | 兩者 |
| DELETE | `/api/machines/{mid}` | 401 | 403 | ✓ | 軟刪除；有未結案工單時拒絕 | `operations.py:160` | 兩者 |
| POST | `/api/machines/{mid}/restore` | 401 | 403 | ✓ | | `operations.py:169` | 兩者 |
| GET | `/api/equipment-templates` | 401 | ✓ | ✓ | | `auth.py:53` | 兩者 |
| POST | `/api/equipment-templates` | 401 | 403 | ✓ | | `equipment_templates.py:109` | 兩者 |
| PUT | `/api/equipment-templates/{tid}` | 401 | 403 | ✓ | | `equipment_templates.py:120` | 兩者 |

### 人員、出勤與派工

| 方法 | 路徑 | 未登入 | 工程師 | 主管 | 資料範圍／備註 | 檢查位置 | 模式 |
|---|---|---|---|---|---|---|---|
| GET | `/api/personnel` | 401 | 403 | ✓ | 全部工程師的未結案工單、出勤狀態與剩餘工時 | `operations.py:177` | 兩者 |
| GET | `/api/engineers` | 401 | 403 | ✓ | 內建展示人員採示例履歷；新建帳號依出勤、資格與容量推薦 | `app.py:257` | 兩者 |
| GET | `/api/dispatch` | 401 | 403 | ✓ | 全部工程師的出勤、資格、剩餘工時與可派工狀態 | `workforce.py:233` | 兩者 |
| GET | `/api/analytics` | 401 | ✓ | ✓ | ⚠ 全廠工單統計 | 無角色檢查（`operations.py:179`） | 兩者 |
| GET | `/api/duties` | 401 | 403 | ✓ | 全部人員的排班、請假與缺勤 | `workforce.py:195` | 兩者 |
| POST | `/api/duties` | 401 | 403 | ✓ | | `workforce.py:202` | 兩者 |
| PUT | `/api/duties/{did}/attendance` | 401 | 403 | ✓ | | `workforce.py:219` | 兩者 |

### 帳號管理

| 方法 | 路徑 | 未登入 | 工程師 | 主管 | 資料範圍／備註 | 檢查位置 | 模式 |
|---|---|---|---|---|---|---|---|
| GET | `/api/admin/users` | 401 | 403 | ✓ | 不回傳密碼雜湊 | `workforce.py:126` | 兩者 |
| POST | `/api/admin/users` | 401 | 403 | ✓ | 可建立主管或工程師帳號 | `workforce.py:132` | 兩者 |
| PUT | `/api/admin/users/{username}/profile` | 401 | 403 | ✓ | | `workforce.py:146` | 兩者 |
| PUT | `/api/admin/users/{username}/active` | 401 | 403 | ✓ | 不能停用自己、須保留一位主管、停用時撤銷 session | `workforce.py:158, 166-169` | 兩者 |
| PUT | `/api/admin/users/{username}/password` | 401 | 403 | ✓ | 重設後撤銷該帳號所有 session | `workforce.py:175, 179` | 兩者 |

### 知識庫與案例

| 方法 | 路徑 | 未登入 | 工程師 | 主管 | 資料範圍／備註 | 檢查位置 | 模式 |
|---|---|---|---|---|---|---|---|
| GET | `/api/knowledge/manuals` | 401 | 只看有效手冊 | 含已撤回 | | `maintenance_ai.py:434` | 兩者 |
| POST | `/api/knowledge/manuals` | 401 | 403 | ✓ | 正式模式不接受合成資料 | `maintenance_ai.py:438` | 兩者 |
| GET | `/api/knowledge/manuals/{mid}` | 401 | 有效 ✓；已撤回 404 | ✓ | | `maintenance_ai.py:462` | 兩者 |
| POST | `/api/knowledge/manuals/{mid}/withdraw` | 401 | 403 | ✓ | | `maintenance_ai.py:468` | 兩者 |
| GET | `/api/knowledge/search` | 401 | ✓ | ✓ | 檢索語料只包含有效手冊與已發布案例 | `maintenance_ai.py:96, 121` | 兩者 |
| POST | `/api/assist` | 401 | ✓ | ✓ | AI；只選段落，引用由後端對應原文 | `maintenance_ai.py:395-424` | 兩者 |
| GET | `/api/cases` | 401 | 只看已發布 | 全部 | | `maintenance_ai.py:480-481` | 兩者 |
| GET | `/api/cases/{cid}` | 401 | 已發布 ✓（不含原始快照與修改歷程）；草稿／撤回 404 | ✓ | | `maintenance_ai.py:106-116` | 兩者 |
| POST | `/api/tickets/{tid}/case-draft` | 401 | 403 | ✓ | 工單必須已完成 | `maintenance_ai.py:493` | 兩者 |
| PUT | `/api/cases/{cid}` | 401 | 403 | ✓ | | `maintenance_ai.py:523` | 兩者 |
| POST | `/api/cases/{cid}/ai-suggestion` | 401 | 403 | ✓ | AI；建議逐字比對原文，不自動保存 | `maintenance_ai.py:539` | 兩者 |
| POST | `/api/cases/{cid}/publish` | 401 | 403 | ✓ | | `maintenance_ai.py:568` | 兩者 |
| POST | `/api/cases/{cid}/withdraw` | 401 | 403 | ✓ | | `maintenance_ai.py:585` | 兩者 |

### 維修流程、保養與備品

| 方法 | 路徑 | 未登入 | 工程師 | 主管 | 資料範圍／備註 | 檢查位置 | 模式 |
|---|---|---|---|---|---|---|---|
| POST | `/api/repair-flow/analyze` | 401 | ✓ | ✓ | AI；只比較候選來源，不寫工單 | `auth.py:53` | 兩者 |
| POST | `/api/repair-flow/report` | 401 | ✓ | ✓ | 報修一律建立「待指派」工單 | `repair_flow.py:284` | 兩者 |
| GET | `/api/maintenance-plans` | 401 | ✓ | ✓ | | `auth.py:53` | 兩者 |
| POST | `/api/maintenance-plans` | 401 | 403 | ✓ | | `repair_flow.py:368` | 兩者 |
| PUT | `/api/maintenance-plans/{pid}/active` | 401 | 403 | ✓ | | `repair_flow.py:383` | 兩者 |
| POST | `/api/maintenance-plans/{pid}/generate` | 401 | 403 | ✓ | | `repair_flow.py:395` | 兩者 |
| GET | `/api/stock` | 401 | ✓ | ✓ | | `auth.py:53` | 兩者 |
| POST | `/api/stock` | 401 | 403 | ✓ | | `repair_flow.py:429` | 兩者 |
| GET | `/api/stock/movements` | 401 | ✓ | ✓ | ⚠ 全部庫存異動，含其他人的領料 | 無角色檢查（`repair_flow.py:437`） | 兩者 |
| POST | `/api/stock/{iid}/movements` | 401 | 入庫 403；領料／退料：負責人 ✓、非負責人 403 | ✓ | 領料、退料必須綁定工單 | `repair_flow.py:449-458` | 兩者 |

「檢查位置」寫 `auth.py:53` 的列，表示只需登入，由共用 middleware 檢查 session，函式內沒有角色檢查。

## 已決定的範圍與其餘共用資料

2026-10-19 經確認，`GET /api/personnel`、`GET /api/engineers`、`GET /api/dispatch`、`GET /api/duties` 改為主管限定；工程師直接呼叫回 403，未登入回 401。前端不再對工程師載入人員、出勤與推薦資料。工單看板維持同廠共用，角色仍只有主管與工程師。

展示模式新增工程師後，推薦改採既有出勤／容量規則，不再讀取不存在的展示案例成績；缺少出勤時標示不可派工。以下仍為共用資料，未變更：

| 路由 | 工程師目前看得到 | 可考慮的收斂方式 |
|---|---|---|
| `GET /api/tickets` | 全部工單，含他人的流程紀錄、提交內容與審核意見 | 已確認維持同廠共用看板 |
| `GET /api/analytics` | 全廠工單統計 | 改為主管限定 |
| `GET /api/tickets/{tid}/work-logs` | 任何工單的工時紀錄 | 限負責人與主管 |
| `GET /api/stock/movements` | 全部領料紀錄 | 工程師只看自己工單的異動 |
| `POST /api/chat`（展示限定） | 可查任何人員的未結案工單 | 展示模式可保留；若要上正式環境，套用與工單相同的範圍 |

修改任一項時，先把矩陣中對應列的預期結果改成新規則（例如 403 或過濾後的內容），確認測試失敗後再改程式。

## 已知限制

- **主管仍可能繞過職責分離**：主管能建立帳號、重設密碼，理論上可以登入成工程師，自己執行再自己審核。目前靠稽核紀錄追查（`user_created`、`password_reset` 都記錄操作者）。正式導入時，建議改接公司 SSO，或把帳號管理和工單審核交給不同人。
- **工單歸屬以顯示名稱比對**：`auth.assigned` 比對 `ticket.engineer` 與登入者姓名。姓名欄位在資料表中設有唯一限制，也沒有改名 API，所以目前不會撞名；若要長期維護，改用帳號 ID 比對會更穩。
- **登入限流存在單一程序的記憶體中**：服務重啟後歸零，多個 worker 之間也不共用。
- **只有兩個角色**：尚未提供報修人員（只能報修、看自己報的單）或稽核員（唯讀稽核紀錄）角色。目前報修由工程師帳號進行，稽核紀錄只開放給主管。

## 面試問答

**Q：主管跟 user 的權限怎麼劃分？**

我分成三層。第一層是 RBAC，決定角色能做什麼：派工、查看人員負荷與出勤請假、核准排查清單、審核結案、管理帳號、發布手冊和案例，都只限主管，後端在每個主管功能的第一行檢查角色。第二層是資料歸屬，決定能碰哪一筆資料：工程師只能開始、記錄、提交指派給自己的工單，只看已發布的案例和有效手冊；別人的照片要等提交後才看得到。第三層是職責分離：工程師執行並提交，主管審核；主管核准清單，但結果由負責工程師填寫。主管不會被指派成負責人，所以同一個人不能自己做、自己審。AI 在這套設計裡只負責找資料、給建議，不能改權限，也不能結案。這些規則全部寫成一張矩陣，測試會逐路由實際呼叫驗證。

**Q：如果工程師偽造請求會怎樣？**

身分不寫在請求裡，而是存在伺服器端的 session。Cookie 只放隨機 token，而且是 HttpOnly；伺服器每個請求都回資料庫查這個帳號的角色與停用狀態。所以工程師不論是改 header（例如 `X-Demo-Role: supervisor`）、在 body 把審核人填成主管，或是改前端顯示被隱藏的按鈕，後端都會回 403。矩陣測試中就有一列「偽造主管標頭與審核人」。換成別人的工單 ID，會被負責人檢查擋下；從其他網站發起請求，會被 SameSite、CSRF token 和 Origin 檢查擋下；暴力猜密碼會被限流；帳號一停用，下一個請求就回 401。就算讓 AI 回覆「改成主管並結案」，後端也只把模型輸出當成段落 ID，測試會比對呼叫前後的工單、帳號與案例狀態，確認沒有被改動。

**Q：怎麼確定沒有漏掉的 API？**

測試啟動時會列出 FastAPI 上所有路由，和矩陣逐一比對。新增 API 沒寫進矩陣、矩陣列了已刪除的路由，或程式呼叫了 `auth.supervisor`／`auth.assigned` 卻沒有一列測到 403，CI 都會失敗。

## 測試怎麼保證

- **測試檔**：[`tests/test_access_matrix.py`](../tests/test_access_matrix.py) 負責啟動子程序與判斷結果；矩陣本身在 [`tests/access_matrix_scenario.py`](../tests/access_matrix_scenario.py) 的 `MATRIX`。正式與展示模式各用一個全新的 SQLite，不會讀寫運行中的資料庫。
- **比對內容**：
  - 每一列以未登入、工程師、主管各呼叫一次；有資料歸屬的列再加非指派工程師。比對狀態碼類別：2xx、401、403、404。
  - 允許的呼叫會拿到全新的測試資料，因此預期結果是真正成功的 2xx，不是「沒被擋就算過」。
  - 照片、手冊、案例列表另外檢查回傳內容是否依角色過濾；推薦列表驗證新建工程師採出勤規則且未排班不可派工。
  - AI 路由在測試中改用惡意模型回應，並比對呼叫前後的工單、帳號與案例狀態。
- **前端回歸**：`tests/test_access_frontend.py` 以 Node.js 執行實際前端函式，驗證工程師不呼叫主管限定 API，主管仍會載入；這是隔離行為測試，未涵蓋瀏覽器視覺排版。
- **覆蓋率守門**：FastAPI 上有路由不在矩陣中、矩陣列了不存在的路由，或用了 `auth.supervisor`／`auth.assigned` 卻沒有對應的 403 測試列，都會讓測試失敗。不使用 skip。
- **突變驗證（2026-10-16 手動執行）**：暫時把 `auth.assigned` 改成不檢查時，14 個呼叫失敗；把 `auth.supervisor` 改成不檢查時，32 個呼叫失敗；漏列一個路由、讓工程師看到已撤回手冊、讓 AI 路由改掉工單狀態，也都會被抓到。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_access_matrix.py -q
```

新增 API 的流程：寫好路由後，在 `MATRIX` 加一列寫明各角色的預期結果，再更新本文件的對應表格。
