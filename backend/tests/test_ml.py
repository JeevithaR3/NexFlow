import numpy as np
import pytest
import torch

from app.core.errors import DataValidationError
from app.digital_twin.congestion import congestion_index, level_of
from app.ml.dataset import FeatureScaler, chronological_split, impute_missing, make_windows, validate_obs
from app.ml.graph import GraphSpec, normalized_adjacency
from app.ml.model import TrafficGNN
from app.ml.train import train_forecaster
from app.ml.dataset import TrafficDataset


def tiny_graph(n=6):
    ei = np.array([[i, i + 1] for i in range(n - 1)], dtype=np.int64).T
    return GraphSpec([f"e{i}" for i in range(n)], ei, np.full(n, 10.0, np.float32), np.full(n, 100.0, np.float32))


def tiny_obs(r=9, t=14, n=6, seed=0):
    rng = np.random.default_rng(seed)
    obs = np.zeros((r, t, n, 5), np.float32)
    level = rng.uniform(0.2, 0.8, (r, 1, n))
    obs[..., 1] = 10 * (1 - level) + rng.normal(0, 0.3, (r, t, n))
    obs[..., 0] = 400 * level + rng.normal(0, 5, (r, t, n))
    obs[..., 2:] = np.abs(rng.normal(3, 1, (r, t, n, 3)))
    return np.clip(obs, 0, None)


def test_congestion_levels():
    assert congestion_index(np.array([10.0]), np.array([10.0]))[0] == 0
    assert level_of(0.1) == "low" and level_of(0.45) == "moderate" and level_of(0.9) == "high"
    assert level_of(None) == "unknown" and level_of(float("nan")) == "unknown"


def test_graph_adjacency_is_symmetric_and_normalised():
    a = normalized_adjacency(tiny_graph().edge_index, 6)
    assert torch.allclose(a, a.T)
    assert (a.sum(1) > 0).all()


def test_chronological_split_has_no_overlap():
    tr, va, te = chronological_split(20)
    assert tr.stop == va.start and va.stop == te.start and te.stop == 20


def test_windows_do_not_cross_runs_and_target_is_horizon_ahead():
    g, obs = tiny_graph(), tiny_obs(r=3, t=14)
    w = make_windows(obs, g, window=5, horizon=3)
    assert len(w.y) == 3 * (14 - 5 - 3 + 1)
    ci = congestion_index(obs[..., 1], g.free_flow_speed)
    assert np.allclose(w.y[0], ci[0, 5 - 1 + 3])
    assert np.allclose(w.ci_last[0], ci[0, 4])


def test_missing_values_forward_filled_within_run_only():
    g, obs = tiny_graph(), tiny_obs(r=3, t=5)
    obs[1, 0, 2, 1] = np.nan
    obs[1, 3, 2, 0] = np.nan
    out = impute_missing(obs, g.free_flow_speed)
    assert np.isfinite(out).all()
    assert out[1, 0, 2, 1] == 10.0  # leading gap -> free-flow speed
    assert out[1, 3, 2, 0] == out[1, 2, 2, 0]


def test_scaler_fit_on_train_only():
    obs = tiny_obs(r=10)
    tr = chronological_split(10)[0]
    sc = FeatureScaler.fit(obs[tr])
    assert np.allclose(sc.mean, obs[tr].reshape(-1, 5).mean(0), atol=1e-4)


def test_validation_rejects_bad_data():
    with pytest.raises(DataValidationError):
        validate_obs(np.zeros((5, 5, 6)), 6)
    with pytest.raises(DataValidationError):
        validate_obs(np.zeros((5, 5, 7, 5)), 6)
    bad = tiny_obs(); bad[0, 0, 0, 0] = -1
    with pytest.raises(DataValidationError):
        validate_obs(bad, 6)


def test_gnn_forward_shape():
    m = TrafficGNN(5, 2, hidden=8)
    out = m(torch.randn(4, 5, 6, 5), torch.randn(6, 2), normalized_adjacency(tiny_graph().edge_index, 6), torch.rand(4, 6))
    assert out.shape == (4, 6)


def test_training_runs_saves_checkpoint_and_reports_baselines(tmp_path):
    g = tiny_graph()
    ds = TrafficDataset(tiny_obs(r=10), [{}] * 10, {"synthetic": True})
    m = train_forecaster(ds, g, window=5, horizon=3, interval_s=90, checkpoint_path=tmp_path / "m.pt",
                         metrics_path=tmp_path / "m.json", epochs=5, hidden=8, net_hash="h", tls_hash="t")
    assert (tmp_path / "m.pt").exists() and (tmp_path / "m.json").exists()
    for k in ("gnn", "persistence", "train_mean", "train_median"):
        assert m["test"][k]["mae"] >= 0 and m["test"][k]["rmse"] >= m["test"][k]["mae"] - 1e-9
    assert m["history"][-1]["epoch"] == m["epochs_run"]
    ck = torch.load(tmp_path / "m.pt", weights_only=True)
    assert ck["config"]["horizon"] == 3
