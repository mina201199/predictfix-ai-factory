import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import machine_metrics

NOW=datetime(2026,10,16,8,0,tzinfo=timezone.utc)


def ticket(days_ago,closed_hours,preventive=False):
  created=NOW-timedelta(days=days_ago)
  return {'created_at':created,'closed_at':created+timedelta(hours=closed_hours) if closed_hours is not None else None,'preventive':preventive}


def test_reliability_needs_enough_samples():
  result=machine_metrics.reliability([ticket(10,5),ticket(5,None)])
  assert result['failures']==2
  assert result['mtbf_days'] is None and result['mttr_hours'] is None


def test_reliability_values():
  result=machine_metrics.reliability([ticket(30,4),ticket(20,6),ticket(10,None)])
  assert result['mtbf_days']==10.0 and result['mttr_hours']==5.0
  assert result['mtbf_samples']==2 and result['mttr_samples']==2


def test_preventive_maintenance_is_not_a_failure():
  result=machine_metrics.reliability([ticket(30,4),ticket(25,1,preventive=True),ticket(20,6),ticket(10,2)])
  assert result['failures']==3 and result['mtbf_days']==10.0 and result['mttr_hours']==4.0


def test_no_tickets():
  assert machine_metrics.reliability([])=={'failures':0,'mtbf_days':None,'mttr_hours':None,'mtbf_samples':0,'mttr_samples':0}


def test_closed_at_uses_last_approval_not_procedure_approval():
  workflow={'approved_at':'2026-01-01T00:00:00+00:00','reviews':[
    {'decision':'approve','at':'2026-01-20T00:00:00+00:00'},
    {'decision':'reject','at':'2026-02-01T00:00:00+00:00'},
    {'decision':'approve','at':'2026-02-03T00:00:00+00:00'}]}
  assert machine_metrics.closed_at(workflow)==datetime(2026,2,3,tzinfo=timezone.utc)


def test_closed_at_without_approval():
  assert machine_metrics.closed_at({})is None
  assert machine_metrics.closed_at({'reviews':[{'decision':'reject','at':'2026-02-01T00:00:00+00:00'}]}) is None


def test_naive_timestamps_are_treated_as_utc():
  # SQLite 讀回的 DateTime 會遺失時區，必須視為 UTC 才能和有時區的審核時間相減
  assert machine_metrics.utc(datetime(2026,1,1,0,0)).tzinfo is not None
  assert machine_metrics.utc('2026-01-01T00:00:00')==datetime(2026,1,1,tzinfo=timezone.utc)


def overview(**changes):
  base={'machine':{'id':'CNC-01','name':'立式加工中心','machine_model':None},
        'live':{'status':'運行正常','risk':12,'temp':48,'vib':2.1,'util':68},
        'parts':[{'name':'主軸軸承','health':93,'remaining':540,'note':'潤滑與振動穩定。'},
                 {'name':'切削刀具','health':78,'remaining':72,'note':'已累積 168 分鐘切削時間，建議檢查刃口磨耗。'}],
        'people':{'responsible':{'name':'Amy Chen','on_duty':True},'last_inspection':None},
        'in_progress':[],'history':[],'stock':[],
        'maintenance':{'next_inspection':'2026-10-20','plans':[]},
        'reliability':{'failures':4,'mtbf_days':60.5,'mttr_hours':12.3}}
  return {**base,**changes}


ALLOWED_TYPES={'part','ticket','manual','plan','stock'}


def test_rule_summary_flags_worn_part():
  result=machine_metrics.rule_summary(overview())
  assert len(result['summary'])==3 and all(result['summary'])
  assert 2<=len(result['suggestions'])<=4
  assert any(s['source']=={'type':'part','ref':'切削刀具','label':'切削刀具'} for s in result['suggestions'])
  assert all(s['source']['type'] in ALLOWED_TYPES for s in result['suggestions'])


def test_rule_summary_lists_open_ticket_and_low_stock_first():
  data=overview(in_progress=[{'id':'WO-1','issue':'冷卻泵異音','engineer':'Alex Lin','status':'維修中','latest_log':{'note':'拆換軸封'}}],
                stock=[{'part':'主軸軸承','item_id':'PART-1','name':'主軸軸承 6206','quantity':0,'minimum':2,'low':True}])
  refs=[s['source']['ref'] for s in machine_metrics.rule_summary(data)['suggestions']]
  assert 'WO-1' in refs and 'PART-1' in refs


def test_rule_summary_without_any_measurements():
  parts=[{'name':'主軸','health':None,'remaining':None,'note':'尚無量測資料，健康度未知。'},{'name':'刀具','health':None,'remaining':None,'note':''}]
  data=overview(live={'status':'待建檔','risk':None,'temp':None,'vib':None,'util':None},parts=parts,
                people={'responsible':None,'last_inspection':None},maintenance={'next_inspection':None,'plans':[]},
                reliability={'failures':0,'mtbf_days':None,'mttr_hours':None})
  result=machine_metrics.rule_summary(data)
  assert len(result['summary'])==3 and '尚無資料' in ''.join(result['summary'])
  assert len(result['suggestions'])>=2


def test_validated_llm_output_drops_invented_sources():
  allowed=machine_metrics.allowed_sources(overview(),[{'ref':'PF-MAN-SPINDLE-001#2','title':'主軸手冊'}])
  output={'summary':['一','二','三'],'suggestions':[
    {'text':'檢查刀具','source_type':'part','source_ref':'切削刀具'},
    {'text':'依手冊潤滑','source_type':'manual','source_ref':'PF-MAN-SPINDLE-001#2'},
    {'text':'捏造的工單','source_type':'ticket','source_ref':'WO-404'}]}
  result=machine_metrics.validated_llm_output(output,allowed)
  assert [s['source']['ref'] for s in result['suggestions']]==['切削刀具','PF-MAN-SPINDLE-001#2']
  assert result['suggestions'][1]['source']['label']=='主軸手冊'


def test_validated_llm_output_rejects_too_few_or_malformed():
  allowed=machine_metrics.allowed_sources(overview(),[])
  assert machine_metrics.validated_llm_output({'summary':['一','二','三'],'suggestions':[
    {'text':'檢查刀具','source_type':'part','source_ref':'切削刀具'}]},allowed) is None
  assert machine_metrics.validated_llm_output({'summary':['只有一行'],'suggestions':[]},allowed) is None
  assert machine_metrics.validated_llm_output(None,allowed) is None


def test_invalid_llm_field_types_fall_back_without_exception():
  allowed=machine_metrics.allowed_sources(overview(),[])
  invalid=[42,{'text':42,'source_type':'part','source_ref':'切削刀具'},
           {'text':'檢查','source_type':'part','source_ref':[]},
           {'text':'檢查','source_type':{},'source_ref':'切削刀具'}]
  for value in invalid:
    suggestions=value if isinstance(value,int) else [value]
    assert machine_metrics.validated_llm_output({'summary':['一','二','三'],'suggestions':suggestions},allowed) is None
