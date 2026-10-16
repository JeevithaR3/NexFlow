"""Dataset pipeline: SUMO-generated synthetic observations, validation, imputation,
chronological splitting, windowing and leakage-free scaling.

Layout: ``obs`` has shape [R, T, N, F] - R independent simulation runs ("episodes"), T aggregation
intervals, N road segments, F features (see :data:`app.sumo.collector.FEATURES`).  Runs are ordered
in time (run 0 is the earliest) and are split *chronologically* into train / validation / test;
windows never cross run boundaries and the scaler is fitted on the training runs only.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from app.core.errors import DataValidationError
from app.core.logging import get_logger
from app.digital_twin.congestion import congestion_index
from app.digital_twin.network import NetworkModel
from app.ml.graph import GraphSpec
from app.sumo.collector import FEATURES, F_SPEED
from app.sumo.scenario import PATTERNS, ScenarioConfig

log = get_logger("ml.dataset")
SCHEMA_VERSION = "obs-v1"
BENCHMARK_SEED_BASE = 50_000  # benchmark scenarios use seeds >= this; the dataset never does


@dataclass
class TrafficDataset:
    obs: np.ndarray  # [R, T, N, F]
    scenarios: list[dict]
    meta: dict = field(default_factory=dict)


# ---- validation / cleaning ---------------------------------------------------------------
def validate_obs(obs: np.ndarray, n_nodes: int) -> None:
    if obs.ndim != 4:
        raise DataValidationError(f"Dataset must be 4-D [runs, intervals, nodes, features]; got {obs.ndim}-D")
    if obs.shape[2] != n_nodes:
        raise DataValidationError(f"Dataset has {obs.shape[2]} nodes but the graph has {n_nodes}")
    if obs.shape[3] != len(FEATURES):
        raise DataValidationError(f"Dataset has {obs.shape[3]} features; expected {len(FEATURES)} {FEATURES}")
    if obs.shape[0] < 3:
        raise DataValidationError("At least 3 runs are required for a chronological train/val/test split")
    finite = obs[np.isfinite(obs)]
    if finite.size and finite.min() < 0:
        raise DataValidationError("Negative traffic measurements found (flow/speed/occupancy/count must be >= 0)")


def impute_missing(obs: np.ndarray, free_flow: np.ndarray) -> np.ndarray:
    """Replace NaNs: forward-fill along time inside each run; leading gaps use free-flow speed
    and zero for the other features.  Returns a new array; never looks at later runs (no leakage)."""
    out = obs.astype(np.float32, copy=True)
    r, t, n, f = out.shape
    default = np.zeros((n, f), dtype=np.float32)
    default[:, F_SPEED] = free_flow
    for k in range(t):
        bad = ~np.isfinite(out[:, k])
        if not bad.any():
            continue
        fill = out[:, k - 1] if k > 0 else np.broadcast_to(default, (r, n, f))
        out[:, k] = np.where(bad, fill, out[:, k])
    return out


def chronological_split(n_runs: int, fractions: tuple[float, float, float] = (0.70, 0.15, 0.15)):
    n_train = max(1, int(round(n_runs * fractions[0])))
    n_val = max(1, int(round(n_runs * fractions[1])))
    if n_train + n_val >= n_runs:
        n_train, n_val = max(1, n_runs - 2), 1
    return slice(0, n_train), slice(n_train, n_train + n_val), slice(n_train + n_val, n_runs)


# ---- scaling (fit on training data only) -----------------------------------------------------
@dataclass
class FeatureScaler:
    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def fit(cls, train_obs: np.ndarray) -> "FeatureScaler":
        flat = train_obs.reshape(-1, train_obs.shape[-1])
        std = flat.std(0)
        return cls(flat.mean(0).astype(np.float32), np.where(std < 1e-6, 1.0, std).astype(np.float32))

    def transform(self, x: np.ndarray) -> np.ndarray:
        return ((x - self.mean) / self.std).astype(np.float32)

    def to_dict(self) -> dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist()}

    @classmethod
    def from_dict(cls, d: dict) -> "FeatureScaler":
        return cls(np.array(d["mean"], dtype=np.float32), np.array(d["std"], dtype=np.float32))


def static_features(graph: GraphSpec) -> np.ndarray:
    """[N, 2] standardised segment length and free-flow speed (a property of the network, not data)."""
    cols = []
    for v in (graph.length_m, graph.free_flow_speed):
        sd = float(v.std())
        cols.append((v - v.mean()) / (sd if sd > 1e-6 else 1.0))
    return np.stack(cols, axis=1).astype(np.float32)


# ---- windows -------------------------------------------------------------------------------
@dataclass
class Windows:
    x: np.ndarray  # [S, W, N, F] raw (unscaled)
    ci_last: np.ndarray  # [S, N]
    y: np.ndarray  # [S, N]  CI at the horizon
    run: np.ndarray  # [S]


def make_windows(obs: np.ndarray, graph: GraphSpec, window: int, horizon: int) -> Windows:
    r, t, n, f = obs.shape
    if t < window + horizon:
        raise DataValidationError(f"Runs have {t} intervals; need at least window+horizon = {window + horizon}")
    ci = congestion_index(obs[..., F_SPEED], graph.free_flow_speed[None, None, :])  # [R,T,N]
    xs, last, ys, rr = [], [], [], []
    for i in range(r):
        for s in range(0, t - window - horizon + 1):
            end = s + window - 1
            xs.append(obs[i, s : s + window])
            last.append(ci[i, end])
            ys.append(ci[i, end + horizon])
            rr.append(i)
    return Windows(
        np.stack(xs).astype(np.float32), np.stack(last).astype(np.float32), np.stack(ys).astype(np.float32), np.array(rr)
    )


# ---- persistence -----------------------------------------------------------------------------
def save_dataset(ds: TrafficDataset, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "traffic_dataset.npz"
    np.savez_compressed(path, obs=ds.obs, scenarios=json.dumps(ds.scenarios), meta=json.dumps(ds.meta))
    return path


def load_dataset(directory: Path) -> TrafficDataset:
    path = directory / "traffic_dataset.npz"
    if not path.exists():
        raise DataValidationError(
            f"No dataset found at {path}", hint="Run `python scripts/generate_dataset.py` (needs SUMO)."
        )
    with np.load(path, allow_pickle=False) as z:
        return TrafficDataset(z["obs"], json.loads(str(z["scenarios"])), json.loads(str(z["meta"])))


# ---- synthetic generation (needs SUMO) -----------------------------------------------------------
def sample_scenarios(n_runs: int, base_seed: int, duration_s: int) -> list[ScenarioConfig]:
    rng = np.random.default_rng(base_seed)
    out = []
    for i in range(n_runs):
        out.append(
            ScenarioConfig(
                pattern=str(rng.choice(PATTERNS)),
                demand_scale=round(float(rng.uniform(0.6, 1.5)), 2),
                seed=base_seed + i,
                duration_s=duration_s,
            )
        )
    return out


def generate_synthetic_dataset(
    net: NetworkModel,
    runner,
    n_runs: int,
    *,
    base_seed: int = 1000,
    duration_s: int = 1200,
    interval_s: int = 60,
    workers: int = 2,
    progress: Callable[[int, int], None] | None = None,
) -> TrafficDataset:
    """Run ``n_runs`` baseline SUMO simulations (default signal plans) and record observations."""
    if base_seed + n_runs >= BENCHMARK_SEED_BASE:
        raise DataValidationError("base_seed range collides with the reserved benchmark seed range")
    scenarios = sample_scenarios(n_runs, base_seed, duration_s)
    results: list = [None] * n_runs
    done = 0

    def work(i: int):
        return i, runner.run(scenarios[i], None, collect_observations=True, interval_s=interval_s)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in ex.map(work, range(n_runs)):
            results[i] = res
            done += 1
            if progress:
                progress(done, n_runs)
    obs = np.stack([r.observations for r in results])
    from app.sumo.environment import check_sumo

    meta = {
        "synthetic": True,
        "description": "Synthetic observations produced by SUMO on the NexFlow demonstration network. "
        "Not real-world traffic data.",
        "schema_version": SCHEMA_VERSION,
        "features": list(FEATURES),
        "interval_s": interval_s,
        "duration_s": duration_s,
        "net_hash": net.net_hash,
        "tls_hash": net.tls_hash,
        "edge_ids": net.edge_ids,
        "base_seed": base_seed,
        "n_runs": n_runs,
        "sumo_version": check_sumo().version,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return TrafficDataset(obs, [s.to_dict() for s in scenarios], meta)
