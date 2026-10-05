import json
from pathlib import Path
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report,accuracy_score,f1_score
import joblib
ROOT=Path(__file__).resolve().parents[1]
groups={
'idle_people':['哪些同仁目前沒有工作單','哪些人沒任務','目前誰空閒','有哪些工程師沒有工作單','找沒有未結案任務的人','誰現在沒案子','哪些技師尚未接任務','有誰還沒被派工','列出零工單人員','可以找哪些空閒工程師'],
'workload':['誰的任務負荷最多','誰最忙','工程師工作量比較','各人員有多少未完成任務','哪位技師負荷最高','列出人員任務數','誰手上案件最多','目前各工程師忙碌情況','所有技師的工單量','比較目前維修負荷'],
'review':['有哪些待主管審核工單','哪些維修等主管確認','待審核的案件','主管還沒批准哪些工單','工程師已提交的維修結果','列出等待審核任務','還有幾筆待審核','主管要檢查哪些結案申請','尚未通過審核的工單','顯示待主管審核清單'],
'unassigned':['有哪些未派工工單','哪些工單還沒人處理','待指派的案件','列出還沒有工程師的任務','哪些維修還沒分配','找未派工案件','哪些工單負責人是待指派','尚未安排人員的工單','有哪些待分派維修','還沒指定技師的工作單'],
'open_tickets':['目前未結案工單有哪些','還沒完成的工單','列出待處理維修','有哪些維修中案件','哪些任務還沒結束','Amy Chen 的未完成任務','David Wu 有哪些工作單','顯示未結案維修清單','CNC14 未完成工單','待追蹤的維修任務'],
'machine_attention':['現在有哪些機台要檢查','哪些設備有警示','找高風險機台','需要保養的機器','哪些機台要檢修','風險最高的設備','哪台機器不健康','CNC03 健康度如何','有哪些零件異常的機台','有哪些設備需要維修'],
'history':['CNC14 維修過幾次','CNC03 的歷史工單','某台機器的維修紀錄','哪些機台有報修紀錄','查看歷年維修工單','列出設備報修歷史','CNC05 所有維修紀錄','機台已結案紀錄','CNC14 過去修過什麼','查詢以前的維修案件'],
'documents':['刀具什麼時候換','換刀後怎麼验收','冷卻液流量下降怎麼辦','主軸異音如何查','交班應該寫什麼','維修結案要填什麼','檢查潤滑的流程','尺寸不準要查哪裡','漏液怎麼通報','派工要考慮哪些條件']}
heldout={
'idle_people':['誰沒有維修工單？','現在哪些技師手上沒工作？','可以派給哪位沒任務的工程師？'],
'workload':['哪個人身上工單最多？','幫我看工程師的工作負荷','哪位師傅最忙？'],
'review':['有什麼單子需要主管審核？','主管還有哪些維修結果未審？','已提交但待批准的有哪些？'],
'unassigned':['還有哪幾張單沒指定人？','哪些案件還沒派給工程師？','誰都還沒接的工單有哪些？'],
'open_tickets':['Amy Chen 還有什麼工單沒結案？','目前還在修的有哪些？','CNC14 尚未結束的任務'],
'machine_attention':['哪幾台機器應該優先檢查？','目前有哪些設備需要檢修？','CNC05 現在健康嗎？'],
'history':['我要看 CNC14 以前報修的內容','CNC03 曾經維修哪些問題？','查一下機器過往的維修紀錄'],
'documents':['如何確認換刀之後可以生產？','我交班需要準備哪些資料？','冷卻循環有問題應該怎麼查？']}
train=[{'text':q,'intent':k} for k,qs in groups.items() for q in qs];test=[{'text':q,'intent':k} for k,qs in heldout.items() for q in qs]
model=Pipeline([('text',TfidfVectorizer(analyzer='char',ngram_range=(1,3))),('classifier',LogisticRegression(C=12,max_iter=500,random_state=42))]);model.fit([r['text'] for r in train],[r['intent'] for r in train]);pred=model.predict([r['text'] for r in test])
report={'model':'zh-maintenance-intent-v1','training':'TF-IDF character 1-3 grams + LogisticRegression, CPU','train_count':len(train),'test_count':len(test),'source':'手寫情境與改寫，非真實使用者、非獨立外部評估','accuracy':accuracy_score([r['intent'] for r in test],pred),'macro_f1':f1_score([r['intent'] for r in test],pred,average='macro'),'cases':[{**r,'prediction':str(p),'correct':r['intent']==p} for r,p in zip(test,pred)]}
joblib.dump(model,ROOT/'artifacts/intent-model.joblib');(ROOT/'artifacts/intent-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');(ROOT/'artifacts/intent-dataset.json').write_text(json.dumps({'train':train,'test':test},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False))
