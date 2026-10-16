"""Experience Memory: persistent store (SQLite) + similarity retrieval (FAISS) + safety checks."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import func, select, update

from app.core.logging import get_logger
from app.digital_twin.network import NetworkModel
from app.experience_memory.compat import QueryContext, compatibility_problems
from app.experience_memory.faiss_store import FaissStore
from app.experience_memory.features import FEATURE_SCHEMA_VERSION, feature_dim
from app.interventions.models import SignalLimits
from app.models.db import Database, ExperienceRow

log = get_logger("memory")


def row_to_dict(r: ExperienceRow, include_vector: bool = False) -> dict:
    d = {
        "faiss_id": r.faiss_id, "experience_id": r.experience_id, "network_id": r.network_id, "tls_hash": r.tls_hash,
        "scenario_id": r.scenario_id, "feature_schema": r.feature_schema, "objective_version": r.objective_version,
        "model_version": r.model_version, "horizon_s": r.horizon_s, "interval_s": r.interval_s,
        "step_length_s": r.step_length_s, "sim_duration_s": r.sim_duration_s, "decision_time_s": r.decision_time_s,
        "demand_pattern": r.demand_pattern, "demand_scale": r.demand_scale, "junction_id": r.junction_id,
        "intervention": r.intervention, "baseline_metrics": r.baseline_metrics, "result_metrics": r.result_metrics,
        "improvement": r.improvement, "improved": r.improved, "search_runtime_s": r.search_runtime_s,
        "runs_used": r.runs_used, "provenance": r.provenance, "config": r.config, "reuse_count": r.reuse_count,
        "verified_count": r.verified_count, "failed_verification_count": r.failed_verification_count,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
    if include_vector:
        d["vector"] = r.vector
    return d


@dataclass
class Match:
    experience: dict
    similarity: float
    rms_distance: float
    accepted: bool
    reasons: list[str]

    def to_dict(self) -> dict:
        return {
            "experience_id": self.experience["experience_id"],
            "similarity": round(self.similarity, 4),
            "rms_distance": round(self.rms_distance, 4),
            "accepted": self.accepted,
            "reasons": self.reasons,
            "junction_id": self.experience["junction_id"],
            "intervention": self.experience["intervention"],
            "stored_improvement": round(self.experience["improvement"], 4),
            "scenario_id": self.experience["scenario_id"],
            "demand_scale": self.experience["demand_scale"],
            "demand_pattern": self.experience["demand_pattern"],
        }


class ExperienceMemory:
    def __init__(self, db: Database, directory: Path, net: NetworkModel, limits: SignalLimits | None = None) -> None:
        self.db = db
        self.net = net
        self.limits = limits or SignalLimits()
        self.dim = feature_dim(net)
        self.store = FaissStore(directory, self.dim, FEATURE_SCHEMA_VERSION)
        self._write_lock = threading.RLock()
        self.ensure_consistent()

    # ---- index consistency -------------------------------------------------------------
    def _indexable_rows(self) -> list[tuple[int, list]]:
        with self.db.session() as s:
            rows = s.execute(
                select(ExperienceRow.faiss_id, ExperienceRow.vector).where(
                    ExperienceRow.feature_schema == FEATURE_SCHEMA_VERSION
                )
            ).all()
        return [(r[0], r[1]) for r in rows if len(r[1]) == self.dim]

    def rebuild_index(self) -> int:
        with self._write_lock:
            rows = self._indexable_rows()
            ids = [r[0] for r in rows]
            vecs = np.array([r[1] for r in rows], dtype=np.float32) if rows else np.zeros((0, self.dim), np.float32)
            self.store.rebuild(ids, vecs)
            log.info("faiss index rebuilt", extra={"count": len(ids)})
            return len(ids)

    def ensure_consistent(self) -> bool:
        """Load the persisted index and rebuild it from the database when it is missing or stale."""
        with self._write_lock:
            expected = {r[0] for r in self._indexable_rows()}
            loaded = self.store.load()
            if loaded and self.store.ids() == expected:
                return False
            self.rebuild_index()
            return True

    # ---- writes -----------------------------------------------------------------------
    def add(self, record: dict) -> str:
        """Persist an experience (SQLite first, then the FAISS index)."""
        vec = np.asarray(record["vector"], dtype=np.float32)
        if vec.shape != (self.dim,):
            raise ValueError(f"vector must have dimension {self.dim}; got {vec.shape}")
        if not np.isfinite(vec).all():
            raise ValueError("vector contains non-finite values")
        exp_id = record.get("experience_id") or f"exp-{uuid.uuid4().hex[:12]}"
        cols = {k: v for k, v in record.items() if k not in ("experience_id", "vector", "faiss_id", "created_at")}
        with self._write_lock:
            with self.db.session() as s:
                row = ExperienceRow(experience_id=exp_id, vector=[float(x) for x in vec], **cols)
                s.add(row)
                s.flush()
                fid = row.faiss_id
            try:
                self.store.add(fid, vec)
            except Exception:  # index is derived data; heal from the database
                log.error("faiss add failed; rebuilding", exc_info=True)
                self.rebuild_index()
        return exp_id

    def mark_reuse(self, experience_id: str, verified: bool) -> None:
        col = ExperienceRow.verified_count if verified else ExperienceRow.failed_verification_count
        with self._write_lock, self.db.session() as s:
            s.execute(
                update(ExperienceRow)
                .where(ExperienceRow.experience_id == experience_id)
                .values({ExperienceRow.reuse_count: ExperienceRow.reuse_count + 1, col: col + 1})
            )

    # ---- reads ------------------------------------------------------------------------
    def count(self) -> int:
        with self.db.session() as s:
            return int(s.scalar(select(func.count()).select_from(ExperienceRow)) or 0)

    def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self.db.session() as s:
            rows = s.scalars(select(ExperienceRow).order_by(ExperienceRow.faiss_id.desc()).limit(limit).offset(offset)).all()
            return [row_to_dict(r) for r in rows]

    def get(self, experience_id: str, include_vector: bool = False) -> dict | None:
        with self.db.session() as s:
            r = s.scalar(select(ExperienceRow).where(ExperienceRow.experience_id == experience_id))
            return row_to_dict(r, include_vector) if r else None

    def stats(self) -> dict:
        with self.db.session() as s:
            total = int(s.scalar(select(func.count()).select_from(ExperienceRow)) or 0)
            improved = int(s.scalar(select(func.count()).select_from(ExperienceRow).where(ExperienceRow.improved)) or 0)
            reuse, ok, bad = s.execute(
                select(
                    func.coalesce(func.sum(ExperienceRow.reuse_count), 0),
                    func.coalesce(func.sum(ExperienceRow.verified_count), 0),
                    func.coalesce(func.sum(ExperienceRow.failed_verification_count), 0),
                )
            ).one()
        return {
            "experiences": total, "improved": improved, "indexed_vectors": self.store.ntotal,
            "feature_schema": FEATURE_SCHEMA_VERSION, "vector_dim": self.dim,
            "reuse_attempts": int(reuse), "verified_reuses": int(ok), "failed_verifications": int(bad),
            "index_in_sync": self.store.ntotal == len(self._indexable_rows()),
        }

    def search(
        self, vector: np.ndarray, ctx: QueryContext, *, k: int, threshold: float, demand_tolerance: float
    ) -> list[Match]:
        """Retrieve candidates by FAISS similarity, then apply the similarity threshold and every
        compatibility check.  Returns *all* inspected candidates (accepted or not) with reasons."""
        vec = np.asarray(vector, dtype=np.float32)
        if vec.shape != (self.dim,):
            raise ValueError(f"query vector must have dimension {self.dim}; got {vec.shape}")
        hits = self.store.search(vec, max(k * 5, 25))
        if not hits:
            return []
        with self.db.session() as s:
            rows = {
                r.faiss_id: row_to_dict(r)
                for r in s.scalars(select(ExperienceRow).where(ExperienceRow.faiss_id.in_([h[0] for h in hits])))
            }
        out: list[Match] = []
        for fid, d2 in hits:
            row = rows.get(fid)
            if row is None:
                continue  # index entry without database row: ignore (healed on next consistency check)
            rms = float(np.sqrt(d2 / self.dim))
            sim = max(0.0, 1.0 - rms)
            reasons = compatibility_problems(row, ctx, self.net, self.limits, demand_tolerance)
            if sim < threshold:
                reasons.insert(0, f"similarity {sim:.3f} below threshold {threshold:.3f}")
            out.append(Match(row, sim, rms, accepted=not reasons, reasons=reasons))
        out.sort(key=lambda m: (-m.similarity, m.experience["experience_id"]))
        return out[: max(k, sum(m.accepted for m in out))]
