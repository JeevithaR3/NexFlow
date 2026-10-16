"""Load a trained checkpoint and forecast congestion from a window of observations."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from app.core.errors import DataValidationError, ModelNotTrainedError
from app.digital_twin.congestion import congestion_index
from app.digital_twin.network import NetworkModel
from app.ml.dataset import FeatureScaler, static_features
from app.ml.graph import GraphSpec, normalized_adjacency
from app.ml.model import TrafficGNN
from app.sumo.collector import FEATURES, F_SPEED


class ForecastService:
    def __init__(self, model, scaler, static, a_hat, graph: GraphSpec, config: dict, version: str, trained_at: str):
        self.model, self.scaler, self.static, self.a_hat = model, scaler, static, a_hat
        self.graph, self.config, self.version, self.trained_at = graph, config, version, trained_at

    @classmethod
    def load(cls, path: Path, net: NetworkModel) -> "ForecastService":
        if not Path(path).exists():
            raise ModelNotTrainedError(
                "No trained GNN checkpoint found.", hint="Run `python scripts/train_gnn.py` (see README)."
            )
        ck = torch.load(path, map_location="cpu", weights_only=True)
        if ck["net_hash"] != net.net_hash:
            raise ModelNotTrainedError(
                "The GNN checkpoint was trained for a different network.",
                hint="Retrain the model with `python scripts/train_gnn.py`.",
            )
        if list(ck["features"]) != list(FEATURES):
            raise ModelNotTrainedError("Checkpoint feature schema differs from the current schema; retrain the model.")
        cfg = ck["config"]
        model = TrafficGNN(cfg["n_dynamic"], cfg["n_static"], hidden=cfg["hidden"])
        model.load_state_dict(ck["state_dict"])
        model.eval()
        graph = GraphSpec.from_network(net)
        return cls(
            model, FeatureScaler.from_dict(ck["scaler"]), torch.from_numpy(static_features(graph)),
            normalized_adjacency(graph.edge_index, graph.n_nodes), graph, cfg, ck["model_version"], ck["trained_at"],
        )

    @property
    def window(self) -> int:
        return int(self.config["window"])

    @property
    def horizon(self) -> int:
        return int(self.config["horizon"])

    @property
    def interval_s(self) -> int:
        return int(self.config["interval_s"])

    def predict(self, window_obs: np.ndarray) -> np.ndarray:
        """window_obs: [W, N, F] raw observations -> predicted CI [N] at ``horizon`` intervals ahead."""
        w, n, f = window_obs.shape
        if (w, n, f) != (self.window, self.graph.n_nodes, len(FEATURES)):
            raise DataValidationError(
                f"Expected a window of shape [{self.window}, {self.graph.n_nodes}, {len(FEATURES)}], got {tuple(window_obs.shape)}"
            )
        if not np.isfinite(window_obs).all():
            raise DataValidationError("Observation window contains non-finite values")
        x = torch.from_numpy(self.scaler.transform(window_obs.astype(np.float32))).unsqueeze(0)
        ci_last = torch.from_numpy(
            congestion_index(window_obs[-1, :, F_SPEED], self.graph.free_flow_speed).astype(np.float32)
        ).unsqueeze(0)
        with torch.no_grad():
            return self.model(x, self.static, self.a_hat, ci_last).clamp(0, 1)[0].numpy()
