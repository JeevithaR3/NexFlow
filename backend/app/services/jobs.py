"""Background job manager: long SUMO work runs in a thread pool; status is persisted in SQLite."""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select

from app.core.errors import NexFlowError, SimulationCancelled
from app.core.logging import get_logger
from app.models.db import Database, RunRow

log = get_logger("jobs")


class JobContext:
    def __init__(self, mgr: "JobManager", run_id: str, stop: threading.Event) -> None:
        self._mgr, self.run_id, self.stop_event = mgr, run_id, stop

    def progress(self, frac: float, message: str = "") -> None:
        self._mgr._update(self.run_id, progress=float(max(0.0, min(1.0, frac))), message=message[:190])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def row_dict(r: RunRow) -> dict:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {
        "id": r.id, "kind": r.kind, "status": r.status, "progress": r.progress, "message": r.message,
        "params": r.params, "result": r.result, "error": r.error, "created_at": iso(r.created_at),
        "started_at": iso(r.started_at), "finished_at": iso(r.finished_at),
    }


class JobManager:
    def __init__(self, db: Database, workers: int = 3) -> None:
        self.db = db
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self._stops: dict[str, threading.Event] = {}
        with db.session() as s:  # jobs interrupted by a restart can never finish
            for r in s.scalars(select(RunRow).where(RunRow.status.in_(["queued", "running"]))):
                r.status, r.error = "failed", {"code": "interrupted", "message": "Server restarted while the run was active."}

    def _update(self, run_id: str, **vals) -> None:
        with self.db.session() as s:
            r = s.get(RunRow, run_id)
            if r:
                for k, v in vals.items():
                    setattr(r, k, v)

    def submit(self, kind: str, params: dict, fn: Callable[[JobContext], dict]) -> str:
        run_id = uuid.uuid4().hex[:12]
        stop = threading.Event()
        self._stops[run_id] = stop
        with self.db.session() as s:
            s.add(RunRow(id=run_id, kind=kind, status="queued", params=params, progress=0.0, message="queued"))

        def work() -> None:
            self._update(run_id, status="running", started_at=_now(), message="running")
            try:
                result = fn(JobContext(self, run_id, stop))
                self._update(run_id, status="succeeded", result=result, progress=1.0, message="done", finished_at=_now())
            except SimulationCancelled:
                self._update(run_id, status="cancelled", message="cancelled", finished_at=_now())
            except NexFlowError as e:
                self._update(run_id, status="failed", finished_at=_now(), message="failed",
                             error={"code": e.code, "message": e.message, "hint": e.hint})
            except Exception:  # never leak internals to the client
                log.error("job crashed", extra={"run_id": run_id}, exc_info=True)
                self._update(run_id, status="failed", finished_at=_now(), message="failed",
                             error={"code": "internal_error", "message": "The run failed unexpectedly.", "hint": "See the server log."})
            finally:
                self._stops.pop(run_id, None)

        self.pool.submit(work)
        return run_id

    def get(self, run_id: str) -> dict | None:
        with self.db.session() as s:
            r = s.get(RunRow, run_id)
            return row_dict(r) if r else None

    def list(self, limit: int = 20, kind: str | None = None) -> list[dict]:
        with self.db.session() as s:
            q = select(RunRow).order_by(RunRow.created_at.desc()).limit(limit)
            if kind:
                q = q.where(RunRow.kind == kind)
            return [{**row_dict(r), "result": None} for r in s.scalars(q)]

    def cancel(self, run_id: str) -> bool:
        ev = self._stops.get(run_id)
        if ev:
            ev.set()
            return True
        return False
