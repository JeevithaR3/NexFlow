"""Request schemas (Pydantic).  Responses are plain JSON documented in docs/API.md."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.sumo.scenario import PATTERNS


class ScenarioIn(BaseModel):
    pattern: Literal["balanced", "ew_heavy", "ns_heavy"] = "ew_heavy"
    demand_scale: float = Field(1.2, ge=0.2, le=3.0)
    seed: int = Field(50001, ge=0, le=10_000_000)


class PredictionRunIn(BaseModel):
    scenario: ScenarioIn = ScenarioIn()
    mode: Literal["sumo", "dataset_replay"] = "sumo"


class InterventionIn(BaseModel):
    type: Literal["signal_timing", "reroute"] = "signal_timing"
    junction_id: str | None = Field(None, max_length=32)
    green_s: dict[str, float] | None = Field(None, description="phase index -> green seconds")
    reroute_share: float | None = Field(None, gt=0, le=1)
    reroute_period_s: float | None = Field(30.0, ge=5, le=600)

    @field_validator("green_s")
    @classmethod
    def _idx(cls, v):
        if v is not None:
            for k in v:
                if not k.isdigit():
                    raise ValueError("green_s keys must be phase indices such as '0' or '2'")
        return v


class SimulationRunIn(BaseModel):
    scenario: ScenarioIn = ScenarioIn()
    intervention: InterventionIn | None = None


class EvaluateIn(BaseModel):
    scenario: ScenarioIn = ScenarioIn()
    junction_id: str | None = Field(None, max_length=32)
    use_memory: bool = True
    include_rerouting: bool = False
    store_experience: bool = True


class BenchmarkRunIn(BaseModel):
    n_warmup: int = Field(6, ge=0, le=30)
    n_eval: int = Field(6, ge=1, le=30)
    seed_base: int = Field(50000, ge=50000, le=10_000_000)
    include_rerouting: bool = False
