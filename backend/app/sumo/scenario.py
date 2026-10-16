"""Reproducible traffic-demand scenarios.

A scenario is (pattern, demand_scale, seed, duration).  Trips are drawn from a
non-homogeneous Poisson process with a NumPy generator seeded from the scenario, so the
same scenario always yields exactly the same route file - the key requirement for
comparing a baseline with intervention candidates under identical demand.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from app.core.errors import DataValidationError
from app.digital_twin.network import SIDES, NetworkModel

PATTERNS = ("balanced", "ew_heavy", "ns_heavy")
# veh/h per entry edge at multiplier 1.0: (main axis sides, cross axis sides)
_RATES = {
    "balanced": {"left": 150, "right": 150, "top": 150, "bottom": 150},
    "ew_heavy": {"left": 230, "right": 230, "top": 70, "bottom": 70},
    "ns_heavy": {"left": 70, "right": 70, "top": 230, "bottom": 230},
}
_OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
_LATERAL = {"left": ("top", "bottom"), "right": ("top", "bottom"), "top": ("left", "right"), "bottom": ("left", "right")}
THROUGH_SHARE = 0.65


@dataclass(frozen=True)
class ScenarioConfig:
    pattern: str = "ew_heavy"
    demand_scale: float = 1.0
    seed: int = 1
    duration_s: int = 1200
    step_length_s: float = 1.0

    def __post_init__(self) -> None:
        if self.pattern not in PATTERNS:
            raise DataValidationError(f"Unknown pattern '{self.pattern}'. Allowed: {', '.join(PATTERNS)}")
        if not (0.2 <= self.demand_scale <= 3.0):
            raise DataValidationError("demand_scale must be within [0.2, 3.0]")
        if self.duration_s < 60 or self.duration_s > 7200:
            raise DataValidationError("duration_s must be within [60, 7200]")
        if self.step_length_s <= 0 or self.step_length_s > 5:
            raise DataValidationError("step_length_s must be within (0, 5]")

    @property
    def scenario_id(self) -> str:
        return f"{self.pattern}-x{self.demand_scale:.2f}-s{self.seed}-d{self.duration_s}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ScenarioConfig":
        keys = {"pattern", "demand_scale", "seed", "duration_s", "step_length_s"}
        return cls(**{k: v for k, v in d.items() if k in keys})


def rate_multiplier(t: float, duration: float) -> float:
    """Demand profile: rises linearly from 0.5x to 1.2x over the first half, then stays."""
    return 0.5 + 0.7 * min(1.0, t / (0.5 * duration))


def build_trips(net: NetworkModel, sc: ScenarioConfig) -> list[tuple[float, str, str]]:
    seed_material = hashlib.sha256(f"{sc.pattern}|{sc.seed}".encode()).digest()[:8]
    rng = np.random.default_rng([sc.seed, int.from_bytes(seed_material, "little")])
    rates = _RATES[sc.pattern]
    trips: list[tuple[float, str, str]] = []
    for side in SIDES:
        for origin in net.origin_by_side[side]:
            lam_max = rates[side] * sc.demand_scale * 1.2 / 3600.0
            t = 0.0
            while True:
                t += rng.exponential(1.0 / lam_max)
                if t >= sc.duration_s:
                    break
                keep = rate_multiplier(t, sc.duration_s) / 1.2
                if rng.random() > keep:
                    continue
                r = rng.random()
                if r < THROUGH_SHARE:
                    dside = _OPPOSITE[side]
                else:
                    dside = _LATERAL[side][0 if r < THROUGH_SHARE + (1 - THROUGH_SHARE) / 2 else 1]
                dests = net.dest_by_side[dside]
                trips.append((round(t, 2), origin, dests[int(rng.integers(len(dests)))]))
    trips.sort(key=lambda x: (x[0], x[1], x[2]))
    return trips


def write_route_file(net: NetworkModel, sc: ScenarioConfig, path: Path) -> int:
    trips = build_trips(net, sc)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<!-- NexFlow synthetic demand: {sc.scenario_id}; generated, not real traffic data -->",
        '<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">',
        '    <vType id="car" vClass="passenger" length="5.0" minGap="2.5" accel="2.6" decel="4.5" '
        'sigma="0.5" maxSpeed="13.89"/>',
    ]
    for i, (dep, o, d) in enumerate(trips):
        lines.append(
            f'    <trip id="v{i}" type="car" depart="{dep}" from="{o}" to="{d}" departLane="best" departSpeed="max"/>'
        )
    lines.append("</routes>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(trips)
