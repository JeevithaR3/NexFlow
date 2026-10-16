"""Candidate generation for the intervention search (Approach A evaluates all of them)."""
from __future__ import annotations

from app.digital_twin.network import NetworkModel
from app.interventions.models import REROUTE, SIGNAL, Intervention, SignalLimits, validate_intervention
from app.core.errors import DataValidationError

# multiplicative changes of the two green phases relative to the network's default plan
DEFAULT_FACTORS: tuple[tuple[float, float], ...] = (
    (0.6, 1.0), (0.8, 1.0), (1.0, 0.6), (1.0, 0.8), (0.6, 1.3), (1.3, 0.6), (0.8, 1.3), (1.3, 0.8),
)
REROUTE_SHARES = (0.3, 0.6)


def signal_candidates(
    net: NetworkModel, junction_id: str, limits: SignalLimits, factors=DEFAULT_FACTORS
) -> list[Intervention]:
    greens = net.green_phases(junction_id)
    if len(greens) < 2:
        raise DataValidationError(f"Junction {junction_id} needs at least two green phases for timing candidates")
    a, b = greens[0], greens[1]
    out: list[Intervention] = []
    seen: set[tuple[int, int]] = set()
    for fa, fb in factors:
        ga = float(min(max(round(a.duration * fa), limits.min_green_s), limits.max_green_s))
        gb = float(min(max(round(b.duration * fb), limits.min_green_s), limits.max_green_s))
        if (ga, gb) in seen or (ga == a.duration and gb == b.duration):
            continue
        seen.add((ga, gb))
        iv = Intervention(SIGNAL, junction_id, {a.index: ga, b.index: gb})
        try:
            validate_intervention(net, iv, limits)
        except DataValidationError:
            continue
        out.append(Intervention(SIGNAL, junction_id, iv.params, label=f"{junction_id}: {a.axis} {ga:g}s / {b.axis} {gb:g}s"))
    return out


def reroute_candidates() -> list[Intervention]:
    return [
        Intervention(REROUTE, None, {"share": s, "period_s": 30.0}, label=f"Reroute {int(s * 100)}% of vehicles by live travel time")
        for s in REROUTE_SHARES
    ]
