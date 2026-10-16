"""Central, environment-driven configuration (prefix ``NEXFLOW_``).

No machine-specific path is hard-coded: everything is derived from the repository root
or overridden through environment variables / a ``.env`` file.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXFLOW_", env_file=str(ROOT_DIR / ".env"), extra="ignore"
    )

    # ---- paths -------------------------------------------------------------------
    data_dir: Path = ROOT_DIR / "data"
    models_dir: Path = ROOT_DIR / "models"
    simulation_dir: Path = ROOT_DIR / "simulation"
    database_url: str | None = None  # default: sqlite file inside data_dir

    # ---- SUMO --------------------------------------------------------------------
    sumo_binary: str | None = None  # explicit path to `sumo`; otherwise auto-detected
    sumo_gui: bool = False  # visualisation mode (needs sumo-gui + a display)
    max_concurrent_sumo: int = Field(2, ge=1, le=16)
    sumo_start_timeout_s: float = 30.0
    keep_run_dirs: bool = False

    # ---- geographic placement of the synthetic network (for Leaflet) ------------------
    map_origin_lat: float = 12.9716
    map_origin_lon: float = 77.5946

    # ---- forecasting -------------------------------------------------------------------
    interval_s: int = 90  # aggregation interval = one signal cycle (90 s) of the demo network
    window: int = 5  # number of past intervals fed to the GNN
    horizon: int = 3  # prediction horizon in intervals (=> horizon * interval_s seconds)

    # ---- scenario / decision -----------------------------------------------------
    scenario_duration_s: int = 1260  # 14 intervals of 90 s
    decision_time_s: int = 540  # intervention becomes active here; metrics measured after

    # ---- experience memory --------------------------------------------------------
    memory_similarity_threshold: float = 0.90
    memory_top_k: int = 5
    memory_demand_tolerance: float = 0.25  # allowed relative |demand_scale| difference
    memory_min_improvement: float = 0.02  # verification: minimum objective improvement

    # ---- API ---------------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"
    log_json: bool = False

    # ---- derived paths ---------------------------------------------------------------
    @property
    def network_file(self) -> Path:
        return self.simulation_dir / "network" / "network.net.xml"

    @property
    def sumocfg_file(self) -> Path:
        return self.simulation_dir / "configs" / "simulation.sumocfg"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def dataset_dir(self) -> Path:
        return self.data_dir / "synthetic"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'nexflow.db').as_posix()}"

    @property
    def checkpoint_file(self) -> Path:
        return self.models_dir / "gnn_forecaster.pt"

    @property
    def model_metrics_file(self) -> Path:
        return self.models_dir / "gnn_metrics.json"

    @property
    def twin_state_file(self) -> Path:
        return self.data_dir / "twin_state.json"

    @property
    def horizon_s(self) -> int:
        return self.horizon * self.interval_s

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.models_dir, self.runs_dir, self.dataset_dir, self.memory_dir):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


def reset_settings_cache() -> None:
    get_settings.cache_clear()
