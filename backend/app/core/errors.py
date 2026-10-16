"""Domain exceptions. The API layer maps them to safe JSON errors (no stack traces)."""
from __future__ import annotations


class NexFlowError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class SumoUnavailableError(NexFlowError):
    status_code = 503
    code = "sumo_unavailable"


class SumoConfigError(NexFlowError):
    status_code = 422
    code = "sumo_config_invalid"


class SimulationError(NexFlowError):
    status_code = 500
    code = "simulation_failed"


class SimulationCancelled(NexFlowError):
    status_code = 409
    code = "simulation_cancelled"


class TwinSyncError(NexFlowError):
    status_code = 409
    code = "twin_sync_failed"


class ModelNotTrainedError(NexFlowError):
    status_code = 409
    code = "model_not_trained"


class DataValidationError(NexFlowError):
    status_code = 422
    code = "data_invalid"


class NotFoundError(NexFlowError):
    status_code = 404
    code = "not_found"


class ConflictError(NexFlowError):
    status_code = 409
    code = "conflict"
