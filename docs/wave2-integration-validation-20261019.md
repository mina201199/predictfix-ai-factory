# 第二波整合驗證（2026-10-19）

已在隔離分支 codex/wave2-integration 整合三組並驗證，準備以 fast-forward 合併本機 main；未 push、發佈或建立 PR。原主工作區仍位於 feat/postgres-and-machine-scan，未提交的 AI／OEM 修改不包含在本次整合，不切換或覆寫該工作區。

## 整合範圍

| 成果 | 原分支／版本 | 驗證與限制 |
| --- | --- | --- |
| 正式訓練與評估 | codex/wave2-training @2783574 | 官方 Gemma 固定126步；原模型及全新程序重載後各128題。逐題重新計分、資料／protocol／實際adapter及config雜湊已獨立核對。QLoRA全部拒答，保留集recall由97.78%降至0%，不啟用此adapter。一般LoRA只有2步資源probe，無完整品質成績。 |
| 維修知識圖譜 | codex/wave2-knowledge-graph @346aa3a | 來源版本、主管審查、撤回失效、多跳引用與角色／機型過濾；同標題案例／手冊段落隔離及舊歧義關係停用已回歸。品質評估為小型合成固定題集，不能代表現場維修成效。 |
| 外部工單介接 | codex/wave2-ticket-integration @bb0a1cc | HMAC入口、CSV、去重／版本、未知機台待對應、transactional outbox及重試／lease／dead-letter；對接本機模擬器，未串企業系統。 |
| 既有成果 | feat/postgres-and-machine-scan @67583a5、docs/model-selection @0b57103 | 保留PostgreSQL／手機掃描功能與Gemma選型說明。新增圖譜及介接尚未在PostgreSQL實測，不能沿用既有PG驗證當作新功能驗收。 |

## 完整整合測試

程式版本：3ec120adab4ead7e3fbde383bb9b15457e03e526。後續僅增加此紀錄、JUnit副本與README測試數字。

- Windows完整pytest：148 passed，207.09秒，failures/errors/skipped均為0；唯一warning為既有Starlette/httpx deprecation。
- JUnit：[原始測試結果](../artifacts/wave2-integration-tests-20261019.xml)，已由check_test_report.py確認非零測試且無失敗／跳過。
- 涵蓋兩模式全路由權限矩陣、圖譜正反例與來源失效、API／CSV／outbox隔離故障情境、實際OCR／掃描回歸及訓練資料／評分／生命週期測試。
- 整合過程補上5條既有scan路由權限列，保留覆蓋率守門；不是忽略未列路由。
- 9個scan／graph／integrations靜態頁面與資產已驗證可載入且帶嚴格CSP；Node語法與scan_race檢查通過。
- 獨立CPU小模型fixture完成1個更新、adapter保存／全新重載及快取對照，重載誤差0。這只驗證工具邏輯，不能當官方模型品質成績。
- 程序清理缺陷修正：Windows在resume前納入Job Object，根程序正常／錯誤提前退出、逾時、例外、晚生後代均清理，無關程序仍存活。最終獨立審查另實跑6項聚焦案例通過，未發現剩餘重要問題。POSIX僅靜態審查，仍待Ubuntu CI實跑。

## 重現方式

在此版本的專案根目錄執行；worktree沒有.venv時請指向既有主repo的Python：

```powershell
New-Item -ItemType Directory -Force .runtime | Out-Null
$python = 'python'
& $python -m pytest --confcutdir=. --rootdir=. tests -q -p no:cacheprovider --basetemp=.runtime/wave2-review-new --junitxml=.runtime/wave2-review-new.xml
& $python scripts/check_test_report.py .runtime/wave2-review-new.xml
node tests/scan_race.cjs
```

預期148項通過、零skip；程序清理測試只操作自身CPU fixture，不啟停使用者LLM／GPU服務。

操作說明：[圖譜](knowledge-graph.md)、[工單介接及模擬器](ticket-integration.md)、[正式訓練結果](gemma-sft-results-20261019.md)。啟動隔離展示環境後開啟graph.html與integrations.html，主管可操作審查／介接，工程師的管理API應回403。不要直接沿用或改寫運行中的正式資料庫。

## 模型與保留檔案

失敗的QLoRA adapter與checkpoints仍在predictfix-wave2-training的忽略.runtime目錄，未加入Git且未啟用；封存或移除該worktree前須另存。歷史GPU報告保留當時runner雜湊，新生命週期修正未重跑GPU。CUDA allocated／reserved、全裝置使用量與WDDM共用記憶體是不同口徑，不宣稱公平速度或顯存改善倍率。
