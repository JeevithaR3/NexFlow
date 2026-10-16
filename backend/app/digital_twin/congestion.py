"""Documented congestion definition used everywhere (GNN target, map colours, memory features).

Congestion index  CI = clip(1 - v / v_free, 0, 1)
  v       vehicle-weighted mean speed on the road segment during the aggregation interval (m/s)
  v_free  free-flow speed (speed limit) of the segment (m/s)
  an interval without any vehicle is treated as free flow (CI = 0).

Levels:  low (green) CI < 0.30  |  moderate (yellow) 0.30 <= CI < 0.60  |  high (red) CI >= 0.60
         unknown (gray) when no measurement exists.
CI is dimensionless.  It is a speed-drop indicator, not a measured travel-time delay.
"""
from __future__ import annotations

import numpy as np

LOW_MAX = 0.30
HIGH_MIN = 0.60
LEVELS = ("low", "moderate", "high", "unknown")
COLORS = {"low": "#16a34a", "moderate": "#eab308", "high": "#dc2626", "unknown": "#9ca3af"}


def congestion_index(speed: np.ndarray, free_flow: np.ndarray) -> np.ndarray:
    ratio = np.asarray(speed, dtype=np.float64) / np.maximum(np.asarray(free_flow, dtype=np.float64), 1e-6)
    return np.clip(1.0 - ratio, 0.0, 1.0)


def level_of(ci: float | None) -> str:
    if ci is None or not np.isfinite(ci):
        return "unknown"
    if ci < LOW_MAX:
        return "low"
    if ci < HIGH_MIN:
        return "moderate"
    return "high"


def level_ids(ci: np.ndarray) -> np.ndarray:
    """0 = low, 1 = moderate, 2 = high (vectorised, no NaN handling)."""
    return np.digitize(np.asarray(ci), [LOW_MAX, HIGH_MIN])


def distribution(levels: list[str]) -> dict[str, int]:
    out = {k: 0 for k in LEVELS}
    for lv in levels:
        out[lv] = out.get(lv, 0) + 1
    return out
