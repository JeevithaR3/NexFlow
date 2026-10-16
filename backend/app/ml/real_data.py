"""Optional adapter for a *real* traffic dataset (not used by the demo).

Expected input (CSV, UTF-8):

``observations.csv``  one row per sensor / road segment and time interval
    timestamp   ISO-8601 or epoch seconds, all sensors share the same regular interval
    sensor_id   string identifying the road segment / detector (node of the graph)
    flow        vehicles per hour            (>= 0)
    speed       mean speed in m/s            (> 0 when vehicles are present; blank = missing)
    occupancy   lane occupancy in percent    (0-100, optional -> 0)
    count       mean vehicle count           (optional -> flow-based estimate not attempted; 0)
    halting     halted vehicles              (optional -> 0)

``sensors.csv``       one row per sensor
    sensor_id, free_flow_speed (m/s), length_m

``links.csv``         directed connectivity
    from_id, to_id

All units must match the synthetic data (m/s, veh/h, %).  The adapter returns a
:class:`TrafficDataset` split into equal-length "runs" (days or blocks) so the same chronological
pipeline can train and evaluate the model.  No real dataset is bundled and none is downloaded.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.core.errors import DataValidationError
from app.ml.dataset import TrafficDataset
from app.ml.graph import GraphSpec
from app.sumo.collector import FEATURES

REQUIRED_OBS = {"timestamp", "sensor_id", "flow", "speed"}


def load_real_dataset(
    observations_csv: Path, sensors_csv: Path, links_csv: Path, intervals_per_run: int
) -> tuple[TrafficDataset, GraphSpec]:
    obs_df = pd.read_csv(observations_csv)
    sensors = pd.read_csv(sensors_csv)
    links = pd.read_csv(links_csv)
    missing = REQUIRED_OBS - set(obs_df.columns)
    if missing:
        raise DataValidationError(f"observations.csv is missing columns: {sorted(missing)}")
    if not {"sensor_id", "free_flow_speed", "length_m"} <= set(sensors.columns):
        raise DataValidationError("sensors.csv needs columns sensor_id, free_flow_speed, length_m")
    if not {"from_id", "to_id"} <= set(links.columns):
        raise DataValidationError("links.csv needs columns from_id, to_id")
    ids = sensors["sensor_id"].astype(str).tolist()
    if len(set(ids)) != len(ids):
        raise DataValidationError("sensors.csv contains duplicate sensor_id values")
    index = {s: i for i, s in enumerate(ids)}
    unknown = set(obs_df["sensor_id"].astype(str)) - set(index)
    if unknown:
        raise DataValidationError(f"observations reference unknown sensors: {sorted(unknown)[:5]}")
    for col in ("from_id", "to_id"):
        if not set(links[col].astype(str)) <= set(index):
            raise DataValidationError("links.csv references unknown sensors")
    if (obs_df["flow"].dropna() < 0).any():
        raise DataValidationError("flow must be non-negative")

    ts = pd.to_datetime(obs_df["timestamp"], errors="coerce", utc=True)
    if ts.isna().any():
        ts = pd.to_datetime(obs_df["timestamp"], unit="s", utc=True)
    obs_df = obs_df.assign(_ts=ts, _node=obs_df["sensor_id"].astype(str).map(index)).sort_values("_ts")
    times = sorted(obs_df["_ts"].unique())
    t_index = {t: i for i, t in enumerate(times)}
    arr = np.full((len(times), len(ids), len(FEATURES)), np.nan, dtype=np.float32)
    colmap = {"flow": 0, "speed": 1, "occupancy": 2, "count": 3, "halting": 4}
    ti = obs_df["_ts"].map(t_index).to_numpy()
    ni = obs_df["_node"].to_numpy()
    for col, k in colmap.items():
        if col in obs_df.columns:
            arr[ti, ni, k] = obs_df[col].to_numpy(dtype=np.float32)
        elif col != "speed" and col != "flow":
            arr[ti, ni, k] = 0.0
    n_runs = len(times) // intervals_per_run
    if n_runs < 3:
        raise DataValidationError("Not enough data for 3 runs of the requested length")
    arr = arr[: n_runs * intervals_per_run].reshape(n_runs, intervals_per_run, len(ids), len(FEATURES))
    pairs = np.array([(index[str(a)], index[str(b)]) for a, b in zip(links["from_id"], links["to_id"])], dtype=np.int64)
    graph = GraphSpec(
        node_ids=ids,
        edge_index=pairs.T if len(pairs) else np.zeros((2, 0), dtype=np.int64),
        free_flow_speed=sensors["free_flow_speed"].to_numpy(dtype=np.float32),
        length_m=sensors["length_m"].to_numpy(dtype=np.float32),
    )
    meta = {"synthetic": False, "source": "real_adapter", "n_runs": n_runs, "features": list(FEATURES)}
    return TrafficDataset(arr, [{"run": i} for i in range(n_runs)], meta), graph
