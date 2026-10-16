"""Application state: long-lived services shared by the API (created once at startup)."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from app.core.config import Settings
from app.core.errors import ModelNotTrainedError, NexFlowError
from app.core.logging import get_logger
from app.digital_twin.network import NetworkModel, load_network
from app.digital_twin.twin import DigitalTwin
from app.experience_memory.memory import ExperienceMemory
from app.interventions.models import SignalLimits
from app.ml.inference import ForecastService
from app.models.db import Database
from app.services.jobs import JobManager
from app.sumo.environment import SumoStatus, check_sumo
from app.sumo.runner import SumoRunner

log = get_logger("state")


@dataclass
class AppState:
    settings: Settings
    db: Database
    jobs: JobManager
    net: NetworkModel | None = None
    net_error: str | None = None
    twin: DigitalTwin | None = None
    memory: ExperienceMemory | None = None
    forecaster: ForecastService | None = None
    forecaster_error: str | None = None
    runner: SumoRunner | None = None
    limits: SignalLimits = field(default_factory=SignalLimits)
    _sumo: tuple[float, SumoStatus] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def build(cls, settings: Settings) -> "AppState":
        db = Database(settings.db_url)
        st = cls(settings=settings, db=db, jobs=JobManager(db))
        try:
            st.net = load_network(settings.network_file)
        except NexFlowError as e:
            st.net_error = e.message
            log.error("network unavailable", extra={"error": e.message})
            return st
        st.twin = DigitalTwin(st.net, settings.window, settings.twin_state_file)
        st.twin.load()
        st.memory = ExperienceMemory(db, settings.memory_dir, st.net, st.limits)
        st.runner = SumoRunner(st.net, settings, st.limits)
        st.reload_model()
        return st

    def reload_model(self) -> None:
        try:
            self.forecaster = ForecastService.load(self.settings.checkpoint_file, self.net)
            self.forecaster_error = None
        except ModelNotTrainedError as e:
            self.forecaster, self.forecaster_error = None, e.message

    def sumo_status(self) -> SumoStatus:
        with self._lock:
            if self._sumo is None or time.time() - self._sumo[0] > 30:
                self._sumo = (time.time(), check_sumo())
            return self._sumo[1]
