# 維修知識圖譜：來源、操作與評估

這版可把警報／零件連到排查步驟，再找到來源明示的備品與資格。每條關係須主管核對；工程師只能讀取當下仍有效的核准路徑。系統不判定診斷正確、不自動派工、結案或核准復機，人工核准也不等於原廠認證。

## 資料與 schema

沿用 SQLAlchemy `store.Base` 與既有資料庫，不新增依賴或 Neo4j。`app.py` 在 `store.init()` 前匯入圖譜模型，所以既有 SQLite 啟動時會新增獨立表，不修改原表。PostgreSQL **未實際驗證**，不能視為已通過部署驗收。

| 表 | 欄位／用途 |
|---|---|
| `graph_nodes` | 穩定 SHA256 ID、kind、label、machineModel。相同文字在不同機型是不同節點。 |
| `graph_relations` | 穩定 SHA256 ID、headId／tailId 外鍵、kind、machineModel、status、revision、createdAt、payload。 |
| relation payload | sourceChunkId、完整 sourceHash、citation（來源 ID／段落／版本／逐字引文／行號／本機連結／合成標記）、createdBy、approvedBy／approvedAt、reviewedBy／reviewedAt、reviewNote、完整審查 history。 |

節點型別：機型、零件、警報碼、症狀、故障、原因、排查步驟、驗收步驟、手冊段落、已發布案例、備品、資格。關係白名單：`has_part`、`references`、`possible_cause`、`inspect`、`verify`、`requires_spare`、`requires_qualification`；目標型別與機型→零件的方向有 schema 約束。

來源流程：有效來源 → 指定逐字引文／規則轉換 → `candidate` → 主管核對來源的語意與適用性 → `approved` → `withdrawn`。節點及關係採固定指紋去重；重建不會把撤回關係重新核准。審查先比對已讀 revision，再用資料庫 CAS 更新，避免並行操作覆蓋歷史；操作者一律取登入 session。

| 來源 | 如何建立候選 | 邊界 |
|---|---|---|
| 手冊段落 | 主管選來源，指定兩端原文、關係、逐字引文，再另行核對核准 | 系統只能驗證文字與機型，不能證明因果；不呼叫 LLM。 |
| 已發布案例 | 規則建立機型→案例→症狀／處置／驗收候選；也可人工指定逐字候選 | 不把假設／未知原因轉成確定根因。 |
| 自訂設備模板 | 規則建立模板機型範圍→零件／排查／驗收候選 | **適用範圍為模板 ID**，不能自稱適用某實際機型；模板內容不是原廠程序。內建通用模板不自動生成機型適用性。 |
| 備品／資格目錄 | 規則建立獨立節點；資格目錄不包含人員身分 | 不從庫存或人員履歷猜測機型相容／必要資格；只有來源明示且主管核准的關係才可連入路徑。 |

每次查詢重建目前可讀來源快照，不沿用原搜尋器的來源快取。撤回手冊、改版／改內容、案例變草稿或撤回，相關邊立刻失去查詢資格。案例同版號重新發布仍會因 publicationHash 改變而要求重新核對；舊紀錄保留給主管追溯。來源注入文字只當資料，前端用 `textContent` 呈現，不執行 HTML／命令。

## 查詢與權限

完整路由列於 [權限矩陣](access-control.md)。`GET /api/graph/sources`、`GET/POST /api/graph/candidates`、`POST /api/graph/rebuild`、`POST /api/graph/relations/{relationId}/review` 限主管。`POST /api/graph/query` 與 `POST /api/graph/assist` 可供登入者唯讀使用。所有 POST 沿用 CSRF 驗證。

查詢必須提供 `machineModel` 與原文字詞 `query`；警報碼必須完整命中，不能用 `E0` 猜 `E01`。只沿指定關係白名單的出邊，最多 3 hop、50 路徑、1000 次展開、5000 條有效邊、20000 筆關係掃描。失效邊不占有效邊配額；掃描／展開截斷回傳 `truncated: true`，不能將截斷後空結果視為沒有資料。禁止循環重訪節點。

`assist` 使用原 `maintenance_ai.search()` 的 TF-IDF／BM25 fusion，在**同一份即時有效來源**上維持純檢索 baseline；`useGraph` 決定是否另外返回圖譜路徑。圖譜起點採原文字詞命中，並非語意擴展模型。結果保留原檢索列表與每步路徑引用，不把圖譜鄰接寫成診斷答案；`automaticActions` 永遠為空、`llmUsed` 為 false。原 `/api/assist` 與原搜尋器未修改。

## 隔離展示與重跑

從本分支 worktree 根目錄執行。以下預設使用既有主 repo 的虛擬環境，不安裝或變更依賴：

```powershell
$graphPython = (Resolve-Path '../predictfix-ai-factory/.venv/Scripts/python.exe').Path
& $graphPython scripts/evaluate_knowledge_graph.py
```

預設每次新建隔離 SQLite，完成後關閉連線並清理；輸出 `artifacts/knowledge-graph-evaluation.json`。要保留一份可操作展示資料庫，指定**不存在**的路徑，工具拒絕覆寫既有資料庫：

```powershell
& $graphPython scripts/evaluate_knowledge_graph.py --demo-db .runtime/graph-demo.db
$env:APP_MODE = 'demo'
$env:DEMO_MODE = '1'
$env:DATABASE_URL = 'sqlite:///' + (Join-Path $PWD '.runtime/graph-demo.db').Replace('\', '/')
$env:BOOTSTRAP_PASSWORD = 'Isolated-KG-Synthetic-Fixture-123456'
$env:OPENAI_ENABLED = '0'
$env:LOCAL_LLM_MODEL = ''
$env:OLLAMA_MODEL = ''
& $graphPython -m uvicorn backend.app:app --host 127.0.0.1 --port 8894
```

此固定密碼只屬新建的合成隔離 fixture，不能放入正式帳號設定。沒有讀取或修改使用者 `.env`；現有 `.gitignore` 已排除 `.env`、`.runtime/` 與本機資料庫。

開啟 [圖譜展示頁](http://127.0.0.1:8894/graph.html)。建議 3 分鐘操作：

1. 用快速登入進主管，機型填 `KG-SYNTH-M1`，起點填 `DEMO-E17`。加圖譜模式應看到 4 條路徑，其中兩條為 3 hop，分別通往 `FILTER-A`、`LOTO`；展開引用可見 A→B→C／D 的不同來源。
2. 改純 TF-IDF／BM25，只有警報索引命中字詞；與圖譜跨來源擴展作對照。
3. 在主管候選紀錄找到 `壓差確認 → 需要備品 → FILTER-A`，填核對理由再撤回。等「審查已保存」後重新查詢，應剩 3 條、沒有備品路徑；可再填理由核准以恢復。
4. 選「合成測試 警報索引」來源，起點類型警報碼／原文 `DEMO-E17`，目標類型零件／原文 `濾芯`，關係來源記載關聯，建立候選。相同來源指紋會去重；新增內容須另行核准。一般手冊流程就是先核對原文再建立。
5. 機型改 `KG-SYNTH-M2`、同警報應只指向刀庫；查 `DEMO-E99`、`DEMO-DRAFT` 不會得到撤回／草稿路徑；反查 `FILTER-A` 不會倒推警報。
6. 登出再以工程師登入，只保留查詢區，不能看到候選／來源管理。後端直接呼叫主管 API 也會 403；未登入則 401。

備品連結開啟目前目錄，資格連結開啟既有流程頁；來源只宣告需求，沒有自動驗證庫存料號相容或指派人員資格。UI 使用原生 HTML/CSS/JS，無 inline script/style、外部 CDN 或額外圖資料庫。

## 評估結果與解讀

固定來源為 `evals/knowledge-graph/snapshot.json`，金標為 `questions.json`，報告保存兩者 SHA256 與逐題檢索／路徑。共有 10 題檢索情境及 2 題實際權限情境；含 2–3 hop、同碼異義、錯機型、撤回、草稿、資料不足、反向關係反例、來源注入與越權。

| 指標 | 純字詞 TF-IDF／BM25 | 字詞＋圖譜 |
|---|---:|---:|
| Macro retrieval precision | 100% | 100% |
| Macro recall（6 題有相關來源） | 79.17% | 100% |
| 可答題取得完整 required 來源（5 題） | 60% | 100% |
| 可答性判定正確（10 題） | 80% | 100% |
| 逐題全部回傳來源均相關 | 100% | 100% |

指標是**文件 ID 集合覆蓋**：兩組共用 top-5 baseline；圖譜組額外加入有界路徑來源，不是相同 k 的排名比較，不是 nDCG／MRR。空結果 precision 定為 1；沒有 relevant 來源的題目不計 recall。可答性只是 required 金標來源是否齊全，不能代表模型作答品質、診斷正確性、維修成功率或工廠停機時間改善。圖譜來源與金標為原創合成、人工設計關係，**沒有獨立領域專家驗收，也沒有真實現場成效證據**。precision 沒有提升。

報告另檢查來源當下有效／機型／版本與 hash、目標路徑／方向、自動操作為空、無 LLM、越權狀態，以及圖譜指標不低於 baseline。任何品質門檻失敗會保留報告並以非零狀態退出；不使用 skip。

## 測試與交付邊界

```powershell
New-Item -ItemType Directory -Force .runtime | Out-Null
& $graphPython -m pytest --confcutdir=. --rootdir=. tests -q -p no:cacheprovider --basetemp=.runtime/graph-verification
node --check graph.js
git diff --check
```

圖譜情境使用真實 SQLite／TestClient，涵蓋持久化、去重、主管審查、CAS 與雙 Session 競態、方向／循環／hop／結果／展開與掃描上限、改版／撤回／草稿／同版重發布、特殊字元模板、備品與資格目錄不亂推適用性、引用追溯、工程師／未登入權限。全路由矩陣仍在正式與展示模式逐列執行，沒有關閉守門。瀏覽器實測主管撤回後路徑由 4 減為 3，重新核准恢復；工程師沒有管理區。axe 基本檢查在修正身分文字對比後無違規。

本分支基準為 68 項 pytest 通過；最後全套為 **70 passed，0 failure／error／skip**，140.07 秒；另有既有 Starlette 套件 deprecation warning 一則。圖譜單一情境包含 52 次檢查，不能將其和 pytest 項數相加。見 [驗證紀錄](../artifacts/knowledge-graph-verification.json)、[JUnit](../artifacts/knowledge-graph-tests.xml) 與 [合成畫面](../artifacts/knowledge-graph-engineer.png)。

獨立審查已修正：失效邊占配額、模板 JSON 跳脫、預送未讀 revision 的競態、評估成功退出未代表品質門檻。仍需真實來源與領域人員核對；大規模資料的索引／批次有效性維護、PostgreSQL、語意抽取模型及正式現場維修效益尚未驗證。

面試可這樣說：「我把搜尋不到的跨段準備資訊變成可追溯的有向路徑，但不把路徑當診斷。每條邊都有來源版本、引文及核准者；撤回或改版會立即失效。合成評估看的是來源覆蓋，真實維修成效仍需要領域標註與現場驗收。」
