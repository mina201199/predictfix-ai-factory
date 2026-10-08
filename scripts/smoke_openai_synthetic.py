"""Send only fixed, newly authored fictitious strings; never load factory sources."""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import openai_runtime as runtime

async def main():
    before=runtime.budget_status()
    schema={'type':'object','properties':{'selected':{'type':'array','items':{'type':'string','enum':['S1','S2']}}},
            'required':['selected'],'additionalProperties':False}
    prompt='以下為專門自寫的虛構 API 測試，無工廠資料。問題：虛構馬達異音時要記錄什麼？S1：虛構測試要求記錄異音條件與轉速。S2：虛構行政範例記錄會議日期。選相關段落編號，回傳 JSON selected。'
    output,execution=await runtime.generate_json(prompt,schema)
    vectors,reason=await runtime.embeddings(['自寫虛構測試：馬達異音與轉速記錄','自寫虛構測試：會議日期'])
    report={'model':runtime.settings()['model'],'source':'newly authored fictional smoke strings, no local manuals loaded',
            'selection_passed':output=={'selected':['S1']},'llm_used':execution.get('llm_used'),
            'reason':execution.get('reason'),'embedding_passed':bool(vectors and len(vectors)==2),
            'embedding_reason':reason,'budget_before':before,'budget_after':runtime.budget_status()}
    path=Path(__file__).resolve().parents[1]/'artifacts/openai-synthetic-smoke.json'
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))

asyncio.run(main())
