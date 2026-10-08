"""Add a repeatable, synthetic status/person matrix through the normal demo API."""
import argparse
from collections import Counter
from contextlib import ExitStack
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

PEOPLE = [
    ('amy', 'Amy Chen', '主軸振動升高，待確認軸承狀況', 'vibration', 4.8, 1.5),
    ('alex', 'Alex Lin', '冷卻流量不足，檢查濾網與泵浦', 'pressure', 1.2, 3.0),
    ('bob', 'Bob Wang', '防護門感測異常，檢查接點與固定', 'current', 0.2, 0.4),
    ('grace', 'Grace Huang', '換刀後尺寸偏差，核對刀補與試切', 'deviation', 35, 8),
    ('david', 'David Wu', '進給定位偏差，檢查伺服與螺桿', 'deviation', 42, 9),
    ('ivy', 'Ivy Liu', '電控間歇警報，核對 PLC 與訊號紀錄', 'current', 8.5, 5.2),
    ('eric', 'Eric Tsai', '潤滑壓力偏低，檢查油路與補油', 'pressure', 0.8, 2.2),
    ('nina', 'Nina Chang', '幾何精度偏移，安排對心與量測', 'deviation', 28, 6),
]
STATUSES = ['待指派', '已指派', '維修中', '待主管審核', '退回重修', '已完成']
PREFIX = '【DEMO 狀態組合 v1】'


def seed(base_url):
    if urlparse(base_url).hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise RuntimeError('Only a local demo server is supported.')
    with ExitStack() as stack:
        def client():
            return stack.enter_context(httpx.Client(base_url=base_url, timeout=30))

        def api(c, method, path, body=None, expected=200, key=None):
            kwargs = {'json': body} if body is not None else {}
            if key:
                kwargs['headers'] = {'Idempotency-Key': key}
            response = c.request(method, '/api' + path, **kwargs)
            if response.status_code != expected:
                raise RuntimeError(f'{method} {path}: {response.status_code} {response.text}')
            return response.json()

        supervisor = client()
        config = api(supervisor, 'GET', '/auth/config')
        if config.get('app_mode') != 'demo' or not config.get('demo_mode'):
            raise RuntimeError('Explicit demo mode is required.')

        def login(c, role, username=None):
            body = {'role': role}
            if username:
                body['username'] = username
            result = api(c, 'POST', '/auth/demo', body)
            c.headers['X-CSRF-Token'] = result['csrf']
            return result

        login(supervisor, 'supervisor')
        engineers = {}
        for username, name, *_ in PEOPLE:
            c = client()
            result = login(c, 'engineer', username)
            if result['user']['name'] != name:
                raise RuntimeError(f'Demo account identity mismatch: {username}')
            engineers[username] = c
        machines = {m['id']: m for m in api(supervisor, 'GET', '/machines')}
        machine_ids = [f'CNC-{n:02}' for n in range(1, 19)]
        if not all(mid in machines for mid in machine_ids):
            raise RuntimeError('The 18 demo CNC machines are required.')
        original = api(supervisor, 'GET', '/tickets')
        existing = {t['issue']: t for t in original}
        created, skipped, cases = [], [], []
        for status_index, status in enumerate(STATUSES):
            for person_index, (username, name, symptom, metric, before, after) in enumerate(PEOPLE):
                case = f'{status_index + 1:02}-{person_index + 1:02}'
                machine = machine_ids[(status_index * 8 + person_index) % 18]
                issue = f'{PREFIX}{case} {symptom}（{status}展示）'
                if issue in existing:
                    # Preserve changes made while demonstrating; never reset existing orders.
                    ticket = existing[issue]
                    skipped.append(ticket['id'])
                else:
                    ticket = api(supervisor, 'POST', '/tickets', {
                        'machine': machine, 'issue': issue,
                        'engineer': '待指派' if status == '待指派' else name,
                    }, 201, 'demo-status-matrix-v1-' + case)
                    tid = ticket['id']
                    path = '/tickets/' + tid
                    remaining = 0 if status in ('待主管審核', '已完成') else [15, 30, 45, 60, 90, 120, 180, 240][person_index]
                    api(supervisor, 'PUT', path + '/estimate', {
                        'remaining_minutes': remaining, 'required_qualifications': [],
                        'note': 'DEMO 虛構估時，僅供工單與人力配置展示',
                    })
                    if status not in ('待指派', '已指派'):
                        engineer = engineers[username]
                        ticket = api(engineer, 'POST', path + '/start')
                        api(engineer, 'POST', path + '/work-logs', {
                            'minutes': 15 + person_index * 5,
                            'note': 'DEMO 虛構作業：確認異常、記錄檢查與量測結果',
                        }, 201)
                        if status != '維修中':
                            ticket = api(engineer, 'POST', path + '/complete', {
                                'note': 'DEMO 虛構修復紀錄：已完成示例檢查與復測，送交主管審核；數值非現場驗收依據。',
                                'measurements': [{'metric': metric, 'before': before, 'after': after,
                                                  'conditions': 'DEMO 虛構量測條件，非實機測試'}],
                                'photo_ids': [],
                            })
                            if status in ('退回重修', '已完成'):
                                ticket = api(supervisor, 'POST', path + '/review', {
                                    'decision': 'reject' if status == '退回重修' else 'approve',
                                    'note': 'DEMO 退回：需補充不同負載條件的復測紀錄。' if status == '退回重修'
                                            else 'DEMO 核准：展示量測與修復紀錄齊備，完成示例審核。',
                                })
                    if ticket['status'] != status:
                        raise RuntimeError(f'{case}: expected {status}, got {ticket["status"]}')
                    created.append(tid)
                cases.append({'case': case, 'id': ticket['id'], 'expected_status': status})
        final = api(supervisor, 'GET', '/tickets')
        ids = {case['id'] for case in cases}
        demo = [t for t in final if t['id'] in ids]
        current = {t['id']: t for t in final}
        unchanged = all(current[t['id']] == t for t in original)
        if not unchanged:
            raise RuntimeError('An existing work order changed during seeding.')
        return {
            'source': 'synthetic demo, normal authenticated workflow transitions',
            'created': len(created), 'skipped': len(skipped), 'demo_total': len(demo),
            'status_counts': dict(Counter(t['status'] for t in demo)),
            'engineer_counts': dict(Counter(t['engineer'] for t in demo)),
            'machine_count': len({t['machine'] for t in demo}),
            'machine_kinds': dict(Counter(machines[t['machine']]['kind'] for t in demo)),
            'existing_orders_preserved': unchanged,
            'cases': [{**case, 'status': current[case['id']]['status'],
                       'machine': current[case['id']]['machine'],
                       'engineer': current[case['id']]['engineer']} for case in cases],
        }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8094')
    parser.add_argument('--report', type=Path, default=Path('.runtime/demo-work-orders-report.json'))
    args = parser.parse_args()
    report = seed(args.base_url)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}, ensure_ascii=False))
