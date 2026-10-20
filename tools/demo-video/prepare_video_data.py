"""Prepare fictional staff, qualifications and shifts on the local demo server for the video.

Only talks to an explicitly enabled local demo instance; refuses anything else.
"""
import sys
from datetime import datetime, timedelta, timezone

import httpx

BASE = 'http://127.0.0.1:8082'
QUAL = 'ATC 換刀機構維修'

# username -> (specialty, skills, qualifications, attendance or None for no shift)
STAFF = {
    'amy':   ('換刀機構', ['換刀', '刀庫'], [QUAL], 'present'),
    'alex':  ('換刀機構', ['換刀'], [], 'present'),
    'bob':   ('刀庫與 ATC', ['換刀', '刀庫'], [QUAL], 'leave'),
    'grace': ('主軸潤滑', ['主軸', '潤滑'], [], 'present'),
}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    c = httpx.Client(base_url=BASE, timeout=60)
    cfg = c.get('/api/auth/config').json()
    if cfg['app_mode'] != 'demo' or not cfg['demo_mode']:
        raise SystemExit('Refusing: target is not an enabled demo instance.')
    r = c.post('/api/auth/demo', json={'role': 'supervisor'})
    r.raise_for_status()
    c.headers['X-CSRF-Token'] = r.json()['csrf']

    now = datetime.now(timezone.utc)
    startsAt = now - timedelta(minutes=30)
    endsAt = now + timedelta(hours=6)
    duties = c.get('/api/duties').json()
    for user, (specialty, skills, quals, attendance) in STAFF.items():
        c.put(f'/api/admin/users/{user}/profile',
              json={'specialty': specialty, 'skills': skills, 'qualifications': quals}).raise_for_status()
        # 無班次的人員只更新專長；過期班次不能阻擋本次展示排班。
        if attendance is None or any(d['username'] == user
            and datetime.fromisoformat(d['starts_at']) < endsAt
            and datetime.fromisoformat(d['ends_at']) > startsAt for d in duties):
            continue
        c.post('/api/duties', json={
            'username': user, 'starts_at': startsAt.isoformat(),
            'ends_at': endsAt.isoformat(), 'attendance': attendance,
            'capacity_minutes': 240, 'note': '影片示範虛構班次'}).raise_for_status()
    for p in c.get('/api/dispatch', params={'part': '換刀'}).json():
        print(p['name'], p['eligible'], p['score'], p['reasons'])


if __name__ == '__main__':
    main()
