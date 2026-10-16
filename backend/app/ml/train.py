"""Training and evaluation of the GNN forecaster (with baselines)."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import torch
from torch import nn

from app.core.logging import get_logger
from app.digital_twin.congestion import level_ids
from app.ml.dataset import (
    FeatureScaler, TrafficDataset, Windows, chronological_split, impute_missing, make_windows,
    static_features, validate_obs,
)
from app.ml.graph import GraphSpec, normalized_adjacency
from app.ml.model import TrafficGNN
from app.sumo.collector import FEATURES

log = get_logger("ml.train")
MODEL_FAMILY = "gnn-v1"


def regression_metrics(pred: np.ndarray, true: np.ndarray) -> dict:
    err = pred - true
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "level_accuracy": float(np.mean(level_ids(pred) == level_ids(true))),
    }


def _tensors(w: Windows, scaler: FeatureScaler):
    return (
        torch.from_numpy(scaler.transform(w.x)),
        torch.from_numpy(w.ci_last),
        torch.from_numpy(w.y),
    )


def _predict(model, x, ci_last, static, a_hat, batch=256) -> np.ndarray:
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            out.append(model(x[i : i + batch], static, a_hat, ci_last[i : i + batch]).clamp(0, 1))
    return torch.cat(out).numpy()


def train_forecaster(
    ds: TrafficDataset,
    graph: GraphSpec,
    *,
    window: int,
    horizon: int,
    interval_s: int,
    checkpoint_path: Path,
    metrics_path: Path | None = None,
    epochs: int = 200,
    patience: int = 20,
    lr: float = 2e-3,
    hidden: int = 64,
    batch_size: int = 32,
    seed: int = 7,
    loss: str = "l1",
    net_hash: str = "",
    tls_hash: str = "",
    progress: Callable[[int, float, float], None] | None = None,
) -> dict:
    graph.validate()
    validate_obs(ds.obs, graph.n_nodes)
    torch.manual_seed(seed)
    np.random.seed(seed)
    obs = impute_missing(ds.obs, graph.free_flow_speed)
    tr, va, te = chronological_split(obs.shape[0])
    scaler = FeatureScaler.fit(obs[tr])  # training runs only -> no leakage
    w_tr, w_va, w_te = (make_windows(obs[s], graph, window, horizon) for s in (tr, va, te))
    x_tr, l_tr, y_tr = _tensors(w_tr, scaler)
    x_va, l_va, y_va = _tensors(w_va, scaler)
    x_te, l_te, y_te = _tensors(w_te, scaler)
    static = torch.from_numpy(static_features(graph))
    a_hat = normalized_adjacency(graph.edge_index, graph.n_nodes)

    model = TrafficGNN(len(FEATURES), static.shape[1], hidden=hidden)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    loss_fn = {"mse": nn.MSELoss(), "l1": nn.L1Loss(), "huber": nn.HuberLoss(delta=0.1)}[loss]
    gen = torch.Generator().manual_seed(seed)
    best, best_state, bad, history = float("inf"), None, 0, []
    t0 = time.perf_counter()
    for epoch in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(len(x_tr), generator=gen)
        total = 0.0
        for i in range(0, len(perm), batch_size):
            idx = perm[i : i + batch_size]
            opt.zero_grad()
            batch_loss = loss_fn(model(x_tr[idx], static, a_hat, l_tr[idx]), y_tr[idx])
            batch_loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            total += batch_loss.item() * len(idx)
        val_pred = _predict(model, x_va, l_va, static, a_hat)
        val_mae = float(np.mean(np.abs(val_pred - y_va.numpy())))
        history.append({"epoch": epoch, "train_loss": total / len(perm), "val_mae": val_mae})
        if progress:
            progress(epoch, total / len(perm), val_mae)
        if val_mae < best - 1e-5:
            best, bad = val_mae, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    model.load_state_dict(best_state)

    def evaluate(w: Windows, x, l, y) -> dict:
        g = _predict(model, x, l, static, a_hat)
        mean_base = np.broadcast_to(w_tr.y.mean(0), w.y.shape)  # per-segment mean of training targets
        return {
            "n_samples": int(len(w.y)),
            "gnn": regression_metrics(g, w.y),
            "persistence": regression_metrics(w.ci_last, w.y),
            "train_mean": regression_metrics(mean_base, w.y),
            "train_median": regression_metrics(np.broadcast_to(np.median(w_tr.y, axis=0), w.y.shape), w.y),
        }

    metrics = {
        "model_family": MODEL_FAMILY,
        "target": "congestion_index (dimensionless, 0-1) of each road segment at t_last + horizon",
        "units": "CI is dimensionless; MAE/RMSE are in CI units",
        "synthetic_data": bool(ds.meta.get("synthetic", False)),
        "window_intervals": window,
        "horizon_intervals": horizon,
        "interval_s": interval_s,
        "horizon_s": horizon * interval_s,
        "split": {
            "type": "chronological by run order",
            "train_runs": tr.stop - tr.start, "val_runs": va.stop - va.start, "test_runs": te.stop - te.start,
        },
        "validation": evaluate(w_va, x_va, l_va, y_va),
        "test": evaluate(w_te, x_te, l_te, y_te),
        "history": history,
        "epochs_run": len(history),
        "best_val_mae": best,
        "train_seconds": round(time.perf_counter() - t0, 2),
        "seed": seed,
        "loss": loss,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "net_hash": net_hash,
        "tls_hash": tls_hash,
    }
    h = hashlib.sha256()
    for k in sorted(best_state):
        h.update(best_state[k].numpy().tobytes())
    metrics["model_version"] = f"{MODEL_FAMILY}-{h.hexdigest()[:8]}"

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": best_state,
            "config": {
                "n_dynamic": len(FEATURES), "n_static": int(static.shape[1]), "hidden": hidden,
                "window": window, "horizon": horizon, "interval_s": interval_s,
            },
            "scaler": scaler.to_dict(),
            "features": list(FEATURES),
            "net_hash": net_hash,
            "tls_hash": tls_hash,
            "model_version": metrics["model_version"],
            "trained_at": metrics["trained_at"],
        },
        checkpoint_path,
    )
    if metrics_path:
        metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics
