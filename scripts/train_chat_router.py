"""Train a local question router; answers remain database/document backed."""
import json, hashlib
from pathlib import Path
import joblib
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts'
examples=json.loads((ROOT/'training/chat-router-examples.json').read_text(encoding='utf-8'))
original=json.loads((ART/'intent-dataset.json').read_text(encoding='utf-8'))
splits={s:[{'text':q,'intent':label} for label,group in examples.items() for q in group[s]] for s in ['train','validation','test']}
# Original test questions stay test-only; generic document labels are evaluated
# by collapsing the new specific procedure labels, rather than relabeling tests.
splits['train'] += [r for r in original['train'] if r['intent']!='documents']
splits['test'] += original['test']
sets={s:{r['text'] for r in rows} for s,rows in splits.items()}
assert not (sets['train']&sets['validation'] or sets['train']&sets['test'] or sets['validation']&sets['test'])
model=Pipeline([('text',TfidfVectorizer(analyzer='char',ngram_range=(1,3))),('classifier',LogisticRegression(C=12,max_iter=1000,random_state=42))])
model.fit([r['text'] for r in splits['train']],[r['intent'] for r in splits['train']])
baseline=joblib.load(ART/'intent-model.joblib')
def common(label):return 'documents' if label.startswith('GUIDE-') else label
def evaluate(candidate,rows,threshold=0):
    predicted=candidate.predict([r['text'] for r in rows])
    if threshold:
        scores=candidate.predict_proba([r['text'] for r in rows]).max(axis=1)
        predicted=[p if confidence>=threshold else 'unknown' for p,confidence in zip(predicted,scores)]
    cases=[{**r,'prediction':str(p),'correct':common(r['intent'])==common(str(p))} for r,p in zip(rows,predicted)]
    expected=[common(r['intent']) for r in rows];actual=[common(str(p)) for p in predicted]
    return {'accuracy':accuracy_score(expected,actual),'macro_f1':f1_score(expected,actual,average='macro',zero_division=0),'cases':cases}
validation=evaluate(model,splits['validation'])
probabilities=model.predict_proba([r['text'] for r in splits['validation']]).max(axis=1)
predictions=model.predict([r['text'] for r in splits['validation']])
thresholds=[0.30+i*0.01 for i in range(61)]
safe=[]
for threshold in thresholds:
    accepted=[(row,p) for row,p,score in zip(splits['validation'],predictions,probabilities) if score>=threshold and p!='unknown']
    if accepted and all(row['intent']==p for row,p in accepted):safe.append((len(accepted),threshold))
threshold=max(safe,key=lambda item:(item[0],-item[1]))[1] if safe else 0.90
# No hyperparameter or checkpoint selection using held-out test results.
report={'model':'zh-maintenance-router-v2','training':'TF-IDF character 1-3 grams + LogisticRegression, CPU; fixed C=12, seed=42','source':'authored questions and paraphrases, not real-user or external-expert validation','counts':{s:len(r) for s,r in splits.items()},'dataset_sha256':hashlib.sha256(json.dumps(splits,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'validation':validation,'baseline_test':evaluate(baseline,splits['test']),'candidate_test':evaluate(model,splits['test']),'limitations':['Held-out sentences share domain vocabulary; this is not factory generalization evidence.','Training changes intent and procedure selection, not language generation or equipment health prediction.','Model confidence is not probability that an answer is true.','Specific procedure ID selection is reported separately below.']}
specific=[r for r in splits['test'] if r['intent'].startswith('GUIDE-')]
report['procedure_exact_accuracy']=accuracy_score([r['intent'] for r in specific],model.predict([r['text'] for r in specific]))
report['abstention_threshold']=round(threshold,2)
report['gated_validation']=evaluate(model,splits['validation'],threshold)
report['gated_test']=evaluate(model,splits['test'],threshold)
report['promotable']=report['gated_test']['accuracy']>report['baseline_test']['accuracy'] and all(r['prediction']=='unknown' for r in report['gated_test']['cases'] if r['intent']=='unknown')
joblib.dump(model,ART/'chat-router-v2.joblib')
(ART/'chat-router-dataset.json').write_text(json.dumps(splits,ensure_ascii=False,indent=2),encoding='utf-8')
(ART/'chat-router-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:report[k] for k in ['counts','procedure_exact_accuracy','promotable']},ensure_ascii=False))
print(json.dumps({k:{m:report[k][m] for m in ['accuracy','macro_f1']} for k in ['baseline_test','candidate_test']},ensure_ascii=False))
print(json.dumps({'threshold':threshold,'gated_test_accuracy':report['gated_test']['accuracy']},ensure_ascii=False))
