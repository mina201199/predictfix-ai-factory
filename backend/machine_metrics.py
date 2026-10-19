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


SOURCE_TYPES=('part','ticket','manual','plan','stock')
WORN_PART=80


def fmt(value,unit=''):
  return '尚無資料' if value is None else f'{value}{unit}'


def suggestion(text,kind,ref,label=None):
  return {'text':text,'source':{'type':kind,'ref':ref,'label':label or ref}}


def rule_summary(overview):
  machine,live,people=overview['machine'],overview['live'],overview['people']
  parts=overview.get('parts') or []
  openTickets=overview.get('in_progress') or []
  reliability=overview.get('reliability') or {}
  suggestions=[]
  # 依「正在發生 → 缺料 → 快壞 → 快到期」排序，讓最急的事排在最前面
  for t in openTickets[:2]:
    note=(t.get('latest_log') or {}).get('note') or '尚無工作紀錄'
    suggestions.append(suggestion(f"工單 {t['id']}（{t['engineer']}，{t['status']}）尚未結案：{note}",'ticket',t['id']))
  for s in (s for s in overview.get('stock') or [] if s.get('low')):
    suggestions.append(suggestion(f"備品「{s['name']}」庫存 {s['quantity']}，低於安全量 {s['minimum']}，建議補料",'stock',s['item_id'],s['name']))
  for p in sorted((p for p in parts if p.get('health') is not None and p['health']<WORN_PART),key=lambda p:p['health']):
    suggestions.append(suggestion(f"{p['name']} 健康度 {p['health']}%：{p.get('note') or '建議排定檢查'}",'part',p['name']))
  for plan in (overview.get('maintenance') or {}).get('plans') or []:
    if plan.get('reminder') in ('overdue','due','soon'):
      when='已逾期' if plan['reminder']=='overdue' else f"{plan.get('days_until_due')} 天內到期"
      suggestions.append(suggestion(f"保養「{plan['title']}」{when}，請排入工單",'plan',plan['id'],plan['title']))
  # 沒有急事時，補上可以做的下一步，確保至少兩條可執行建議
  measured=sorted((p for p in parts if p.get('health') is not None),key=lambda p:p['health'])
  for p in measured[:2]:
    suggestions.append(suggestion(f"{p['name']} 健康度 {p['health']}%，依保養週期持續追蹤：{p.get('note') or ''}".rstrip('：'),'part',p['name']))
  for p in (p for p in parts if p.get('health') is None):
    suggestions.append(suggestion(f"{p['name']} 尚無量測資料，建議先建立基準量測",'part',p['name']))
  unique=[]
  for s in suggestions:
    if s['source']['ref'] not in {u['source']['ref'] for u in unique}:unique.append(s)
  responsible=people.get('responsible')
  if openTickets:
    second=f"目前有 {len(openTickets)} 張未結工單，最新是「{openTickets[0]['issue']}」（{openTickets[0]['engineer']}）"
  elif responsible:
    duty={True:'在班',False:'未在班'}.get(responsible.get('on_duty'),'出勤尚無資料')
    second=f"目前沒有未結工單；負責人 {responsible['name']}（{duty}）"
  else:
    second='目前沒有未結工單；負責人尚無資料'
  if reliability.get('mtbf_days') is not None:
    third=f"平均 {reliability['mtbf_days']} 天故障一次，平均修復 {fmt(reliability.get('mttr_hours'),' 小時')}；下次檢核 {fmt((overview.get('maintenance') or {}).get('next_inspection'))}"
  else:
    third=f"可靠度樣本不足；下次檢核 {fmt((overview.get('maintenance') or {}).get('next_inspection'))}"
  first=f"{machine['id']} {machine.get('name') or ''}：{live.get('status') or '尚無資料'}，風險 {fmt(live.get('risk'))}、溫度 {fmt(live.get('temp'),'°C')}、振動 {fmt(live.get('vib'),' mm/s')}"
  return {'summary':[first,second,third],'suggestions':unique[:4]}


def allowed_sources(overview,manuals):
  allowed={}
  for p in overview.get('parts') or []:allowed[('part',p['name'])]=p['name']
  for t in (overview.get('in_progress') or [])+(overview.get('history') or []):allowed[('ticket',t['id'])]=t['id']
  for plan in (overview.get('maintenance') or {}).get('plans') or []:allowed[('plan',plan['id'])]=plan['title']
  for s in overview.get('stock') or []:allowed[('stock',s['item_id'])]=s['name']
  for m in manuals:allowed[('manual',m['ref'])]=m['title']
  return allowed


def validated_llm_output(output,allowed):
  if not isinstance(output,dict):return None
  summary=output.get('summary')
  if not isinstance(summary,list) or len(summary)!=3 or not all(isinstance(s,str) and s.strip() for s in summary):return None
  suggestions=output.get('suggestions')
  if not isinstance(suggestions,list):return None
  kept=[]
  for item in suggestions:
    if not isinstance(item,dict) or not isinstance(item.get('text'),str) or not item['text'].strip():continue
    if not isinstance(item.get('source_type'),str) or not isinstance(item.get('source_ref'),str):continue
    key=(item.get('source_type'),item.get('source_ref'))
    # 模型只能引用我們提供的零件、工單、保養計畫、備品與手冊；捏造的來源整條丟掉
    if key in allowed:kept.append(suggestion(item['text'].strip(),key[0],key[1],allowed[key]))
  if len(kept)<2:return None
  return {'summary':[s.strip() for s in summary],'suggestions':kept[:4]}
