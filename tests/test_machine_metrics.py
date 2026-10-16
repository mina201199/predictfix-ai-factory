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
