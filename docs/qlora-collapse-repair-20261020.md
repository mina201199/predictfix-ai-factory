# QLoRA 全拒答診斷與修正（2026-10-20）

狀態：舊adapter診斷與v2候選已完成；v2仍在訓練正例拒答。v3數值修正已通過梯度回歸，正式訓練／評估尚未完成，不預設改善。

## 已量到的原因

舊版 loss 對每題所有答案 token 平均，再每題更新一次。實際126題有43題空答案、83題非空，並不是空答案占多數；但短答案只有6個監督 token，首分支的1/N權重較大。以實際長度加總，空答案的首分支有效權重為52.722%。長正例中，格式與容易預測的段落ID又把是否拒答的錯誤稀釋。

在舊最終 adapter 的正例 `lathe-chuck-03`，直接以官方權重、同量化與裝置拆分重播：首分支空答案logit為29.8248，非空為29.6708，故greedy選空。其餘gold-prefix答案token幾乎全部機率大於0.98；此首分支錯誤占答案NLL的98.257%。這解釋了低平均loss與全拒答為何可同時出現。

該題完整teacher-forced forward、只給gold prefix的forward及cached受限生成，首分支logits一致。未發現標籤全部為空、雙重shift、chat prefix或保存／重載不一致的證據。這是已確認的目標函式失衡與分支捷徑，仍不能聲稱已排除所有可能貢獻因素。

原始證據：[診斷統計](../artifacts/qlora-collapse-diagnosis-20261020.json)、[官方模型forward對照](../artifacts/qlora-collapse-forward-probe-20261020.json)。舊GPU報告及舊protocol原樣保留。

## 修正與實驗設計

- `selection_decisions.py` 只對grammar真正有多個選項的位置計算允許token間的cross-entropy。
- 每題第一個拒答／選段分支權重為1；其餘選段分支的loss平均後總權重為1。grammar強制的格式token及結尾不算loss，答案長短不再改變首分支權重。
- 訓練仍使用原來126題、原順序、相同初始化、rank8、alpha16、dropout0.05、AdamW、learning rate0.0002、clip1及一次epoch。改變的是訓練目標，不能把效果歸因為單純QLoRA硬體差異。
- 先做只使用兩筆訓練題的32步診斷，確認正例與拒答能同時學會；這不算正式品質成績，也不依測試集挑選設定。
- 正式實驗使用最後第126步adapter，不根據holdout挑checkpoint。先跑匹配的未微調nf4基準，訓練後在全新程序重載adapter，再評估。

## 新測試資料與限制

v3保留集已看過，留作歷史紀錄。新的v4有100題、10個新來源群組（部分設備主題與舊資料相近，不是設備語意完全不重複），家族、ID與問題皆不和v2或v3重複；validation仍為原固定28題。v4沿用同一作者的任務風格與規則標註，不是外部獨立專家或實廠資料。資料與protocol在正式執行前凍結，禁止依其結果調參。

正式比較分開列validation／holdout、positive／no_answer／injection及family；重點包含正例recall、precision、空答案拒答率與整體拒答比例，不以exact match增加掩蓋正例歸零。模型合規、維修因果與可否復機均不由這個選段實驗證明。

## 執行與驗證

```powershell
$python = 'C:/Users/User/Desktop/ai factory/predictfix-ai-factory/.runtime/qlora-env/Scripts/python.exe'
& $python scripts/run_gemma_sft_campaign.py --scope qlora --max-hours 1 --runtime-dir '../predictfix-ai-factory/.runtime' --run-dir '.runtime/qlora-repair-20261020' --protocol training/gemma-sft-protocol-v2.json --holdout training/selection-holdout-v4-repair.json
```

此命令序列執行基準、126步訓練與全新模型重載評估，輸出資料夾須不存在。使用相同官方快取，不重新下載；不自動部署或替換現有GGUF服務。所有耗時均受其他背景工作影響，CUDA配置器數字不當作獨占實體顯存。

使用者要求先完成本次QLoRA修正，暫不push。Ubuntu CI與POSIX實跑仍待授權，不把Windows結果當Linux驗證。

小型官方權重診斷已實際跑完固定32步：最終正例選S3:P4、空金標題回[]，兩題皆正確。這是重複兩題的訓練能力檢查，非正式泛化成績；含原始輸出與診斷程式的[完整紀錄](../artifacts/qlora-decision-overfit-20261020.json)。CPU loss檢查確認只在決策位置產生梯度；官方tokenizer確認126訓練、28驗證及100新測試均無超長或截斷。

## v2正式候選暴露的第二個原因：softcap飽和

v2完整126步後，訓練正例feed-servo-19仍輸出[]。空／非空分支logits為29.9995193與29.9991798，近乎同為上限30；反推raw logits約176與168，softcap導數僅0.0000320與0.0000547。這項判斷使用訓練題probe，尚未讀取v4測試分數來選擇修正。原始v2基準、訓練、重載評估報告分別保存在artifacts的qlora-repair-capped系列。

當raw logits都很大時，`30*tanh(raw/30)`會把錯誤次序壓成接近相等；進一步共同推高兩者可使錯誤CE接近ln(2)，卻沒有學對次序。這是數值上不理想的平坦方向，而非保存錯誤。CPU fixture實際呼叫production loss：錯誤分數176對168的梯度norm只有0.000031716，回歸測試確實失敗。

v3只把**條件決策訓練loss**改用raw logits，移除這個飽和平坦方向；首分支與其餘分支權重不變。相同CPU fixture的梯度norm恢復為1.413739，梯度方向正確，並驗證共同平移兩個分數不會降低loss。生成端的softcap與grammar完全不改；v1及v2仍能用各自凍結protocol重跑舊loss，不改寫歷史。

這不是把threshold改成強迫作答：raw-logit CE仍允許空答案，依金標學習。其最終品質與是否過度拒答，必須由完成訓練後的逐題評估證明。

```powershell
& $python scripts/check_selection_loss_runtime.py
& $python scripts/run_gemma_sft_campaign.py --scope qlora --max-hours 1 --runtime-dir '../predictfix-ai-factory/.runtime' --run-dir '.runtime/qlora-repair-raw-20261020' --protocol training/gemma-sft-protocol-v3.json --holdout training/selection-holdout-v4-repair.json
```

原126題順序、初始化、rank、learning rate與v4資料皆不變；使用新的v3protocol與獨立輸出資料夾。v4是同作者合成家族，v2先前曾計算其評估但封存未讀，修正選擇只根據訓練probe與數值測試。不得把它描述成只執行過一次的外部專家盲測。


## v3完整實測結果：數值修正有效，任務仍未達可用

126次optimizer更新完整完成，儲存adapter後由全新模型重載，probe logits最大誤差0。adapter SHA256為6e7ce963f52c9b49fac5d274d9dbb194b14e871993f8662c94fa00b709d52fc0。154項完整測試通過，無skip。

|100題合成保留評估|原模型NF4|v2 capped|v3 raw|
|---|---:|---:|---:|
|Exact match|13%|40%|30%|
|Precision|31.80%|0%|60%|
|Recall|92.22%|0%|66.67%|
|空金標正確拒答|0/40|40/40|0/40|

v3保留集100題全部固定選一段；包括validation的128題共有126題一段、1題兩段、1題三段。全拒答消失，但空金標40題全錯，多段答案仍漏選。validation EM為32.14%；保留集positive EM60%、precision100%、recall71.43%，不能用這些局部改善掩蓋拒答失敗。保留集injection EM從原模型20%降為0%，雖未選入注入段落，任務答案仍不正確。

證據見artifacts/qlora-repair-comparison-20261020.json、raw-base/train/eval報告與adapter-integrity報告。此候選不部署、不宣稱完整修復；下一輪只驗證504題覆蓋量，已曝光v4不再作未見測試。原先52.7%描述僅為inverse-length名義權重，並非實測梯度占比。


## 504題單一變項對照已完成

使用者授權最多90分鐘，完整流程實際4757.187秒（79.29分鐘，背景工作未受控）。依凍結規格`gemma-sft-protocol-v4-coverage.json`完成504次optimizer更新、401626序列tokens與1806個監督決策位置。只增加訓練覆蓋量與相應步數，其餘模型、raw決策loss、LR、rank、seed、batch與生成流程不變。原126題順序保留；第126步checkpoint與上一輪最終adapter SHA256完全相同，確認前綴訓練軌跡相同。此對照支持繼續訓練有幫助，但不能單獨區分「新題覆蓋」與「更多更新步數」的效果。

|同一28題validation|原模型NF4|raw126步|raw504步|
|---|---:|---:|---:|
|完全正確（EM）|1/28（3.57%）|9/28（32.14%）|24/28（85.71%）|
|段落precision|36.00%|54.84%|92.86%|
|段落recall|93.10%|58.62%|89.66%|
|空金標正確拒答|0/9|0/9|9/9|
|有答案卻拒答|0/19|0/19|2/19|
|注入題EM|0/4|2/4|3/4|

預測段落數0/1/2/3分別11/9/5/3，不再全拒答或固定只選一段。按金標基數分組：空答案9/9正確、單段9/11正確、雙段4/6正確、三段2/2正確。多段8題合計6題完全正確；三段樣本僅2題，不足以宣稱穩健。

剩餘錯誤全部列於`artifacts/qlora-coverage-comparison-20261020.json`：`way-lube-09`、`lathe-turret-09`有答案卻回空；`lathe-turret-25`錯選一段並漏一段；`lathe-turret-13`多選一段。沒有以這些錯誤挑checkpoint或再調參。

新adapter SHA256：`ca0915324cee4b32a10ad158fe7867cf17e7c49df275d70a07f31977d732262c`。實際檔案包含410個有限LoRA tensors、12079104參數、48370272 bytes。最後504步checkpoint、保存adapter與全新模型重載雜湊一致；重載probe logits最大誤差0。各階段來源雜湊一致且與現行程式相符，原始逐題輸出獨立重評分吻合。155項完整回歸通過，failures/errors/skipped均0；既有Starlette棄用警告1項。

### 如何驗證

開啟`artifacts/qlora-coverage-comparison-20261020.json`查看`optimizerSteps:504`、`reload.passed:true`、`prefix126ExactAdapterMatch:true`、`byGoldCardinality`及4題`errors`。原始基準、訓練、重載輸出及總流程在同目錄`qlora-coverage-base/train/eval/campaign-20261020.json`。測試證據為`qlora-coverage-tests-20261020.xml`，adapter完整性為`qlora-coverage-adapter-integrity-20261020.json`。

若需檢查測試報告，在本worktree執行：

```powershell
& '../predictfix-ai-factory/.venv/Scripts/python.exe' scripts/check_test_report.py artifacts/qlora-coverage-tests-20261020.xml
```

預期tests155且failures/errors/skipped皆0。模型檔保存在`.runtime/qlora-coverage-504-20261020/qlora_train/adapter`，沒有替換服務模型。

### 結論與界線

目前已在開發validation解除全拒答與單段塌縮，數值修正加完整訓練有效；但validation已多次檢視且只有28題，不能宣稱未知案場泛化、資安或維修診斷可靠。已曝光v4 holdout本輪完全不評估，尚無新獨立測試；因此`modelReady:false`，不部署、不merge、不push、不開PR。本輪90分鐘授權已完成，不再啟動GPU。若往後要正式驗收，需另行凍結新的來源／設備主題測試集與人工標註核對，取得相應執行預算。
