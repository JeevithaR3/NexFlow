"""Application state: network, database, memory, twin, forecaster, runner and jobs."""
from __future__ import annotations

import json

from app.core.config import Settings, get_settings
from app.core.errors import ModelNotTrainedError, NexFlowError, SumoConfigError
from app.core.logging import get_logger
from app.digital_twin.network import NetworkModel, load_network
from app.digital_twin.twin import DigitalTwin
from app.experience_memory.memory import ExperienceMemory
from app.interventions.models import SignalLimits
from app.ml.inference import ForecastService
from app.models.db import Database
from app.services.decision import DecisionEngine
from app.services.jobs import JobManager
from app.sumo.runner import SumoRunner

log = get_logger("state")


class AppState:
    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()
        self.s.ensure_dirs()
        self.limits = SignalLimits()
        self.db = Database(self.s.db_url)
        self.jobs = JobManager(self.db, workers=self.s.max_concurrent_sumo + 1)
        self.net: NetworkModel | None = None
        self.net_error: NexFlowError | None = None
        self.twin: DigitalTwin | None = None
        self.memory: ExperienceMemory | None = None
        self.runner: SumoRunner | None = None
        self._fc: ForecastService | None = None
        self._fc_mtime = -1.0
        self.fc_error: NexFlowError | None = None
        try:
            self.net = load_network(self.s.network_file)
            self.twin = DigitalTwin(self.net, self.s.window, self.s.twin_state_file)
            self.twin.load()
            self.memory = ExperienceMemory(self.db, self.s.memory_dir, self.net, self.limits)
            self.runner = SumoRunner(self.net, self.s, self.limits)
        except SumoConfigError as e:
            self.net_error = e

    def require_net(self) -> NetworkModel:
        if self.net is None:
            raise self.net_error or SumoConfigError("Network not loaded")
        return self.net

    @property
    def forecaster(self) -> ForecastService | None:
        """Loads (and hot-reloads after retraining) the GNN checkpoint."""
        ck = self.s.checkpoint_file
        mtime = ck.stat().st_mtime if ck.exists() else -1.0
        if mtime != self._fc_mtime:
            self._fc_mtime = mtime
            try:
                self._fc, self.fc_error = ForecastService.load(ck, self.require_net()), None
            except NexFlowError as e:
                self._fc, self.fc_error = None, e
        return self._fc

    def engine(self) -> DecisionEngine:
        net = self.require_net()
        return DecisionEngine(net, self.runner, self.forecaster, self.memory, self.twin, self.s, limits=self.limits)

    def model_metrics(self) -> dict | None:
        f = self.s.model_metrics_file
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
