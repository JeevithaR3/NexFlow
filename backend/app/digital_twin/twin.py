"""Digital Twin: the live virtual state of the road network.

It is *not* SUMO and not a coloured map.  It holds the validated topology (from
:class:`NetworkModel`), the most recent observed traffic measurements, traffic-light
configurations, the GNN forecast, and the selected intervention with its status.  The state
is synchronised from an actual SUMO run (or from a recorded dataset replay, labelled as such)
and every synchronisation validates road / junction / traffic-light IDs against the network.
"""
from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.core.errors import TwinSyncError
from app.digital_twin.congestion import congestion_index, distribution, level_of
from app.digital_twin.network import NetworkModel
from app.sumo.collector import FEATURES, F_COUNT, F_FLOW, F_HALT, F_OCC, F_SPEED

SOURCES = ("sumo_simulation", "dataset_replay")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DigitalTwin:
    def __init__(self, net: NetworkModel, window: int = 6, state_file: Path | None = None) -> None:
        self.net = net
        self.window = window
        self.state_file = state_file
        self._lock = threading.RLock()
        self._buffer: deque[np.ndarray] = deque(maxlen=window)
        self._buffer_times: deque[float] = deque(maxlen=window)
        self.source: str | None = None
        self.scenario: dict | None = None
        self.sim_time_s: float | None = None
        self.updated_at: str | None = None
        self.current: np.ndarray | None = None  # [N, F] latest interval
        self.tls_states: dict[str, str] = {}
        self.tls_programs: dict[str, dict] = {}
        self.prediction: dict | None = None
        self.intervention: dict | None = None
        self.run_id: str | None = None

    # ---- validation ------------------------------------------------------------------
    def validate_ids(self, edge_ids: list[str] | None = None, tls_ids: list[str] | None = None) -> None:
        if edge_ids is not None:
            unknown = sorted(set(edge_ids) - set(self.net.edge_ids))
            if unknown:
                raise TwinSyncError(f"Unknown road IDs for this network: {', '.join(unknown[:5])}")
            if len(edge_ids) != len(self.net.edge_ids):
                raise TwinSyncError("Observation does not cover every road segment of the network")
        if tls_ids is not None:
            unknown = sorted(set(tls_ids) - set(self.net.tls_ids))
            if unknown:
                raise TwinSyncError(f"Unknown traffic-light IDs: {', '.join(unknown[:5])}")

    # ---- synchronisation ---------------------------------------------------------------
    def sync_observations(
        self,
        times: list[float],
        obs: np.ndarray,
        *,
        source: str,
        scenario: dict | None,
        tls_states: dict[str, str] | None = None,
        tls_programs: dict[str, dict] | None = None,
        run_id: str | None = None,
        up_to: int | None = None,
        edge_ids: list[str] | None = None,
    ) -> None:
        """Load observation intervals [T, N, F]; the twin's *current* state is interval ``up_to``
        (default: the last one) and the history buffer holds the last ``window`` intervals up to it."""
        if source not in SOURCES:
            raise TwinSyncError(f"Unknown state source '{source}'")
        self.validate_ids(edge_ids if edge_ids is not None else self.net.edge_ids, list((tls_states or {}).keys()))
        if obs.ndim != 3 or obs.shape[1] != self.net.n_edges or obs.shape[2] != len(FEATURES):
            raise TwinSyncError(
                f"Observation shape {tuple(obs.shape)} does not match the network "
                f"(expected [T, {self.net.n_edges}, {len(FEATURES)}])"
            )
        if len(times) != obs.shape[0] or obs.shape[0] == 0:
            raise TwinSyncError("Observation timestamps and data are inconsistent or empty")
        if not np.isfinite(obs).all():
            raise TwinSyncError("Observation contains non-finite values")
        end = (obs.shape[0] - 1) if up_to is None else up_to
        with self._lock:
            self._buffer.clear()
            self._buffer_times.clear()
            for k in range(max(0, end - self.window + 1), end + 1):
                self._buffer.append(obs[k].astype(np.float32))
                self._buffer_times.append(float(times[k]))
            self.current = obs[end].astype(np.float32)
            self.sim_time_s = float(times[end])
            self.source = source
            self.scenario = scenario
            self.run_id = run_id
            if tls_states is not None:
                self.tls_states = dict(tls_states)
            if tls_programs is not None:
                self.tls_programs = {k: dict(v) for k, v in tls_programs.items()}
            self.prediction = None
            self.intervention = None
            self.updated_at = _now()
            self._persist()

    def latest_window(self) -> np.ndarray | None:
        with self._lock:
            if len(self._buffer) < self.window:
                return None
            return np.stack(self._buffer)

    def set_prediction(self, pred_ci: np.ndarray, *, horizon_s: int, model_version: str, source: str) -> None:
        if pred_ci.shape != (self.net.n_edges,):
            raise TwinSyncError("Prediction vector does not match the number of road segments")
        with self._lock:
            self.prediction = {
                "pred_ci": [float(x) for x in pred_ci],
                "horizon_s": int(horizon_s),
                "made_at_sim_s": self.sim_time_s,
                "target_sim_time_s": (self.sim_time_s or 0.0) + horizon_s,
                "model_version": model_version,
                "source": source,
                "created_at": _now(),
                "verification": None,
            }
            self.updated_at = _now()
            self._persist()

    def set_verification(self, verification: dict) -> None:
        with self._lock:
            if self.prediction is not None:
                self.prediction["verification"] = verification
                self._persist()

    def set_intervention(self, intervention: dict | None, status: str, evidence: dict | None = None) -> None:
        with self._lock:
            self.intervention = (
                None if intervention is None else {"intervention": intervention, "status": status, "evidence": evidence or {}}
            )
            self.updated_at = _now()
            self._persist()

    # ---- derived views ------------------------------------------------------------------
    def current_ci(self) -> np.ndarray | None:
        with self._lock:
            if self.current is None:
                return None
            free = np.array([e.speed for e in self.net.edges])
            return congestion_index(self.current[:, F_SPEED], free)

    def snapshot(self) -> dict:
        with self._lock:
            if self.current is None:
                return {"available": False, "reason": "No traffic state yet. Run a simulation or prediction first."}
            cur_ci = self.current_ci()
            pred = self.prediction["pred_ci"] if self.prediction else None
            edges = []
            for i, e in enumerate(self.net.edges):
                row = self.current[i]
                item = {
                    "id": e.id,
                    "flow_vph": round(float(row[F_FLOW]), 1),
                    "speed_ms": round(float(row[F_SPEED]), 2),
                    "occupancy_pct": round(float(row[F_OCC]), 2),
                    "vehicle_count": round(float(row[F_COUNT]), 2),
                    "halting_count": round(float(row[F_HALT]), 2),
                    "ci": round(float(cur_ci[i]), 4),
                    "level": level_of(float(cur_ci[i])),
                    "pred_ci": None,
                    "pred_level": "unknown",
                    "delta_ci": None,
                }
                if pred is not None:
                    item["pred_ci"] = round(pred[i], 4)
                    item["pred_level"] = level_of(pred[i])
                    item["delta_ci"] = round(pred[i] - float(cur_ci[i]), 4)
                edges.append(item)
            return {
                "available": True,
                "source": self.source,
                "synthetic": True,
                "scenario": self.scenario,
                "run_id": self.run_id,
                "sim_time_s": self.sim_time_s,
                "updated_at": self.updated_at,
                "network": {"net_hash": self.net.net_hash, "tls_hash": self.net.tls_hash},
                "edges": edges,
                "distribution": {
                    "current": distribution([x["level"] for x in edges]),
                    "predicted": distribution([x["pred_level"] for x in edges]) if pred is not None else None,
                },
                "prediction": (
                    {k: v for k, v in self.prediction.items() if k != "pred_ci"} if self.prediction else None
                ),
                "traffic_lights": self._tls_view(),
                "intervention": self.intervention,
            }

    def _tls_view(self) -> dict:
        out = {}
        for j in self.net.tls_ids:
            base = self.net.tls_summary(j)
            prog = self.tls_programs.get(j)
            out[j] = {
                "program_id": prog.get("program_id") if prog else "0",
                "phases": prog["phases"] if prog and prog.get("phases") else base["phases"],
                "cycle_s": prog["cycle_s"] if prog and prog.get("phases") else base["cycle_s"],
                "green_phases": base["green_phases"],
                "state": self.tls_states.get(j),
            }
        return out

    # ---- persistence -----------------------------------------------------------------
    def _persist(self) -> None:
        if not self.state_file or self.current is None:
            return
        payload = {
            "net_hash": self.net.net_hash,
            "source": self.source,
            "scenario": self.scenario,
            "run_id": self.run_id,
            "sim_time_s": self.sim_time_s,
            "updated_at": self.updated_at,
            "current": self.current.tolist(),
            "buffer": [b.tolist() for b in self._buffer],
            "buffer_times": list(self._buffer_times),
            "tls_states": self.tls_states,
            "tls_programs": self.tls_programs,
            "prediction": self.prediction,
            "intervention": self.intervention,
        }
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.state_file)

    def load(self) -> bool:
        """Restore the persisted state if it belongs to the *same* network; otherwise ignore it."""
        if not self.state_file or not self.state_file.exists():
            return False
        try:
            d = json.loads(self.state_file.read_text(encoding="utf-8"))
            if d.get("net_hash") != self.net.net_hash:
                return False
            cur = np.array(d["current"], dtype=np.float32)
            if cur.shape != (self.net.n_edges, len(FEATURES)):
                return False
            with self._lock:
                self.current = cur
                self._buffer.clear()
                self._buffer_times.clear()
                for b, t in zip(d["buffer"], d["buffer_times"]):
                    self._buffer.append(np.array(b, dtype=np.float32))
                    self._buffer_times.append(float(t))
                self.source, self.scenario, self.run_id = d["source"], d["scenario"], d.get("run_id")
                self.sim_time_s, self.updated_at = d["sim_time_s"], d["updated_at"]
                self.tls_states, self.tls_programs = d.get("tls_states", {}), d.get("tls_programs", {})
                self.prediction, self.intervention = d.get("prediction"), d.get("intervention")
            return True
        except (OSError, ValueError, KeyError):
            return False
