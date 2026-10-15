import os
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, Integer, DateTime, LargeBinary
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
(ROOT/'data').mkdir(exist_ok=True)
from . import config
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///'+str(ROOT/'data'/('predictfix.db' if config.demo() else 'factory.db')))
engine = create_engine(DATABASE_URL, connect_args={'check_same_thread':False} if DATABASE_URL.startswith('sqlite') else {})
Session = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Ticket(Base):
    __tablename__='tickets'
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    machine: Mapped[str] = mapped_column(String(30))
    issue: Mapped[str] = mapped_column(Text)
    engineer: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default='待處理')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))
    completion_note: Mapped[str] = mapped_column(Text, default='')
    request_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)

class Audit(Base):
    __tablename__='audit'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(30))
    request_id: Mapped[str] = mapped_column(String(60))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))

class Machine(Base):
    __tablename__='machines'
    id: Mapped[str] = mapped_column(String(30),primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    active: Mapped[int] = mapped_column(Integer,default=1)

class Workflow(Base):
    __tablename__='ticket_workflow'
    id: Mapped[str] = mapped_column(String(60),primary_key=True)
    payload: Mapped[str] = mapped_column(Text,default='{}')

class EquipmentTemplate(Base):
    __tablename__='equipment_templates'
    id: Mapped[str] = mapped_column(String(60),primary_key=True)
    revision: Mapped[int] = mapped_column(Integer,default=1)
    payload: Mapped[str] = mapped_column(Text)

def init():
    Base.metadata.create_all(engine)
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("UPDATE tickets SET status=CASE WHEN engineer='待指派' THEN '待指派' ELSE '已指派' END WHERE status='待處理'"))

UNLOADED=object()

def ticket_dict(t,meta=UNLOADED):
    import json
    if meta is UNLOADED:
        # 列表會用 join 一次帶入流程資料；只有單張工單才另外查詢，避免 N+1
        with Session() as s:
            meta=s.get(Workflow,t.id)
    workflow=json.loads(meta.payload) if meta else {}
    return {'id':t.id, 'machine':t.machine, 'issue':t.issue, 'engineer':t.engineer,'workflow':workflow,
            'status':t.status, 'created_at':t.created_at.isoformat(), 'completion_note':t.completion_note}

class User(Base):
    __tablename__='users'
    username: Mapped[str] = mapped_column(String(50),primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[int] = mapped_column(Integer,default=1)
class LoginSession(Base):
    __tablename__='login_sessions'
    token_hash: Mapped[str] = mapped_column(String(64),primary_key=True)
    username: Mapped[str] = mapped_column(String(50))
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class Evidence(Base):
    __tablename__='ticket_evidence'
    id: Mapped[str] = mapped_column(String(60),primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(60),index=True)
    uploader: Mapped[str] = mapped_column(String(50))
    filename: Mapped[str] = mapped_column(String(120))
    media_type: Mapped[str] = mapped_column(String(30))
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

class KnowledgeDocument(Base):
    __tablename__ = 'knowledge_documents'
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    active: Mapped[int] = mapped_column(Integer, default=1)

class RepairCase(Base):
    __tablename__ = 'repair_cases'
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(60), unique=True)
    status: Mapped[str] = mapped_column(String(20), default='draft')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[str] = mapped_column(Text)

class EngineerProfile(Base):
    __tablename__ = 'engineer_profiles'
    username: Mapped[str] = mapped_column(String(50), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)

class Duty(Base):
    __tablename__ = 'engineer_duties'
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    username: Mapped[str] = mapped_column(String(50), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attendance: Mapped[str] = mapped_column(String(20))
    capacity_minutes: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text)

class WorkLog(Base):
    __tablename__ = 'work_logs'
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(60), index=True)
    username: Mapped[str] = mapped_column(String(50))
    minutes: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))

class SchemaVersion(Base):
    __tablename__ = 'schema_versions'
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))

class MaintenancePlan(Base):
    __tablename__ = 'maintenance_plans'
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)

class StockItem(Base):
    __tablename__ = 'stock_items'
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    unit: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    minimum: Mapped[int] = mapped_column(Integer, default=0)

class StockMovement(Base):
    __tablename__ = 'stock_movements'
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(60), index=True)
    ticket_id: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    request_key: Mapped[str] = mapped_column(String(100), unique=True)
    payload: Mapped[str] = mapped_column(Text)
