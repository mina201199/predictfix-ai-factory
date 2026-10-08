"""Paid requests share a durable, conservative USD3 ceiling across local processes."""
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import uuid
from contextlib import contextmanager
from decimal import Decimal
import httpx

ROOT=Path(__file__).resolve().parents[1]
# Standard text rates, USD per million tokens, verified 2026-10-08.
PRICES={'gpt-6-luna':(Decimal('0.10'),Decimal('0.50')),
        'gpt-4.1-mini':(Decimal('0.40'),Decimal('1.60')),
        'text-embedding-3-small':(Decimal('0.02'),Decimal('0'))}


def settings():
    values={}
    path=ROOT/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if line and not line.startswith('#') and '=' in line:
                key,value=line.split('=',1)
                if key.strip().startswith('OPENAI_'):
                    values[key.strip()]=value.strip().strip('\"\'')
    values.update({k:v for k,v in os.environ.items() if k.startswith('OPENAI_')})
    # Test suites must not spend the real key supplied by the user.
    enabled=values.get('OPENAI_ENABLED','1')=='1' and 'PYTEST_CURRENT_TEST' not in os.environ
    return {'key':values.get('OPENAI_API_KEY',''),'enabled':enabled,
            'model':values.get('OPENAI_MODEL','gpt-6-luna'),
            'embedding_model':values.get('OPENAI_EMBEDDING_MODEL','text-embedding-3-small'),
            'budget':values.get('OPENAI_TOTAL_BUDGET_USD','3.00'),
            'document_access':values.get('OPENAI_DOCUMENT_ACCESS','none')}


def configured():
    s=settings()
    return s['enabled'] and bool(s['key'])


def document_allowed(synthetic=False):
    scope=settings().get('document_access','none')
    return scope=='all' or (scope=='synthetic' and synthetic)


def source_allowed(source):
    """Synthetic scope authorizes existing demo constants, not imported files."""
    if settings().get('document_access')=='all':return True
    if not document_allowed(True):return False
    from .knowledge import CHUNKS
    return any(c.get('is_synthetic') and c.get('source_type') in ('synthetic_demo_manual','authored_demo_document')
               and c.get('id')==source.get('id') and c.get('text')==source.get('text') for c in CHUNKS)


@contextmanager
def connect():
    directory=ROOT/'.runtime';directory.mkdir(exist_ok=True)
    db=sqlite3.connect(directory/'openai-budget.sqlite',timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, model TEXT, charge INTEGER, status TEXT, input_tokens INTEGER, output_tokens INTEGER)')
    db.execute('CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, model TEXT, vector TEXT)')
    db.commit()
    try:
        with db:
            yield db
    finally:
        db.close()


def ceiling():
    amount=Decimal(settings()['budget'])
    if not amount.is_finite() or amount<0 or amount>3:
        raise ValueError('Budget must be between USD0 and USD3')
    return int(amount*1_000_000)


def reserve(model,input_bound,output_bound):
    if model not in PRICES:
        raise ValueError('Unpriced model blocked')
    inp,out=PRICES[model]
    # 20% safety margin; no paid hosted tools, images, retries or regional premiums.
    charge=math.ceil((Decimal(input_bound)*inp+Decimal(output_bound)*out)*Decimal('1.20'))
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        used=db.execute('SELECT COALESCE(SUM(charge),0) FROM calls').fetchone()[0]
        if used+charge>ceiling():
            raise ValueError('Budget exhausted')
        rid=uuid.uuid4().hex
        db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?)',(rid,model,charge,'reserved',None,None))
    return rid,charge


def settle(rid,model,usage,reserved):
    inp=usage.get('input_tokens',usage.get('prompt_tokens'))
    out=usage.get('output_tokens',usage.get('completion_tokens',0))
    # Missing or invalid usage retains the full reservation, including timeouts.
    if not isinstance(inp,int) or not isinstance(out,int) or inp<0 or out<0:
        return
    ir,orr=PRICES[model]
    charge=math.ceil((Decimal(inp)*ir+Decimal(out)*orr)*Decimal('1.20'))
    with connect() as db:
        db.execute('UPDATE calls SET charge=?,status=?,input_tokens=?,output_tokens=? WHERE id=?',
                   (charge,'completed' if charge<=reserved else 'bound_exceeded',inp,out,rid))
        if charge>reserved:
            # Fail closed for subsequent requests if provider usage violates the bound.
            db.execute("UPDATE calls SET charge=MAX(charge,3000000) WHERE id=?",(rid,))


def budget_status():
    with connect() as db:
        charged,requests=db.execute('SELECT COALESCE(SUM(charge),0),COUNT(*) FROM calls').fetchone()
        pending=db.execute("SELECT COUNT(*) FROM calls WHERE status!='completed'").fetchone()[0]
    cap=ceiling()
    return {'limit_usd':cap/1_000_000,'accounted_usd':charged/1_000_000,
            'remaining_usd':max(0,cap-charged)/1_000_000,'requests':requests,'unsettled_requests':pending,
            'basis':'standard token prices plus 20% margin; failures retain reservations; not account-wide billing'}


async def paid_request(endpoint,payload,output_bound=0):
    s=settings()
    if not configured():
        return None,'not_configured'
    # UTF-8 byte count upper-bounds ordinary text tokenization; extra overhead
    # covers message and structured schema framing. Keep requests small.
    encoded=json.dumps(payload,ensure_ascii=False).encode('utf-8')
    if len(encoded)>32000:
        return None,'input_too_large'
    try:
        rid,reserved=reserve(payload['model'],len(encoded)+8192,output_bound)
    except (ValueError,sqlite3.Error):
        return None,'budget_or_price_blocked'
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            r=await client.post('https://api.openai.com/v1/'+endpoint,
                headers={'Authorization':'Bearer '+s['key']},json=payload)
        if r.status_code!=200:
            return None,'provider_http_'+str(r.status_code)
        data=r.json()
        settle(rid,payload['model'],data.get('usage',{}),reserved)
        return data,None
    except (httpx.HTTPError,ValueError,KeyError,TypeError,sqlite3.Error):
        return None,'provider_or_format_error'


async def generate_json(prompt,schema):
    model=settings()['model']
    payload={'model':model,'store':False,'input':prompt,'max_output_tokens':900,
             'text':{'format':{'type':'json_schema','name':'maintenance_result','strict':True,'schema':schema}}}
    if model=='gpt-6-luna':payload['reasoning']={'effort':'none'}
    data,reason=await paid_request('responses',payload,900)
    execution={'provider':'openai','model':model,'llm_used':False}
    if reason:return None,{**execution,'reason':reason}
    try:
        content=''.join(item['text'] for output in data.get('output',[]) if output.get('type')=='message'
                        for item in output.get('content',[]) if item.get('type')=='output_text')
        result=json.loads(content)
        return result,{**execution,'llm_used':True,'usage':data.get('usage',{})}
    except (ValueError,KeyError,TypeError):
        return None,{**execution,'reason':'invalid_json'}


async def embeddings(texts):
    model=settings()['embedding_model']
    keys=[hashlib.sha256((model+'\n'+t).encode()).hexdigest() for t in texts]
    vectors={}
    with connect() as db:
        for key in keys:
            row=db.execute('SELECT vector FROM vectors WHERE id=? AND model=?',(key,model)).fetchone()
            if row:vectors[key]=json.loads(row[0])
    missing=list(dict.fromkeys(key for key in keys if key not in vectors))
    # Sequential small batches avoid parallel duplicate reservations.
    batch=[];size=0
    async def submit(batch):
        payload={'model':model,'input':[texts[keys.index(key)] for key in batch],'dimensions':512}
        data,reason=await paid_request('embeddings',payload)
        if reason:return reason
        try:
            ordered=sorted(data['data'],key=lambda row:row['index'])
            if len(ordered)!=len(batch):return 'embedding_count_mismatch'
            with connect() as db:
                for key,row in zip(batch,ordered):
                    vector=row['embedding']
                    if len(vector)!=512 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in vector):
                        return 'invalid_embedding'
                    vectors[key]=vector
                    db.execute('INSERT OR IGNORE INTO vectors VALUES (?,?,?)',(key,model,json.dumps(vector)))
        except (KeyError,TypeError,ValueError):return 'invalid_embedding'
        return None
    for key in missing:
        text=texts[keys.index(key)];n=len(text.encode('utf-8'))
        if n>12000:return None,'embedding_input_too_large'
        if batch and size+n>14000:
            reason=await submit(batch)
            if reason:return None,reason
            batch=[];size=0
        batch.append(key);size+=n
    if batch:
        reason=await submit(batch)
        if reason:return None,reason
    return [vectors[key] for key in keys],None
