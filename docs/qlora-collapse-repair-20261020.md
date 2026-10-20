# QLoRA 全拒答診斷與修正（2026-10-20）

狀態：已完成正式舊 adapter 診斷與修正實作；新的正式訓練／獨立評估尚未完成，不預設改善。

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

v3保留集已看過，留作歷史紀錄。新的v4有100題、10個未使用語意家族，家族、ID與問題皆不和v2或v3重複；validation仍為原固定28題。v4沿用同一作者的任務風格與規則標註，不是外部獨立專家或實廠資料。資料與protocol在正式執行前凍結，禁止依其結果調參。

正式比較分開列validation／holdout、positive／no_answer／injection及family；重點包含正例recall、precision、空答案拒答率與整體拒答比例，不以exact match增加掩蓋正例歸零。模型合規、維修因果與可否復機均不由這個選段實驗證明。

## 執行與驗證

```powershell
$python = 'C:/Users/User/Desktop/ai factory/predictfix-ai-factory/.runtime/qlora-env/Scripts/python.exe'
& $python scripts/run_gemma_sft_campaign.py --scope qlora --max-hours 1 --runtime-dir '../predictfix-ai-factory/.runtime' --run-dir '.runtime/qlora-repair-20261020' --protocol training/gemma-sft-protocol-v2.json --holdout training/selection-holdout-v4-repair.json
```

此命令序列執行基準、126步訓練與全新模型重載評估，輸出資料夾須不存在。使用相同官方快取，不重新下載；不自動部署或替換現有GGUF服務。所有耗時均受其他背景工作影響，CUDA配置器數字不當作獨占實體顯存。

使用者要求先完成本次QLoRA修正，暫不push。Ubuntu CI與POSIX實跑仍待授權，不把Windows結果當Linux驗證。

小型官方權重診斷已實際跑完固定32步：最終正例選S3:P4、空金標題回[]，兩題皆正確。這是重複兩題的訓練能力檢查，非正式泛化成績；含原始輸出與診斷程式的[完整紀錄](../artifacts/qlora-decision-overfit-20261020.json)。CPU loss檢查確認只在決策位置產生梯度；官方tokenizer確認126訓練、28驗證及100新測試均無超長或截斷。
