"""Pure reliability and summary helpers; no database or app imports so tests can load them freely."""
from datetime import datetime, timezone
from statistics import mean

# 少於這些樣本時平均值沒有意義，回傳 None 讓畫面顯示「樣本不足」
MTBF_MIN_TICKETS=3
MTTR_MIN_CLOSED=2


def utc(value):
  if value is None:return None
  if isinstance(value,str):value=datetime.fromisoformat(value)
  # SQLite 讀回的 DateTime 會遺失時區；系統一律以 UTC 寫入，所以補回 UTC
  return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def closed_at(workflow):
  # 結案時間是主管最後一次核准的審核紀錄；workflow 的 approved_at 是作業程序核准，不是結案
  approvals=[r for r in (workflow or {}).get('reviews',[]) if r.get('decision')=='approve' and r.get('at')]
  return utc(approvals[-1]['at']) if approvals else None


def reliability(tickets):
  # 定期保養產生的工單是計畫性作業，不算故障
  failures=[t for t in tickets if not t.get('preventive')]
  created=sorted(utc(t['created_at']) for t in failures)
  gaps=[(later-earlier).total_seconds()/86400 for earlier,later in zip(created,created[1:])]
  repairs=[(utc(t['closed_at'])-utc(t['created_at'])).total_seconds()/3600 for t in failures if t.get('closed_at')]
  return {'failures':len(failures),
          'mtbf_days':round(mean(gaps),1) if len(created)>=MTBF_MIN_TICKETS else None,
          'mttr_hours':round(mean(repairs),1) if len(repairs)>=MTTR_MIN_CLOSED else None,
          'mtbf_samples':len(gaps),'mttr_samples':len(repairs)}
