"""介接專屬資料表，沿用既有 Base 與資料庫生命週期。"""
from sqlalchemy import Integer, String, Text, UniqueConstraint, Float
from sqlalchemy.orm import Mapped, mapped_column
from .store import Base


class MachineMapping(Base):
  __tablename__ = 'integration_machine_mappings'
  __table_args__ = (UniqueConstraint('source', 'machineCode'),)
  id: Mapped[int] = mapped_column(Integer, primary_key=True)
  source: Mapped[str] = mapped_column(String(60))
  machineCode: Mapped[str] = mapped_column(String(60))
  machineId: Mapped[str] = mapped_column(String(30))


class ExternalOrder(Base):
  __tablename__ = 'integration_orders'
  __table_args__ = (UniqueConstraint('source', 'externalId'),)
  id: Mapped[int] = mapped_column(Integer, primary_key=True)
  source: Mapped[str] = mapped_column(String(60))
  externalId: Mapped[str] = mapped_column(String(60))
  version: Mapped[int] = mapped_column(Integer)
  machineCode: Mapped[str] = mapped_column(String(60))
  ticketId: Mapped[str | None] = mapped_column(String(60), unique=True, nullable=True)
  payload: Mapped[str] = mapped_column(Text)
  reason: Mapped[str] = mapped_column(String(100), default='')


class InboundEvent(Base):
  __tablename__ = 'integration_inbound_events'
  __table_args__ = (UniqueConstraint('source', 'eventId'),)
  id: Mapped[int] = mapped_column(Integer, primary_key=True)
  source: Mapped[str] = mapped_column(String(60))
  eventId: Mapped[str] = mapped_column(String(60))
  payloadHash: Mapped[str] = mapped_column(String(64))
  result: Mapped[str] = mapped_column(Text)
  receivedAt: Mapped[float] = mapped_column(Float)


class Outbox(Base):
  __tablename__ = 'integration_outbox'
  __table_args__ = {'sqlite_autoincrement': True}
  id: Mapped[int] = mapped_column(Integer, primary_key=True)
  eventId: Mapped[str] = mapped_column(String(60), unique=True)
  source: Mapped[str] = mapped_column(String(60))
  ticketId: Mapped[str] = mapped_column(String(60), index=True)
  payload: Mapped[str] = mapped_column(Text)
  state: Mapped[str] = mapped_column(String(20), default='pending')
  attempts: Mapped[int] = mapped_column(Integer, default=0)
  nextAttempt: Mapped[float] = mapped_column(Float, default=0)
  leaseToken: Mapped[str] = mapped_column(String(60), default='')
  leaseUntil: Mapped[float] = mapped_column(Float, default=0)
  lastError: Mapped[str] = mapped_column(String(100), default='')
