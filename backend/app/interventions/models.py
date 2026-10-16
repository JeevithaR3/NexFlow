"""Intervention definitions and validation (all interventions are *simulated recommendations*)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.core.errors import DataValidationError
from app.digital_twin.network import NetworkModel

SIGNAL = "signal_timing"
REROUTE = "reroute"
YELLOW_MIN_S = 3.0


@dataclass(frozen=True)
class SignalLimits:
    """Legal/configured green-time bounds per green phase (seconds)."""

    min_green_s: float = 10.0
    max_green_s: float = 60.0
    max_cycle_s: float = 120.0

    def to_dict(self) -> dict:
        return {"min_green_s": self.min_green_s, "max_green_s": self.max_green_s, "max_cycle_s": self.max_cycle_s}


@dataclass(frozen=True)
class Intervention:
    type: str
    junction_id: str | None = None
    # signal_timing: {phase_index: green_seconds}; reroute: {"share": 0..1, "period_s": seconds}
    params: dict = field(default_factory=dict)
    label: str = ""

    def key(self) -> str:
        return json.dumps(
            {"t": self.type, "j": self.junction_id, "p": {str(k): v for k, v in sorted(self.params.items())}},
            sort_keys=True,
        )

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "junction_id": self.junction_id,
            "params": {str(k): v for k, v in self.params.items()},
            "label": self.label or self.describe(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Intervention":
        params = d.get("params", {})
        if d["type"] == SIGNAL:
            params = {int(k): float(v) for k, v in params.items()}
        return cls(type=d["type"], junction_id=d.get("junction_id"), params=params, label=d.get("label", ""))

    def describe(self) -> str:
        if self.type == SIGNAL:
            g = ", ".join(f"phase {k}: {v:g}s" for k, v in sorted(self.params.items()))
            return f"Signal timing at {self.junction_id} ({g})"
        if self.type == REROUTE:
            return f"Dynamic rerouting of {self.params.get('share', 0) * 100:.0f}% of vehicles every {self.params.get('period_s', 0):g}s"
        return self.type


def validate_intervention(net: NetworkModel, iv: Intervention, limits: SignalLimits) -> None:
    """Raise :class:`DataValidationError` for invalid or unsafe interventions."""
    if iv.type == SIGNAL:
        if iv.junction_id not in net.tls_programs:
            raise DataValidationError(f"Junction '{iv.junction_id}' has no traffic light in this network")
        greens = net.green_phases(iv.junction_id)
        valid_idx = {g.index for g in greens}
        if not iv.params:
            raise DataValidationError("signal_timing intervention needs green durations for at least one phase")
        for idx, dur in iv.params.items():
            if int(idx) not in valid_idx:
                raise DataValidationError(f"Phase {idx} is not a green phase of {iv.junction_id} (valid: {sorted(valid_idx)})")
            if not (limits.min_green_s <= float(dur) <= limits.max_green_s):
                raise DataValidationError(
                    f"Green time {dur}s for phase {idx} outside permitted range "
                    f"[{limits.min_green_s:g}, {limits.max_green_s:g}] s"
                )
        total = sum(
            float(iv.params.get(g.index, g.duration)) for g in greens
        ) + sum(p["duration"] for p in net.tls_programs[iv.junction_id] if p["index"] not in valid_idx)
        if total > limits.max_cycle_s:
            raise DataValidationError(f"Resulting cycle {total:g}s exceeds the maximum {limits.max_cycle_s:g}s")
    elif iv.type == REROUTE:
        share = float(iv.params.get("share", -1))
        period = float(iv.params.get("period_s", -1))
        if not (0.0 < share <= 1.0):
            raise DataValidationError("reroute share must be within (0, 1]")
        if not (5.0 <= period <= 600.0):
            raise DataValidationError("reroute period_s must be within [5, 600] seconds")
    else:
        raise DataValidationError(f"Unknown intervention type '{iv.type}'")
