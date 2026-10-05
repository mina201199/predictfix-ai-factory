import os
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, Integer, DateTime, LargeBinary
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
(ROOT/'data').mkdir(exist_ok=True)
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///'+str(ROOT/'data'/'predictfix.db'))
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

def init():
    Base.metadata.create_all(engine)
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("UPDATE tickets SET status=CASE WHEN engineer='待指派' THEN '待指派' ELSE '已指派' END WHERE status='待處理'"))

def ticket_dict(t):
    import json
    with Session() as s:
        meta=s.get(Workflow,t.id)
        workflow=json.loads(meta.payload) if meta else {}
    return {'id':t.id, 'machine':t.machine, 'issue':t.issue, 'engineer':t.engineer,'workflow':workflow,
            'status':t.status, 'created_at':t.created_at.isoformat(), 'completion_note':t.completion_note}

class User(Base):
    __tablename__='users'
    username: Mapped[str] = mapped_column(String(50),primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
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
