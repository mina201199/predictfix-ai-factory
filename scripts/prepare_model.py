"""Download official CWRU 12k drive-end files and evaluate held-out loads.

Not a health/RUL model. The three classes are all seeded faults on a lab motor.
Loads 0/1 train, 2 validation, 3 test. Same defect setup may span loads.
"""
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import joblib
import numpy as np
from scipy.io import loadmat
from sklearn.tree import DecisionTreeClassifier
from sklearn.dummy import DummyClassifier
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix, classification_report
from backend.ml import WINDOW, FEATURE_NAMES, LABELS, features

PAGE = 'https://engineering.case.edu/bearingdatacenter/12k-drive-end-bearing-fault-data'
RAW = ROOT/'data'/'cwru'
ART = ROOT/'artifacts'
RAW.mkdir(parents=True, exist_ok=True)
ART.mkdir(exist_ok=True)

def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'PredictFix-Research/0.1'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()

def main():
    html = download(PAGE).decode('utf-8')
    anchors = re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S)
    links = {re.sub('<[^>]+>', '', text).strip(): urljoin(PAGE, url) for url, text in anchors}
    rows = []
    records = []
    replay = []
    prefixes = {'inner_race':'IR007_', 'ball':'B007_', 'outer_race':'OR007@6_'}
    for label, prefix in prefixes.items():
        for load in range(4):
            name = prefix+str(load)
            url = links[name]
            filename = url.rsplit('/', 1)[-1]
            target = RAW/filename
            if not target.exists():
                target.write_bytes(download(url))
            content = target.read_bytes()
            mat = loadmat(target)
            key = next(k for k in mat if k.endswith('_DE_time'))
            signal = np.asarray(mat[key]).reshape(-1)
            # Non-overlapping windows, every file assigned to one partition.
            count = min(len(signal)//WINDOW, 56)
            for index in range(count):
                values = signal[index*WINDOW:(index+1)*WINDOW]
                rows.append((features(values), label, load, filename))
                if load == 3 and index < 5:
                    replay.append({'sample_id':name+'-'+str(index), 'file':filename,
                                   'load_hp':load, 'window_index':index, 'expected':label,
                                   'signal':values.tolist()})
            records.append({'name':name, 'file':filename, 'url':url, 'load_hp':load,
                            'label':label, 'windows':count, 'sha256':hashlib.sha256(content).hexdigest()})
            print('prepared', name, filename, count, flush=True)
    x = np.array([r[0] for r in rows])
    y = np.array([r[1] for r in rows])
    loads = np.array([r[2] for r in rows])
    train, val, test = loads <= 1, loads == 2, loads == 3
    model = DecisionTreeClassifier(max_depth=8, min_samples_leaf=3,
                                   class_weight='balanced', random_state=42)
    model.fit(x[train], y[train])
    baseline = DummyClassifier(strategy='most_frequent').fit(x[train], y[train])
    classes = list(model.classes_)
    def evaluate(mask, estimator):
        pred = estimator.predict(x[mask])
        return {'accuracy':float(accuracy_score(y[mask], pred)),
                'macro_f1':float(f1_score(y[mask], pred, average='macro')),
                'confusion_matrix':confusion_matrix(y[mask], pred, labels=classes).tolist(),
                'per_class':classification_report(y[mask], pred, output_dict=True, zero_division=0)}
    report = {'model_version':'cwru-tree-v1', 'task':'known_seeded_fault_classification',
              'created_at':datetime.now(timezone.utc).isoformat(), 'source':PAGE,
              'classes':classes, 'labels':LABELS, 'sample_rate_hz':12000,
              'window_size':WINDOW, 'features':FEATURE_NAMES,
              'split':{'train_load_hp':[0,1], 'validation_load_hp':[2], 'test_load_hp':[3],
                       'train_windows':int(train.sum()), 'validation_windows':int(val.sum()),
                       'test_windows':int(test.sum())},
              'validation':evaluate(val, model), 'test':evaluate(test, model),
              'baseline_test':evaluate(test, baseline), 'files':records,
              'limitations':['No healthy class; all examples have seeded faults.',
                             'No health percentage, severity, RUL, or 7-day failure probability.',
                             'Load holdout is not an unseen bearing or unseen factory test.',
                             'Windows within a file are correlated; independent test files = 3.',
                             'Real CNC spindle use requires new data and validation.']}
    joblib.dump(model, ART/'bearing-model.joblib')
    (ART/'model-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (ART/'replay.json').write_text(json.dumps(replay, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'validation':report['validation']['macro_f1'], 'test':report['test']['macro_f1'],
                      'baseline':report['baseline_test']['macro_f1']}, indent=2))

if __name__ == '__main__':
    main()
