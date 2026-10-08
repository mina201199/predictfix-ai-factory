import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from backend import openai_runtime as runtime


@pytest.fixture
def isolated(monkeypatch,tmp_path):
    monkeypatch.setattr(runtime,'ROOT',tmp_path)
    monkeypatch.setattr(runtime,'settings',lambda:{'key':'test-key-not-real','enabled':True,
        'model':'gpt-4.1-mini','embedding_model':'text-embedding-3-small','budget':'3.00'})


def test_concurrent_reservations_share_ceiling(isolated):
    def reserve():
        try:return runtime.reserve('gpt-4.1-mini',3_000_000,0)[0]
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:reserve(),range(4)))
    assert sum(r is not None for r in results)==2
    status=runtime.budget_status()
    assert status['accounted_usd']==2.88 and status['requests']==2
    assert runtime.budget_status()==status  # Reopening does not reset counters.


def test_usage_reconciles_and_unknown_models_block(isolated):
    rid,reserved=runtime.reserve('gpt-4.1-mini',10000,900)
    runtime.settle(rid,'gpt-4.1-mini',{'input_tokens':100,'output_tokens':20},reserved)
    assert runtime.budget_status()['accounted_usd']==.000087
    with pytest.raises(ValueError):runtime.reserve('unpriced-model',10,10)
    rid,reserved=runtime.reserve('gpt-4.1-mini',10000,900)
    before=runtime.budget_status()['accounted_usd']
    runtime.settle(rid,'gpt-4.1-mini',{},reserved)
    assert runtime.budget_status()['accounted_usd']==before


def test_failures_retain_reservations_no_retries(isolated,monkeypatch):
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kwargs):
            calls.append(url)
            return runtime.httpx.Response(429,json={'error':'rate limit'})
    monkeypatch.setattr(runtime.httpx,'AsyncClient',Client)
    result,execution=asyncio.run(runtime.generate_json('test',{'type':'object'}))
    assert result is None and execution['reason']=='provider_http_429'
    assert len(calls)==1 and runtime.budget_status()['accounted_usd']>0
    assert runtime.budget_status()['unsettled_requests']==1


def test_embedding_cache_avoids_repeat_payment(isolated,monkeypatch):
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kwargs):
            payload=kwargs['json'];calls.append(payload)
            return runtime.httpx.Response(200,json={'usage':{'prompt_tokens':10},
                'data':[{'index':i,'embedding':[.1]*512} for i in range(len(payload['input']))]})
    monkeypatch.setattr(runtime.httpx,'AsyncClient',Client)
    result,reason=asyncio.run(runtime.embeddings(['設備手冊','設備手冊']))
    assert not reason and len(result)==2 and len(calls)==1
    status=runtime.budget_status()
    again,reason=asyncio.run(runtime.embeddings(['設備手冊']))
    assert again==result[:1] and not reason and len(calls)==1
    assert runtime.budget_status()==status


def test_config_file_never_overrides_mode_and_tests_disable_key(monkeypatch,tmp_path):
    monkeypatch.setattr(runtime,'ROOT',tmp_path)
    (tmp_path/'.env').write_text('OPENAI_API_KEY=test-not-real\nAPP_MODE=production\nOPENAI_TOTAL_BUDGET_USD=3.00',encoding='utf-8')
    monkeypatch.setenv('APP_MODE','demo')
    monkeypatch.setenv('PYTEST_CURRENT_TEST','isolated')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    assert runtime.settings()['key']=='test-not-real' and not runtime.configured()
    assert runtime.os.getenv('APP_MODE')=='demo'


def test_synthetic_scope_requires_unchanged_builtin_source(monkeypatch):
    from backend.knowledge import CHUNKS
    monkeypatch.setattr(runtime,'settings',lambda:{'document_access':'synthetic'})
    source=next(c for c in CHUNKS if c.get('is_synthetic') and c.get('source_type')=='synthetic_demo_manual')
    assert runtime.source_allowed(source)
    assert not runtime.source_allowed({**source,'id':'IMPORTED-1','is_synthetic':True})
    assert not runtime.source_allowed({**source,'text':source['text']+' uploaded private text'})
    assert not runtime.document_allowed(False)


def test_unapproved_document_prompt_never_calls_provider():
    # Importing the app's database modules here would freeze DATABASE_URL before
    # test_api's isolated database fixture. Keep this integration in a subprocess.
    import subprocess
    import sys
    code='''
import asyncio
from backend import maintenance_ai, openai_runtime as runtime
runtime.configured=lambda:True
runtime.settings=lambda:{'document_access':'synthetic'}
async def forbidden(*args,**kwargs):
    raise AssertionError('Unapproved source sent to provider')
runtime.generate_json=forbidden
output,execution=asyncio.run(maintenance_ai.generate_json('private document',{},synthetic=False))
assert output is None and execution['reason']=='documents_not_authorized'
'''
    subprocess.run([sys.executable,'-c',code],check=True,capture_output=True,text=True)
