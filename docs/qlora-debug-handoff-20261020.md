# QLoRA 選段問題交接

成果基準：`codex/qlora-collapse-fix`，獨立測試成果commit `55a2481`；評估入口`45b37ff`、新資料凍結`dc41cdf`。工作樹：`C:/Users/User/Desktop/ai factory/predictfix-wave2-training`。本說明只交接，不改模型、不啟動GPU。

## 已確認、需要修正的問題

### P1：多段漏選，三段答案無法完整輸出

新100題中候選完全正確42題，原模型18題；但候選段落recall只有50.77%，低於原模型90.77%。金標三段20題，候選完全正確0/20（原模型14/20），三段組recall36.67%。候選100題預測0/1/2/3段為23/64/13/0題，偏向單段且完全沒選三段。雙段20題只有6題完全正確。

重現案例：`independent-ultrasonic-cleaner-02`金標`S1:P1,S1:P2,S3:P2`，候選只選`S3:P2`。不要只看整體EM增加而判定修好。

入口：`scripts/selection_decisions.py`的`decisionPlan`、`decisionLoss`；`scripts/run_gemma_sft.py`的`train`、`generateConstrained`；`scripts/gemma_sft_protocol.py`的`grammarAnswers`、`nextTokens`。

建議先在既有train/validation上檢查停止／繼續選下一段分支的logits、允許token、金標基數與梯度權重，分開比較teacher-forced與greedy自由生成。首個空／非空分支權重1，其餘所有決策合計權重1；後者同時負責ID與停止／繼續，可能稀釋後續選段，但目前**尚未證實**為剩餘問題根因。不要同時改loss、資料平衡及解碼，否則無法歸因。

### P1：拒答仍不可靠，不能靠少選提高precision

空金標30題只正確拒答18題，另12題錯誤選段；有答案70題中5題誤拒答。與原模型相比precision由42.29%升至73.33%，但召回大幅下降，表示更保守並不等於更正確。

請分別統計空金標誤答與有金標誤拒答，不用整體空輸出比例取代。查看上述分支是否能依相關性區分空答案，而非僅依題型／語句線索。

### P1：新情境泛化不足，開發集成績不能當驗收

固定28題validation的EM85.71%、空答案9/9；新100題EM42%、空答案18/30。兩集題型比例與版本條件不同，不能直接當同題前後退步量。新100題內的positive種類60題，候選EM15/60（25%），原模型18/60（30%）；總分改善不能掩蓋正例退步。

請檢查訓練資料是否涵蓋多意圖、現行／作廢版本、條件相近的證據；另比較段落ID token路徑、位置分布及語句模板偏差。這些是**待驗證假設**，目前沒有證據能單獨歸因於設備名稱、ID、grammar或量化。

### P2：安全干擾與資料標註仍需外部覆核

候選20題文件注入未選入注入段落，但僅10/20答案完全正確；不能將「未選注入段落」說成全部安全題通過。所有資料為同一助理撰寫的合成情境，雖新主要設備主題及原文無完全重複，仍共享任務與作者，未有人類維修專家獨立核對標註。需確認多段金標是否完整、條件及版本限制是否無歧義。

## 已修正或已排除的項目

- 歷史全拒答：原本格式token與答案長度平均loss會稀釋關鍵分支；改監督grammar決策後，仍發現softcap訓練梯度飽和，現已改用raw條件logits。舊loss與報告保留，不能把舊問題與現有漏選混為一談。
- raw loss在錯誤分數176/168的CPU梯度norm約1.4137；舊softcap約0.0000317。檢查工具：`scripts/check_selection_loss_runtime.py`（需已安裝torch的QLoRA環境，純CPU）。
- 完成504次真實更新，不是3步smoke；前126步adapter與先前126步最終adapter雜湊完全相同。
- 官方模型權重、資料、來源、adapter與config雜湊核對通過；全新模型重載probe最大logit誤差0；兩組100筆輸出相同題目順序，獨立重評200筆吻合。
- JSON/schema兩組均100%合法；不能直接將失敗歸咎於JSON解析、保存／重載或缺失題目。量化是否影響品質仍未有對照證據。

## 程式與證據地圖

|用途|檔案|
|---|---|
|目前loss與分支權重|`scripts/selection_decisions.py`|
|訓練、手動forward、greedy trie生成|`scripts/run_gemma_sft.py`|
|grammar與評分定義|`scripts/gemma_sft_protocol.py`|
|504步原始凍結規格|`training/gemma-sft-protocol-v4-coverage.json`|
|原始train/validation資料|`training/selection-dataset-v2.json`|
|新測試集及每題理由|`training/selection-holdout-v5-independent.json`|
|新資料產生與重複／金標稽核|`scripts/build_selection_independent_holdout.py`|
|獨立評估及來源守門|`scripts/run_selection_independent_eval.py`|
|兩組成績、所有分組與錯題|`artifacts/selection-independent-v5-comparison-20261020.json`|
|候選100筆原始輸出與reload|`artifacts/selection-independent-v5-qlora_nf4_504_final-20261020.json`|
|原模型100筆原始輸出|`artifacts/selection-independent-v5-base_nf4-20261020.json`|
|504步訓練逐步loss／梯度|`artifacts/qlora-coverage-train-20261020.json`|
|開發validation與前輪比較|`artifacts/qlora-coverage-comparison-20261020.json`|
|數值問題完整歷史|`docs/qlora-collapse-repair-20261020.md`|
|本輪完整評估方法與限制|`docs/selection-independent-v5-evaluation-proposal-20261020.md`|

打開comparison，應看到`rawRowsRescored:200`、`modelReady:false`、候選`errors`58筆、`byGoldCardinality`中3段EM為0。逐題可依ID回查新測試集的question、paragraphs與label_rationale，禁止依模型輸出直接修改金標。

本機adapter（未提交Git）：`.runtime/qlora-coverage-504-20261020/qlora_train/adapter`。SHA256：`ca0915324cee4b32a10ad158fe7867cf17e7c49df275d70a07f31977d732262c`。官方模型：`google/gemma-4-E2B-it`，revision `3e22461f65e89153144f8adb70e3b8c2cc9845a7`。不要用隨機權重或其他版本替代後宣稱同一對照。

## 可先做的CPU檢查

在本工作樹，以主repo的`.venv/Scripts/python.exe`執行：

```powershell
& '../predictfix-ai-factory/.venv/Scripts/python.exe' -m pytest tests/test_selection_independent_eval.py tests/test_selection_independent_holdout.py tests/test_selection_decisions.py tests/test_gemma_sft_protocol.py --confcutdir=. --rootdir=. -q -p no:cacheprovider --basetemp=.runtime/team-qlora-review
```

既有評估前紀錄為39項通過、零失敗／skip，證據`artifacts/selection-independent-v5-eval-guard-tests-20261020.xml`；這是原始版本紀錄，後續程式或環境改動應重新驗證。較早的整套155pass不代表目前其他並行修改已完成整套測試。CPU測試不載入GPU，不代表模型品質合格。

## 接手限制與下一輪驗收

先用train/validation重現與形成單一假設，提出最小變更、對應CPU回歸，再申請需要的GPU預算；目前沒有追加GPU訓練或推論授權。已曝光v3/v4/v5只能作已知回歸，不能反覆看分數調參後宣稱獨立測試。正式結論需另凍結新資料並盡可能請外部專家覆核。

驗收同時列EM、precision、recall、0/1/2/3基數、空金標拒答、有答案誤拒答、每設備與注入題，尤其檢查三段題不能再為0/20。需明確說明修正是否造成其他類別退步；不只報單一總分。

保留舊adapter、逐題輸出與失敗報告，不覆寫歷史或把部分訓練當完整結果。不要擅停其他服務、下載權重、merge、push、開PR或部署。工作樹內另有權限、介接、部署與環境檔的並行未提交修改，未納入本次QLoRA成果及交接提交；不可一起stage或覆寫。
