"""Documented objective used to compare interventions against the baseline of the same scenario.

score = w_wait*(wait/wait0) + w_tt*(tt/tt0) + w_netq*(queue/queue0) + w_locq*(localq/localq0) + w_thr*(thr0/thr)
Every ratio is candidate/baseline (throughput inverted), so the baseline scores exactly 1.0; lower is
better and  improvement = 1 - score  (0.05 = 5 % better).  Small epsilons avoid division by zero.

Hard guard-rails (a candidate violating one is *invalid* regardless of its score):
  * network throughput must not fall by more than ``max_throughput_drop`` (default 5 %)
  * network mean travel time must not rise by more than ``max_travel_time_rise`` (default 10 %)
  * the queue at any *neighbouring* junction may not grow by more than ``max_neighbor_queue_rise`` (25 %)
    unless the absolute increase is below ``neighbor_queue_abs_tolerance`` vehicles.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

OBJECTIVE_VERSION = "obj-v1"


@dataclass(frozen=True)
class ObjectiveConfig:
    w_wait: float = 0.30
    w_travel: float = 0.20
    w_net_queue: float = 0.10
    w_local_queue: float = 0.30
    w_throughput: float = 0.10
    max_throughput_drop: float = 0.05
    max_travel_time_rise: float = 0.10
    max_neighbor_queue_rise: float = 0.25
    neighbor_queue_abs_tolerance: float = 1.5
    min_improvement: float = 0.02  # needed to *recommend* a change

    def to_dict(self) -> dict:
        return {**asdict(self), "version": OBJECTIVE_VERSION}


def _ratio(cand: float, base: float, eps: float) -> float:
    return (cand + eps) / (base + eps)


def evaluate_candidate(
    cfg: ObjectiveConfig,
    base_metrics: dict,
    base_queues: dict[str, float],
    cand_metrics: dict,
    cand_queues: dict[str, float],
    target_junction: str,
    neighbors: list[str],
) -> dict:
    comp = {
        "wait": _ratio(cand_metrics["avg_wait_s"], base_metrics["avg_wait_s"], 1.0),
        "travel_time": _ratio(cand_metrics["avg_travel_time_s"], base_metrics["avg_travel_time_s"], 1.0),
        "network_queue": _ratio(cand_metrics["queue_proxy_veh"], base_metrics["queue_proxy_veh"], 0.5),
        "local_queue": _ratio(cand_queues.get(target_junction, 0.0), base_queues.get(target_junction, 0.0), 0.5),
        "throughput": _ratio(base_metrics["throughput_veh"], cand_metrics["throughput_veh"], 1.0),
    }
    score = (
        cfg.w_wait * comp["wait"] + cfg.w_travel * comp["travel_time"] + cfg.w_net_queue * comp["network_queue"]
        + cfg.w_local_queue * comp["local_queue"] + cfg.w_throughput * comp["throughput"]
    )
    neighbor_effects = {}
    violations: list[str] = []
    for j in neighbors:
        b, c = base_queues.get(j, 0.0), cand_queues.get(j, 0.0)
        neighbor_effects[j] = {"baseline_queue": round(b, 3), "candidate_queue": round(c, 3), "delta": round(c - b, 3)}
        if c - b > cfg.neighbor_queue_abs_tolerance and c > b * (1 + cfg.max_neighbor_queue_rise):
            violations.append(f"queue at neighbouring junction {j} rises {b:.1f} -> {c:.1f} vehicles")
    thr_ratio = cand_metrics["throughput_veh"] / max(base_metrics["throughput_veh"], 1)
    if thr_ratio < 1 - cfg.max_throughput_drop:
        violations.append(f"network throughput drops by {(1 - thr_ratio) * 100:.1f}%")
    tt_ratio = cand_metrics["avg_travel_time_s"] / max(base_metrics["avg_travel_time_s"], 1e-6)
    if base_metrics["avg_travel_time_s"] > 0 and tt_ratio > 1 + cfg.max_travel_time_rise:
        violations.append(f"mean travel time rises by {(tt_ratio - 1) * 100:.1f}%")
    return {
        "score": round(score, 5),
        "improvement": round(1.0 - score, 5),
        "components": {k: round(v, 4) for k, v in comp.items()},
        "valid": not violations,
        "violations": violations,
        "neighbor_effects": neighbor_effects,
    }
