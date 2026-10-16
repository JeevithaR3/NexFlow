"""Feature schema ``fv1`` for traffic-state vectors stored in / searched against the memory.

All components are dimensionless and lie in [0, 1], so a plain L2 distance is meaningful and no
learned scaler can drift:

  index 0  mean predicted CI over all road segments
  index 1  max predicted CI
  index 2  fraction of segments predicted *high* (CI >= 0.6)
  index 3  fraction of segments predicted *moderate or high* (CI >= 0.3)
  index 4  mean current CI
  index 5  mean current halted vehicles per segment / storage capacity (clipped to 1)
  then, for every signalised junction j (sorted ids), three values over its incoming segments:
           mean predicted CI, mean current CI, mean halted vehicles / capacity (clipped to 1)
Dimension = 6 + 3 * (#signalised junctions).
"""
from __future__ import annotations

import numpy as np

from app.digital_twin.congestion import HIGH_MIN, LOW_MAX
from app.digital_twin.network import NetworkModel

FEATURE_SCHEMA_VERSION = "fv1"
VEHICLE_SPACE_M = 7.5  # metres of road per queued vehicle (5 m car + 2.5 m gap)


def feature_dim(net: NetworkModel) -> int:
    return 6 + 3 * len(net.tls_ids)


def feature_names(net: NetworkModel) -> list[str]:
    names = ["pred_ci_mean", "pred_ci_max", "pred_frac_high", "pred_frac_mod_or_high", "cur_ci_mean", "cur_halt_norm_mean"]
    for j in net.tls_ids:
        names += [f"{j}:pred_ci_in", f"{j}:cur_ci_in", f"{j}:cur_halt_norm_in"]
    return names


def build_state_vector(net: NetworkModel, cur_ci: np.ndarray, pred_ci: np.ndarray, halting: np.ndarray) -> np.ndarray:
    n = net.n_edges
    for name, a in (("cur_ci", cur_ci), ("pred_ci", pred_ci), ("halting", halting)):
        if a.shape != (n,):
            raise ValueError(f"{name} must have shape ({n},), got {a.shape}")
    cap = np.array([max(e.length * e.lanes / VEHICLE_SPACE_M, 1.0) for e in net.edges])
    halt = np.clip(halting / cap, 0.0, 1.0)
    vec = [
        pred_ci.mean(), pred_ci.max(), (pred_ci >= HIGH_MIN).mean(), (pred_ci >= LOW_MAX).mean(),
        cur_ci.mean(), halt.mean(),
    ]
    for j in net.tls_ids:
        idx = [net.edge_index[e] for e in net.junction_by_id[j].incoming]
        vec += [pred_ci[idx].mean(), cur_ci[idx].mean(), halt[idx].mean()]
    out = np.clip(np.array(vec, dtype=np.float32), 0.0, 1.0)
    return out
