"""Compatibility and relevance checks.  A similar vector alone is never enough."""
from __future__ import annotations

from dataclasses import dataclass

from app.interventions.models import Intervention, SignalLimits, validate_intervention
from app.core.errors import DataValidationError
from app.digital_twin.network import NetworkModel


@dataclass(frozen=True)
class QueryContext:
    network_id: str
    tls_hash: str
    feature_schema: str
    objective_version: str
    model_version: str
    horizon_s: int
    interval_s: int
    step_length_s: float
    sim_duration_s: int
    decision_time_s: int
    demand_scale: float
    junction_id: str


def compatibility_problems(
    row: dict, ctx: QueryContext, net: NetworkModel, limits: SignalLimits, demand_tolerance: float
) -> list[str]:
    """Return a list of human-readable reasons why ``row`` must NOT be reused (empty = compatible)."""
    p: list[str] = []
    if row["network_id"] != ctx.network_id:
        p.append("different road network")
    if row["tls_hash"] != ctx.tls_hash:
        p.append("different traffic-light configuration")
    if row["feature_schema"] != ctx.feature_schema:
        p.append(f"different feature schema ({row['feature_schema']} vs {ctx.feature_schema})")
    if row["objective_version"] != ctx.objective_version:
        p.append("different objective definition")
    if row["model_version"] != ctx.model_version:
        p.append("created with a different forecasting model version")
    if row["horizon_s"] != ctx.horizon_s or row["interval_s"] != ctx.interval_s:
        p.append("different prediction horizon / aggregation interval (units)")
    if abs(row["step_length_s"] - ctx.step_length_s) > 1e-9 or row["sim_duration_s"] != ctx.sim_duration_s:
        p.append("different simulation step length or duration")
    if row["decision_time_s"] != ctx.decision_time_s:
        p.append("different decision time")
    if row["junction_id"] != ctx.junction_id:
        p.append(f"different target junction ({row['junction_id']} vs {ctx.junction_id})")
    if ctx.demand_scale > 0:
        rel = abs(row["demand_scale"] - ctx.demand_scale) / ctx.demand_scale
        if rel > demand_tolerance:
            p.append(f"demand level differs by {rel * 100:.0f}% (tolerance {demand_tolerance * 100:.0f}%)")
    if not row["improved"]:
        p.append("stored outcome did not improve the objective")
    else:
        try:
            validate_intervention(net, Intervention.from_dict(row["intervention"]), limits)
        except (DataValidationError, KeyError, ValueError) as exc:
            p.append(f"intervention not valid under the current limits ({getattr(exc, 'message', exc)})")
    return p
