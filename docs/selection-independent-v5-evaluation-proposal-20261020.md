# 新合成獨立測試集與評估預算

最新狀態：已完成兩組各100題並通過200筆逐題重評與來源審查。整體EM改善，但多段召回退步，候選仍不適合部署。下方準備階段與預估為保留的歷史紀錄，實際結果見末節。

資料已準備，尚未取得執行評估的同意，沒有載入模型推論或重訓。候選固定為504步最終adapter，不根據新測試選checkpoint。新增資料檢查及相關回歸31項通過，零失敗、零跳過；未重跑沒有變更的整套後端測試（前次155項通過）。

## 測試內容

`training/selection-holdout-v5-independent.json`包含100題、10個新主要設備主題：超音波清洗槽、雷射刻印站、迴焊爐、定量點膠站、扭力鎖付站、動平衡檢測台、硬度試驗機、標籤貼附站、X光檢測站、織布機。這些主要設備不同於舊切削機、附屬裝置及通訊情境；一般維修用語與選段任務仍共享。

金標段落數0/1/2/3分別30/30/20/20；依kind分為positive60、no_answer20、document_injection20。注入題包含10題可選證據及10題空答案，因此空金標合計30題。每題8或9個候選段落，混合相近機型、錯誤事件、條件不符、作廢R1版本、無關資料。只有現行R3、機型／事件／條件與詢問欄位全部匹配的段落可選；作廢段落與文件中的指令不得選。每題附金標理由與完整證據文字。

與四份既有selection資料比對，ID、來源群組、題目及段落文字均無完全重複。本次逐項檢視設備清單及10種情境模板（由同一助理檢查，非人類專家覆核）；規則金標自動稽核並測試能拒絕作廢段落當金標、舊題混入。這不等於近義改寫偵測或外部專家覆核。官方tokenizer檢查平均708.8、最長752tokens，不超過1024且無截斷；最大grammar答案21tokens，不超過64。

資料與模型尚未接觸，不用新答案修改訓練。資料SHA256（UTF-8、LF）為`fdacde65fbd1612048e054ca9c9bf32e69c0b80e0fb209abdb5bc735a915bd1c`。後續若發現標註錯誤須另記版本與理由，不依模型成績改答案。

## 已凍結的比較方式

`training/selection-independent-v5-evaluation-plan.json`固定資料雜湊、官方模型版本、prompt、grammar、greedy解碼與最終504步adapter雜湊`ca0915324cee4b32a10ad158fe7867cf17e7c49df275d70a07f31977d732262c`。建議依序跑同一NF4原模型與QLoRA候選各100題；不比較其他checkpoint、不重訓、不調超參數。輸入僅question與paragraphs，金標、理由、角色標記不送入模型。

報告保留200筆原始輸出、錯誤與逾時；分別列EM、段落precision/recall、空金標拒答、有答案誤拒答、金標基數對預測基數、注入題錯選及EM、每設備群組成績。金標與題型組成不同，不能直接以新100題分數減去舊28題分數當改善幅度；本輪原模型與候選使用相同新題才是配對比較。

既有reload入口要求測試protocol與訓練protocol相同，不能直接把新資料換進舊manifest。取得評估同意後須新增獨立的eval-only入口與守門測試，同時驗證原始訓練來源及新評估計畫，不改寫歷史protocol或放寬訓練守門。該準備工作不啟動GPU；完成守門後才開始已同意的評估預算。

## 時間估算與待決定事項

上一輪28題原模型總耗時168.297秒、候選114.922秒，含模型載入及候選重載probe。直接線性換算100題約10.0及6.8分鐘；不是新測試的實測，也不適合當精準速度比較。新題輸入較短，但三段題較多；GPU及背景工作未受控，因此增加緩衝：

|選項|預估評估耗時|意義|
|---|---:|---|
|只跑候選100題|8–12分鐘|可看新題能力，但缺同題原模型對照|
|原模型＋候選各100題|18–27分鐘|建議；能判斷微調對同一批新題的影響|

建議總評估上限30分鐘，包含載入、推論與重載驗證；到時保留部分結果並停止，不延長、不悄悄補跑。新入口實作與CPU守門所需準備時間不計入GPU評估估算。這次只準備資料與計畫，不啟動評估，也不建立追蹤排程。

## 檢查方式與限制

可打開`artifacts/selection-independent-v5-preparation-20261020.json`確認100題、四份舊資料無完全重複、長度上限及`modelInferencePerformed:false`。金標資料可在測試集查看selected及label_rationale。產生器使用獨占建立，不覆寫舊資料；新增檢查在`tests/test_selection_independent_holdout.py`，測試證據為`artifacts/selection-independent-v5-preparation-tests-20261020.xml`。

這是同作者合成、不同設備來源群組的未用測試，並非企業工單或外部獨立專家驗收。每設備僅10題，100題亦非100個獨立設備群組；不得據此承諾實廠泛化、維修安全或自動復機。取得結果後不自動部署、合併或推送。


## 執行授權與入口

使用者已回覆OK，同意原模型及504步候選各100題、總預算最多30分鐘。上方「未授權」描述為準備階段紀錄；凍結plan本身不改寫，實際授權記錄於campaign。新增scripts/run_selection_independent_eval.py，與原訓練入口分離；先核對原training manifest與來源hash、504次更新ID、adapter權重／config、官方模型版本及新資料hash，再開始。候選以全新模型重載並比對原訓練probe後純推論，不建立optimizer。

```powershell
& '../predictfix-ai-factory/.runtime/qlora-env/Scripts/python.exe' scripts/run_selection_independent_eval.py --runtime-dir '../predictfix-ai-factory/.runtime' --run-dir '.runtime/selection-independent-v5-20261020'
```

父程序以既有owned-process tree隔離兩組子程序，合計1800秒硬上限；每題之間亦檢查剩餘預算。輸出目錄須全新，不覆蓋既有結果；失敗或超時不自動重跑。所有資料與候選在評估之前已凍結。


## 已完成獨立測試與成果審查

使用者授權後，以凍結資料各評估100題，原模型及504步最終候選皆正常結束，exit code0、無缺列、無跳過或逾時；合計645.234秒（10.75分鐘），低於1800秒上限。這是實際工作耗時，受背景工作影響，不拿兩組秒數宣稱受控效能差異。未訓練、未更改金標或checkpoint。

|同一100題新合成測試|原模型NF4|504步QLoRA|
|---|---:|---:|
|完全正確EM|18/100（18%）|42/100（42%）|
|段落precision|42.29%|73.33%|
|段落recall|90.77%|50.77%|
|空金標正確拒答|0/30|18/30（60%）|
|有答案卻拒答|0/70|5/70（7.14%）|
|注入題EM|0/20|10/20|
|選入注入段落|1/20|0/20|
|JSON與schema合法|100/100|100/100|

同題配對：兩組皆正確1題、只有候選正確41題、只有原模型正確17題、兩組皆錯41題。EM增加24個百分點不等於全面改善；候選58題錯誤全部保存。positive種類60題EM反而由18/60（30%）降至15/60（25%），整體提升主要伴隨拒答與干擾題改善。

### 多段問題仍未解決

|金標段落數|題數|原模型完全正確|候選完全正確|
|---|---:|---:|---:|
|0|30|0|18|
|1|30|0|18|
|2|20|4|6|
|3|20|14|0|

原模型預測2/3段為21/79題；候選預測0/1/2/3段為23/64/13/0題，完全沒有預測三段。候選在三段金標的段落recall只有36.67%。例如`independent-ultrasonic-cleaner-02`應選S1:P1、S1:P2、S3:P2，卻只選S3:P2。空金標也仍有12題錯誤作答。這表示先前28題開發validation的85.71%不能代表新情境的能力；兩資料組成不同，不直接把兩次百分比相減當同題退步量。

各設備群組候選EM依序為：超音波清洗槽40%、雷射刻印站40%、迴焊爐40%、定量點膠站40%、扭力鎖付站40%、動平衡檢測台50%、硬度試驗機30%、標籤貼附站50%、X光檢測站40%、織布機50%。每群僅10題，樣本不足以保證個別設備可靠。

### 實際驗證與可追溯檔案

獨立CPU審查重算200筆原始JSON輸出、全部metrics_by_split/kind/family，完全吻合；兩組題目ID及順序與100題凍結集一致。官方權重、資料、計畫、原訓練來源與目前推論程式hash吻合，missing_keys與mismatched_keys皆空。最終adapter hash仍為`ca0915324cee4b32a10ad158fe7867cf17e7c49df275d70a07f31977d732262c`，全新模型重載probe logits最大誤差0，參數數量與config hash亦吻合。

- `artifacts/selection-independent-v5-comparison-20261020.json`：audit_passed、200筆重評、所有分組、配對結果與全部錯題。
- `artifacts/selection-independent-v5-base_nf4-20261020.json`：原模型100筆逐題輸出及來源。
- `artifacts/selection-independent-v5-qlora_nf4_504_final-20261020.json`：候選100筆逐題輸出、重載證據及來源。
- `artifacts/selection-independent-v5-campaign-20261020.json`：整體預算、程序exit code與645.234秒耗時。
- `artifacts/selection-independent-v5-eval-guard-tests-20261020.xml`：評估前39項相關守門及回歸測試通過，failures/errors/skipped皆0；完成時再次檢查報告，未對未變來源反覆重跑測試。此前155項整套測試為較早版本結果，不能宣稱本次已完整回歸目前其他並行改動。

開啟comparison檔，應看到`status:audit_passed`、`rawRowsRescored:200`、`candidateReload.max_abs_error:0`、`modelReady:false`，再查看comparison下兩組metrics、byGoldCardinality與errors。測試報告可用既有scripts/check_test_report.py檢查。

### 結論

全拒答的數值缺陷已修正；504步候選在新測試有部分進步，但多段漏選、單段偏好與不正確作答仍在，不能宣稱選段任務全面修復或適合上線。這100題現在已曝光，往後只能作已知回歸集，不能邊看結果調參再把同集分數當獨立泛化證據。任何後續改架構／訓練或新GPU預算須另行決定，本輪不自動補跑、不重訓、不部署、不merge或push。這仍是同作者合成新情境測試，未經外部專家或實廠驗收。
