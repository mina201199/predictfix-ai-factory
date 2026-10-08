"""Human-approved, source-backed procedures, calendar maintenance and stock ledger."""
import copy
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from . import auth, config, maintenance_ai as ai, store

TAIPEI = timezone(timedelta(hours=8))


def today():
    return datetime.now(TAIPEI).date()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return prefix + uuid.uuid4().hex


def locked(db, model, key):
    if store.engine.dialect.name == 'sqlite':
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
    row = db.scalar(select(model).where(model.id == key).with_for_update())
    if row is None:
        raise HTTPException(404, '資料不存在')
    return row


def workflow(db, ticket):
    row = db.get(store.Workflow, ticket.id)
    if row is None:
        row = store.Workflow(id=ticket.id, payload='{}')
        db.add(row)
    return row, json.loads(row.payload)


def editable(ticket):
    if ticket.status in ['已完成', '待主管審核']:
        raise HTTPException(409, '已完成或待審核工單不可修改')


def validate_checklist(data):
    procedure = data.get('procedure')
    if not procedure:
        return  # Existing work orders retain their original submission rules.
    missing = []
    for step in procedure['steps']:
        result = step.get('result', {})
        outcome = result.get('outcome')
        if (outcome not in ['pass', 'na'] or len(result.get('note', '').strip()) < 3
                or (step['kind'] == 'verify' and outcome != 'pass')):
            missing.append(step['label'])
    if missing:
        raise HTTPException(422, '尚有未通過的排查／驗收項目：' + '、'.join(missing))


def checklist_submission(db, ticket):
    _, data = workflow(db, ticket)
    validate_checklist(data)
    return copy.deepcopy(data.get('procedure'))


def on_review(db, ticket, data, decision):
    if decision == 'approve':
        validate_checklist(data)
        plan_id = data.get('maintenance_plan_id')
        if plan_id:
            plan = db.scalar(select(store.MaintenancePlan).where(store.MaintenancePlan.id == plan_id).with_for_update())
            if plan:
                p = json.loads(plan.payload)
                if p.get('open_ticket') == ticket.id:
                    p['history'].append({'ticket_id': ticket.id, 'completed_at': stamp(), 'due': p['next_due']})
                    p.update(open_ticket=None, next_due=(today() + timedelta(days=p['interval_days'])).isoformat())
                    plan.payload = json.dumps(p, ensure_ascii=False)
    elif data.get('procedure'):
        # Previous results remain in submission snapshots; rework requires fresh confirmation.
        for step in data['procedure']['steps']:
            step.pop('result', None)
        data['procedure']['revision'] += 1


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Report(Input):
    machine: str
    symptoms: str = Field(min_length=3, max_length=160)
    machine_model: str = Field(default='', max_length=100)
    component: str = Field(default='', max_length=100)
    conditions: str = Field(default='', max_length=500)
    alarm: str = Field(default='', max_length=200)
    recent_change: str = Field(default='', max_length=500)
    scope: str = Field(default='', max_length=300)
    previous_checks: str = Field(default='', max_length=1000)
    use_llm: bool = True

    @field_validator('symptoms')
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 3:
            raise ValueError('請填寫異常描述')
        return value.strip()


def machine(db, mid):
    row = db.get(store.Machine, mid)
    if not row or not row.active:
        raise HTTPException(422, '設備不存在或已停用')
    return json.loads(row.payload)


class Step(Input):
    label: str = Field(min_length=3, max_length=200)
    kind: Literal['inspect', 'verify']
    criterion: str = Field(min_length=3, max_length=500)
    source_chunk_id: str = Field(default='', max_length=200)
    source_hash: str = Field(default='', max_length=64)

    @field_validator('label', 'criterion')
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 3:
            raise ValueError('請填完整項目與判定依據')
        return value.strip()


class Procedure(Input):
    revision: int = Field(ge=0)
    machine_model: str = Field(min_length=2, max_length=100)
    approval_note: str = Field(min_length=3, max_length=500)
    steps: list[Step] = Field(min_length=2, max_length=16)


def approved_steps(body, model):
    if len(body.approval_note.strip()) < 3 or not model.strip():
        raise HTTPException(422, '請確認機型與核准依據')
    if body.machine_model != model:
        raise HTTPException(422, '清單機型與設備機型不一致')
    if not any(s.kind == 'inspect' for s in body.steps) or not any(s.kind == 'verify' for s in body.steps):
        raise HTTPException(422, '至少需要一項排查和一項驗收')
    sources = {s['chunk_id']: s for s in ai.corpus()}
    result = []
    for step in body.steps:
        source = None
        if step.source_chunk_id:
            source = sources.get(step.source_chunk_id)
            if not source or model not in source.get('machine_models', []):
                raise HTTPException(422, '來源已撤回或不適用此機型，請重新查找')
            if ai.digest(source) != step.source_hash:
                raise HTTPException(409, '來源已更新，請重新查找並核准')
        result.append({'id': uid('STEP-'), **step.model_dump(),
                       'source': copy.deepcopy(source),
                       'origin': 'source_backed_human_approved' if source else 'supervisor_authored'})
    return result


class Results(Input):
    revision: int = Field(ge=1)
    results: list['Result'] = Field(min_length=1, max_length=16)


class Result(Input):
    step_id: str
    outcome: Literal['pass', 'fail', 'na']
    note: str = Field(min_length=3, max_length=1000)

    @field_validator('note')
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 3:
            raise ValueError('請記錄量測／檢查結果，略過時需填原因')
        return value.strip()


class PlanInput(Procedure):
    machine: str
    title: str = Field(min_length=3, max_length=120)
    interval_days: int = Field(ge=1, le=3650)
    next_due: date

    @field_validator('title')
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 3:
            raise ValueError('請填寫保養名稱')
        return value.strip()


def plan_dict(row):
    p = json.loads(row.payload)
    delta = (date.fromisoformat(p['next_due']) - today()).days
    return {'id': row.id, **p, 'days_until_due': delta,
            'reminder': 'in_progress' if p.get('open_ticket') else 'overdue' if delta < 0 else 'due' if delta == 0 else 'soon' if delta <= 7 else 'scheduled'}


class PlanActive(Input):
    active: bool


class ItemInput(Input):
    name: str = Field(min_length=2, max_length=100)
    unit: str = Field(min_length=1, max_length=20)
    minimum: int = Field(ge=0, le=1000000)

    @field_validator('name', 'unit')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('不可空白')
        return value.strip()


class Movement(Input):
    kind: Literal['receive', 'issue', 'return']
    quantity: int = Field(ge=1, le=1000000)
    ticket_id: str | None = None
    note: str = Field(min_length=3, max_length=500)

    @field_validator('note')
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 3:
            raise ValueError('請填領用／退料／入庫依據')
        return value.strip()


def register(app):
    @app.post('/api/repair-flow/analyze')
    async def analyze(body: Report, request: Request):
        with store.Session() as db:
            m = machine(db, body.machine)
        model = m.get('machine_model') or body.machine_model.strip()
        context = body.model_dump(exclude={'use_llm'})
        context['machine_model'] = model
        follow_up = [{'field': key, 'question': question} for key, question in [
            ('machine_model', '確認設備機型與適用手冊'), ('component', '異常發生在哪個零件／系統？'),
            ('conditions', '發生在何種轉速、負載或加工條件？'), ('alarm', '警報全文是什麼？無警報也請註明。'),
            ('recent_change', '近期更換過什麼？無變更也請註明。'), ('scope', '只發生在特定刀位／工件，還是所有情境？'),
            ('previous_checks', '已檢查什麼、結果如何？尚未檢查也請註明。')]
            if not context[key].strip()]
        answer = await ai.assist(ai.AssistInput(question=body.symptoms + '\n' + '\n'.join(
            str(context[k]) for k in ['conditions', 'alarm', 'recent_change', 'scope', 'previous_checks']),
            machine_model=model, component=body.component, allow_synthetic=config.demo(), use_llm=body.use_llm))
        candidates = []
        for c in answer['citations']:
            candidates.append({**c, 'source_hash': ai.digest({k: v for k, v in c.items() if k not in
                ['rank', 'score', 'tfidf_score', 'bm25_score', 'applicability', 'reference']}),
                'label': c['title'] + ' · ' + c.get('section', ''),
                'qualification': '待主管確認', 'estimate_minutes': None,
                'tools_and_parts': '依來源核對；未自動推定備品與工時'})
        # Hash the canonical corpus record so attachment can reject stale/retracted sources.
        canonical = {c['chunk_id']: c for c in ai.corpus()}
        for c in candidates:
            if c['chunk_id'] in canonical:
                c['source_hash'] = ai.digest(canonical[c['chunk_id']])
        return {'context': context, 'follow_up': follow_up, 'candidates': candidates,
                'assistant': answer, 'method': 'structured_follow_up_and_grounded_source_comparison',
                'ready_for_approval': not follow_up and bool(candidates)}

    @app.post('/api/repair-flow/report', status_code=201)
    def report(body: Report, request: Request, idempotency_key: str = Header(min_length=8, max_length=100)):
        with store.Session() as db:
            if store.engine.dialect.name == 'sqlite':
                db.connection().exec_driver_sql('BEGIN IMMEDIATE')
            m = machine(db, body.machine)
            context = body.model_dump(exclude={'use_llm'})
            context['machine_model'] = m.get('machine_model') or body.machine_model.strip()
            old = db.scalar(select(store.Ticket).where(store.Ticket.request_key == idempotency_key))
            if old:
                _, data = workflow(db, old)
                if data.get('report_context') != context:
                    raise HTTPException(409, '相同請求編號的報修內容不同')
                return store.ticket_dict(old)
            ticket = store.Ticket(id=uid('WO-'), machine=body.machine, issue=body.symptoms.strip(), engineer='待指派', status='待指派', request_key=idempotency_key)
            db.add(ticket)
            db.add(store.Workflow(id=ticket.id, payload=json.dumps({'report_context': context}, ensure_ascii=False)))
            ai.record(db, 'flow_report', request.state.user, {'ticket_id': ticket.id})
            db.commit()
            return store.ticket_dict(ticket)

    @app.put('/api/tickets/{tid}/report-context')
    def update_context(tid: str, body: Report, request: Request):
        with store.Session() as db:
            ticket = locked(db, store.Ticket, tid)
            if request.state.user['role'] != 'supervisor':
                auth.assigned(request, ticket)
            editable(ticket)
            if body.machine != ticket.machine:
                raise HTTPException(422, '補問資訊不可更換工單設備')
            m = machine(db, ticket.machine)
            meta, data = workflow(db, ticket)
            context = body.model_dump(exclude={'use_llm'})
            context['machine_model'] = m.get('machine_model') or body.machine_model.strip()
            if data.get('procedure') and context['machine_model'] != data['procedure']['machine_model']:
                raise HTTPException(409, '已核准清單機型不可透過補問修改')
            data.setdefault('report_history', []).append({'context': data.get('report_context'), 'actor': request.state.user['username'], 'at': stamp()})
            data['report_context'] = context
            ticket.issue = body.symptoms
            meta.payload = json.dumps(data, ensure_ascii=False)
            ai.record(db, 'report_context_updated', request.state.user, {'ticket_id': tid})
            db.commit()
            return store.ticket_dict(ticket)

    @app.put('/api/tickets/{tid}/procedure')
    def attach(tid: str, body: Procedure, request: Request):
        auth.supervisor(request)
        with store.Session() as db:
            ticket = locked(db, store.Ticket, tid)
            editable(ticket)
            meta, data = workflow(db, ticket)
            revision = data.get('procedure', {}).get('revision', 0)
            if revision != body.revision:
                raise HTTPException(409, '清單已更新，請重新載入')
            m = machine(db, ticket.machine)
            model = m.get('machine_model') or data.get('report_context', {}).get('machine_model', '')
            steps = approved_steps(body, model)
            if data.get('procedure'):
                data.setdefault('procedure_history', []).append(copy.deepcopy(data['procedure']))
            data['procedure'] = {'revision': revision + 1, 'machine_model': model,
                'approved_by': request.state.user['username'], 'approved_at': stamp(),
                'approval_note': body.approval_note.strip(), 'steps': steps}
            meta.payload = json.dumps(data, ensure_ascii=False)
            ai.record(db, 'procedure_approved', request.state.user, {'ticket_id': tid, 'revision': revision + 1})
            db.commit()
            return store.ticket_dict(ticket)

    @app.put('/api/tickets/{tid}/procedure/results')
    def results(tid: str, body: Results, request: Request):
        with store.Session() as db:
            ticket = locked(db, store.Ticket, tid)
            auth.assigned(request, ticket)
            editable(ticket)
            meta, data = workflow(db, ticket)
            procedure = data.get('procedure')
            if not procedure or procedure['revision'] != body.revision:
                raise HTTPException(409, '清單已更新，請重新載入')
            steps = {s['id']: s for s in procedure['steps']}
            if len({r.step_id for r in body.results}) != len(body.results) or any(r.step_id not in steps for r in body.results):
                raise HTTPException(422, '清單項目不存在或重複')
            for result in body.results:
                step = steps[result.step_id]
                if step['kind'] == 'verify' and result.outcome == 'na':
                    raise HTTPException(422, '驗收項目不可略過')
                step['result'] = {**result.model_dump(exclude={'step_id'}), 'recorded_by': request.state.user['username'], 'at': stamp()}
            procedure['revision'] += 1
            meta.payload = json.dumps(data, ensure_ascii=False)
            ai.record(db, 'procedure_results', request.state.user, {'ticket_id': tid, 'revision': procedure['revision']})
            db.commit()
            return store.ticket_dict(ticket)

    @app.get('/api/maintenance-plans')
    def plans():
        with store.Session() as db:
            return sorted([plan_dict(p) for p in db.scalars(select(store.MaintenancePlan)).all()], key=lambda p: p['next_due'])

    @app.post('/api/maintenance-plans', status_code=201)
    def create_plan(body: PlanInput, request: Request):
        auth.supervisor(request)
        with store.Session() as db:
            m = machine(db, body.machine)
            model = m.get('machine_model') or body.machine_model.strip()
            steps = approved_steps(body, model)
            p = {**body.model_dump(mode='json', exclude={'steps', 'revision'}), 'steps': steps,
                 'active': True, 'open_ticket': None, 'history': [], 'created_by': request.state.user['username']}
            row = store.MaintenancePlan(id=uid('PM-'), payload=json.dumps(p, ensure_ascii=False))
            db.add(row)
            ai.record(db, 'maintenance_plan_created', request.state.user, {'id': row.id})
            db.commit()
            return plan_dict(row)

    @app.put('/api/maintenance-plans/{pid}/active')
    def active(pid: str, body: PlanActive, request: Request):
        auth.supervisor(request)
        with store.Session() as db:
            row = locked(db, store.MaintenancePlan, pid)
            p = json.loads(row.payload)
            p['active'] = body.active
            row.payload = json.dumps(p, ensure_ascii=False)
            ai.record(db, 'maintenance_plan_active', request.state.user, {'id': pid, 'active': body.active})
            db.commit()
            return plan_dict(row)

    @app.post('/api/maintenance-plans/{pid}/generate')
    def generate(pid: str, request: Request):
        auth.supervisor(request)
        with store.Session() as db:
            row = locked(db, store.MaintenancePlan, pid)
            p = json.loads(row.payload)
            if not p['active']:
                raise HTTPException(409, '保養計畫已停用')
            if p.get('open_ticket'):
                return store.ticket_dict(db.get(store.Ticket, p['open_ticket']))
            if date.fromisoformat(p['next_due']) > today():
                raise HTTPException(409, '尚未到期，不建立重複或提前保養工單')
            m = machine(db, p['machine'])
            model = m.get('machine_model') or p['machine_model']
            # Re-check active sources when starting a new cycle.
            steps = approved_steps(Procedure(revision=0, machine_model=p['machine_model'], approval_note=p['approval_note'],
                steps=[Step(**{k: s[k] for k in ['label', 'kind', 'criterion', 'source_chunk_id', 'source_hash']}) for s in p['steps']]), model)
            ticket = store.Ticket(id=uid('WO-'), machine=p['machine'], issue=p['title'], engineer='待指派', status='待指派', request_key='pm:' + pid + ':' + p['next_due'])
            db.add(ticket)
            procedure = {'revision': 1, 'machine_model': p['machine_model'], 'approved_by': request.state.user['username'],
                         'approved_at': stamp(), 'approval_note': p['approval_note'], 'steps': steps}
            db.add(store.Workflow(id=ticket.id, payload=json.dumps({'maintenance_plan_id': pid, 'procedure': procedure}, ensure_ascii=False)))
            p['open_ticket'] = ticket.id
            row.payload = json.dumps(p, ensure_ascii=False)
            ai.record(db, 'maintenance_ticket_created', request.state.user, {'plan_id': pid, 'ticket_id': ticket.id})
            db.commit()
            return store.ticket_dict(ticket)

    @app.get('/api/stock')
    def stock():
        with store.Session() as db:
            return [{'id': i.id, 'name': i.name, 'unit': i.unit, 'quantity': i.quantity, 'minimum': i.minimum,
                     'low_stock': i.quantity < i.minimum} for i in db.scalars(select(store.StockItem)).all()]

    @app.post('/api/stock', status_code=201)
    def create_item(body: ItemInput, request: Request):
        auth.supervisor(request)
        with store.Session() as db:
            row = store.StockItem(id=uid('PART-'), **body.model_dump())
            db.add(row)
            ai.record(db, 'stock_item_created', request.state.user, {'id': row.id, 'name': row.name})
            db.commit()
            return {'id': row.id}

    @app.get('/api/stock/movements')
    def movements(ticket_id: str | None = None):
        with store.Session() as db:
            query = select(store.StockMovement)
            if ticket_id:
                query = query.where(store.StockMovement.ticket_id == ticket_id)
            return [{'id': r.id, 'item_id': r.item_id, 'ticket_id': r.ticket_id, **json.loads(r.payload)} for r in db.scalars(query).all()]

    @app.post('/api/stock/{iid}/movements')
    def movement(iid: str, body: Movement, request: Request, idempotency_key: str = Header(min_length=8, max_length=100)):
        with store.Session() as db:
            item = locked(db, store.StockItem, iid)
            if body.kind == 'receive':
                auth.supervisor(request)
                if body.ticket_id:
                    raise HTTPException(422, '入庫不綁定維修工單')
            else:
                ticket = db.scalar(select(store.Ticket).where(store.Ticket.id == body.ticket_id).with_for_update())
                if not ticket:
                    raise HTTPException(422, '領用／退料需要有效工單')
                if request.state.user['role'] != 'supervisor':
                    auth.assigned(request, ticket)
            existing = db.scalar(select(store.StockMovement).where(store.StockMovement.request_key == idempotency_key))
            if existing:
                old = json.loads(existing.payload)
                if existing.item_id != iid or old['input'] != body.model_dump() or old['actor'] != request.state.user['username']:
                    raise HTTPException(409, '相同請求編號的庫存異動內容不同')
                return {'id': existing.id, **old}
            if body.kind == 'issue':
                editable(ticket)
            if body.kind == 'issue' and item.quantity < body.quantity:
                raise HTTPException(409, '庫存不足，無法領用')
            if body.kind == 'return':
                rows = db.scalars(select(store.StockMovement).where(store.StockMovement.item_id == iid, store.StockMovement.ticket_id == body.ticket_id)).all()
                net = sum((1 if d['kind'] == 'issue' else -1) * d['quantity'] for d in (json.loads(r.payload) for r in rows))
                if body.quantity > net:
                    raise HTTPException(422, '退料不可超過此工單尚未退回的領用量')
            item.quantity += (-1 if body.kind == 'issue' else 1) * body.quantity
            payload = {**body.model_dump(), 'input': body.model_dump(), 'actor': request.state.user['username'], 'at': stamp(), 'balance': item.quantity}
            row = store.StockMovement(id=uid('MOVE-'), item_id=iid, ticket_id=body.ticket_id, request_key=idempotency_key, payload=json.dumps(payload, ensure_ascii=False))
            db.add(row)
            ai.record(db, 'stock_movement', request.state.user, {'id': row.id, 'item_id': iid, **payload})
            db.commit()
            return {'id': row.id, **payload}
