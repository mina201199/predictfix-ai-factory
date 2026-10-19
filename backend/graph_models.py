"""圖譜獨立資料表；在 store.init 前匯入以共用既有資料庫。"""
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from . import store


class GraphNode(store.Base):
  __tablename__ = 'graph_nodes'
  id: Mapped[str] = mapped_column(String(80), primary_key=True)
  kind: Mapped[str] = mapped_column(String(30))
  label: Mapped[str] = mapped_column(String(500))
  machineModel: Mapped[str] = mapped_column(String(100), index=True)


class GraphRelation(store.Base):
  __tablename__ = 'graph_relations'
  id: Mapped[str] = mapped_column(String(80), primary_key=True)
  headId: Mapped[str] = mapped_column(ForeignKey('graph_nodes.id'), index=True)
  tailId: Mapped[str] = mapped_column(ForeignKey('graph_nodes.id'))
  kind: Mapped[str] = mapped_column(String(30))
  machineModel: Mapped[str] = mapped_column(String(100), index=True)
  status: Mapped[str] = mapped_column(String(20), default='candidate', index=True)
  revision: Mapped[int] = mapped_column(Integer, default=1)
  payload: Mapped[str] = mapped_column(Text)
  createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True),
    default=lambda: datetime.now(timezone.utc))
