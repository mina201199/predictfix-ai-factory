"""Seed back-dated, clearly labelled DEMO repair history for CNC-01..CNC-18.

History needs creation and closing times in the past, which the API cannot set, so this
writes to the demo database directly. It refuses production mode and only runs once.
"""
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

MARKER='machine_history_seed_v1'
PREFIX='【DEMO 歷史】'
SUPERVISOR='陳主管'
# 每筆是（問題、結案說明、工時分鐘）；內容是虛構的示範資料
CASES=[
  ('主軸振動偏高，運轉時有異音','更換主軸軸承並重新預壓，空轉振動由 4.6 降到 1.8 mm/s，復測通過',240),
  ('切削刀具崩刃，加工面粗糙','更換刀片並校正刀長補正，試切三件尺寸與粗糙度合格',90),
  ('冷卻液流量不足，工件溫度升高','清洗濾網與管路，更換泵浦密封，流量恢復到 18 L/min',150),
  ('進給螺桿定位偏差','補充潤滑並重新設定背隙補正，定位誤差回到 5 μm 以內',180),
  ('換刀時刀庫卡刀','調整刀庫定位與夾爪彈簧，連續換刀 50 次無異常',120),
  ('主軸溫度升高觸發警報','清潔散熱風扇與油冷機濾網，熱機 1 小時溫升正常',100),
  ('潤滑油壓力偏低','更換潤滑泵濾芯並補油，壓力回到 1.5 bar',75),
  ('防護門感測器間歇異常','重新固定感測器並更換接頭，開關門 30 次訊號穩定',60),
]
OPEN_CASES=[
  ('主軸軸承溫度持續上升，待確認潤滑狀態','已拆下前蓋量測軸承溫度，等待潤滑脂到料'),
  ('冷卻泵異音，流量逐漸下降','已確認泵浦軸封滲漏，正在拆換軸封'),
  ('刀長量測數值飄移','正在清潔量測頭並重新校正'),
]


def seed_history(seed=20261016):
  if os.getenv('APP_MODE','production')!='demo':
    raise SystemExit('seed_machine_history 只能在 demo 模式執行，避免把虛構資料寫進正式資料庫')
  from sqlalchemy import select
  from backend import store
  from backend.operations import PEOPLE
  rng=random.Random(seed)
  now=datetime.now(timezone.utc)
  people=[(p['name'],p['name'].split()[0].lower()) for p in PEOPLE]
  with store.Session() as db:
    if db.scalar(select(store.Audit).where(store.Audit.kind==MARKER)):
      return {'machines':0,'tickets':0,'skipped':True}
    machines=[m.id for m in db.scalars(select(store.Machine).order_by(store.Machine.id)).all() if m.id in {f'CNC-{n:02}' for n in range(1,19)}]
    count=0
    for index,machineId in enumerate(machines):
      days=sorted(rng.sample(range(30,331),3+rng.randint(0,3)),reverse=True)
      for number,daysAgo in enumerate(days,1):
        issue,note,minutes=rng.choice(CASES)
        name,username=rng.choice(people)
        created=now-timedelta(days=daysAgo,hours=rng.randint(0,8))
        closed=created+timedelta(hours=rng.uniform(2,30))
        ticketId=f'HIST-{machineId}-{number:02}'
        db.add(store.Ticket(id=ticketId,machine=machineId,issue=PREFIX+issue,engineer=name,status='已完成',created_at=created,completion_note=note))
        db.add(store.Workflow(id=ticketId,payload=json.dumps({'source':'demo_history_seed','reviews':[
          {'reviewer':SUPERVISOR,'decision':'approve','note':'復測紀錄確認通過','at':closed.isoformat()}]},ensure_ascii=False)))
        db.add(store.WorkLog(id=ticketId+'-L1',ticket_id=ticketId,username=username,minutes=minutes,note=note,created_at=closed-timedelta(minutes=30)))
        count+=1
      # 約三分之一的機台有正在處理的工單，讓「正在進行」區塊有內容
      if index%3==0:
        issue,note=OPEN_CASES[(index//3)%len(OPEN_CASES)]
        name,username=people[index%len(people)]
        created=now-timedelta(days=1+index%3,hours=2)
        ticketId=f'HIST-{machineId}-OPEN'
        db.add(store.Ticket(id=ticketId,machine=machineId,issue=PREFIX+issue,engineer=name,status='維修中',created_at=created))
        db.add(store.Workflow(id=ticketId,payload=json.dumps({'source':'demo_history_seed','remaining_minutes':90},ensure_ascii=False)))
        db.add(store.WorkLog(id=ticketId+'-L1',ticket_id=ticketId,username=username,minutes=45,note=note,created_at=now-timedelta(hours=3)))
        count+=1
    db.add(store.Audit(kind=MARKER,request_id=f'{seed}',payload=json.dumps({'machines':len(machines),'tickets':count,'source':'demo_history_seed'})))
    db.commit()
  return {'machines':len(machines),'tickets':count}


if __name__=='__main__':
  print(json.dumps(seed_history(),ensure_ascii=False))
