"""Reproducible development comparison, deliberately not an LLM quality claim."""
import json
import sys
from pathlib import Path
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.knowledge import CHUNKS
from backend.maintenance_ai import search


def main():
    dataset=json.loads((ROOT/'artifacts/retrieval-eval-dataset.json').read_text(encoding='utf-8'))
    report={'scope':dataset['scope'],'corpus':'builtin static synthetic corpus only',
            'limitations':'Manual-ID retrieval only; no relevance labels per passage, no answer-quality or business-effect validation.',
            'methods':{}}
    for method in ['tfidf','bm25','hybrid']:
        results=[];start=perf_counter()
        for case in dataset['cases']:
            rows=search(case['question'],chunks=CHUNKS,method=method,limit=3,
                        machine_model=case.get('machine_model','PF-VMC850-DEMO'),
                        allow_synthetic=case.get('allow_synthetic',True))
            ids=[r['id'] for r in rows]
            expected=case['expected']
            rank=ids.index(expected)+1 if expected in ids else None
            results.append({**case,'returned_ids':ids,'returned_chunks':[r['chunk_id'] for r in rows],
                            'rank':rank,'passed':expected in ids if expected else not ids})
        positives=[r for r in results if r['expected']]
        negatives=[r for r in results if not r['expected']]
        report['methods'][method]={'top3_hit_rate':round(sum(r['passed'] for r in positives)/len(positives),4),
            'mrr_at_3':round(sum(1/r['rank'] if r['rank'] else 0 for r in positives)/len(positives),4),
            'negative_no_results_rate':round(sum(r['passed'] for r in negatives)/len(negatives),4),
            'elapsed_ms':round((perf_counter()-start)*1000,2),'results':results}
    target=ROOT/'artifacts/retrieval-eval-report.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({m:{k:v for k,v in data.items() if k!='results'} for m,data in report['methods'].items()},ensure_ascii=False))


if __name__=='__main__':main()
