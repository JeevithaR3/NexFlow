"""SQLAlchemy models and session handling (SQLite)."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ExperienceRow(Base):
    __tablename__ = "experiences"

    faiss_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # FAISS vector id
    experience_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    network_id: Mapped[str] = mapped_column(String(32), index=True)
    tls_hash: Mapped[str] = mapped_column(String(32))
    scenario_id: Mapped[str] = mapped_column(String(80))
    feature_schema: Mapped[str] = mapped_column(String(16))
    objective_version: Mapped[str] = mapped_column(String(16))
    model_version: Mapped[str] = mapped_column(String(40))
    horizon_s: Mapped[int] = mapped_column(Integer)
    interval_s: Mapped[int] = mapped_column(Integer)
    step_length_s: Mapped[float] = mapped_column(Float)
    sim_duration_s: Mapped[int] = mapped_column(Integer)
    decision_time_s: Mapped[int] = mapped_column(Integer)
    demand_pattern: Mapped[str] = mapped_column(String(24))
    demand_scale: Mapped[float] = mapped_column(Float)
    junction_id: Mapped[str] = mapped_column(String(32), index=True)
    vector: Mapped[list] = mapped_column(JSON)
    intervention: Mapped[dict] = mapped_column(JSON)
    baseline_metrics: Mapped[dict] = mapped_column(JSON)
    result_metrics: Mapped[dict] = mapped_column(JSON)
    improvement: Mapped[float] = mapped_column(Float)
    improved: Mapped[bool] = mapped_column(Boolean, index=True)
    search_runtime_s: Mapped[float] = mapped_column(Float)  # wall time spent obtaining this experience
    runs_used: Mapped[int] = mapped_column(Integer)
    provenance: Mapped[str] = mapped_column(String(40))
    config: Mapped[dict] = mapped_column(JSON)  # limits, objective weights, candidate grid
    reuse_count: Mapped[int] = mapped_column(Integer, default=0)
    verified_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_verification_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)  # queued|running|succeeded|failed|cancelled
    params: Mapped[dict] = mapped_column(JSON)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(String(200), default="")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BenchmarkRow(Base):
    __tablename__ = "benchmarks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    config: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)


def _json_default(o):
    import numpy as np

    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _dumps(o) -> str:
    return json.dumps(o, default=_json_default)


class Database:
    def __init__(self, url: str) -> None:
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, future=True, json_serializer=_dumps, **kwargs)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine, "connect")
            def _pragma(dbapi_conn, _):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.close()

        self._factory = sessionmaker(self.engine, expire_on_commit=False, future=True)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def dispose(self) -> None:
        self.engine.dispose()
