"""Train the GNN forecaster on the synthetic dataset and write checkpoint + metrics."""
import argparse
import sys

import _path  # noqa: F401
from app.core.config import get_settings
from app.core.errors import NexFlowError
from app.digital_twin.network import load_network
from app.ml.dataset import load_dataset
from app.ml.graph import GraphSpec
from app.ml.train import train_forecaster

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--epochs", type=int, default=200)
p.add_argument("--hidden", type=int, default=64)
p.add_argument("--seed", type=int, default=7)
a = p.parse_args()
s = get_settings()
try:
    net = load_network(s.network_file)
    ds = load_dataset(s.dataset_dir)
    if ds.meta.get("net_hash") != net.net_hash:
        raise NexFlowError("Dataset was generated for a different network.", hint="Re-run scripts/generate_dataset.py")
    m = train_forecaster(
        ds, GraphSpec.from_network(net), window=s.window, horizon=s.horizon, interval_s=s.interval_s,
        checkpoint_path=s.checkpoint_file, metrics_path=s.model_metrics_file, epochs=a.epochs, hidden=a.hidden,
        seed=a.seed, net_hash=net.net_hash, tls_hash=net.tls_hash,
        progress=lambda e, tl, vm: print(f"  epoch {e:3d}  train_mse={tl:.5f}  val_mae={vm:.4f}") if e % 10 == 0 else None,
    )
    print(f"\nHorizon: {m['horizon_s']} s ({m['horizon_intervals']} x {m['interval_s']} s). Target: {m['target']}")
    for split in ("validation", "test"):
        r = m[split]
        print(f"{split:10s} n={r['n_samples']:4d} " + " | ".join(
            f"{k}: MAE {r[k]['mae']:.4f} RMSE {r[k]['rmse']:.4f} acc {r[k]['level_accuracy']:.3f}"
            for k in ("gnn", "persistence", "train_mean", "train_median")))
    print(f"checkpoint: {s.checkpoint_file}\nmetrics:    {s.model_metrics_file}")
except NexFlowError as e:
    print(f"ERROR: {e.message}\n{e.hint or ''}")
    sys.exit(1)
