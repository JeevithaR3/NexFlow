"""Train the shared GCN-GRU architecture for the Bengaluru OSM SUMO network."""
from __future__ import annotations

import argparse
import sys

import _path  # noqa: F401
from app.core.config import get_settings
from app.core.errors import NexFlowError, SumoConfigError
from app.digital_twin.network import load_network
from app.ml.dataset import load_dataset
from app.ml.graph import GraphSpec
from app.ml.train import train_forecaster


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--epochs", type=int, default=200)
parser.add_argument("--hidden", type=int, default=64)
parser.add_argument("--seed", type=int, default=7)
args = parser.parse_args()

settings = get_settings()
try:
    if not settings.bengaluru_network_file.exists():
        raise SumoConfigError("Bengaluru OSM SUMO network has not been generated.",
                              hint="Run `python scripts/setup_bengaluru_sumo.py` first.")
    network = load_network(settings.bengaluru_network_file)
    dataset = load_dataset(settings.bengaluru_dataset_dir)
    if dataset.meta.get("net_hash") != network.net_hash:
        raise SumoConfigError("Bengaluru SUMO dataset belongs to a different road network.",
                              hint="Regenerate it with scripts/generate_bengaluru_dataset.py.")
    metrics = train_forecaster(
        dataset,
        GraphSpec.from_network(network),
        window=settings.window,
        horizon=settings.horizon,
        interval_s=settings.interval_s,
        checkpoint_path=settings.bengaluru_checkpoint_file,
        metrics_path=settings.bengaluru_metrics_file,
        epochs=args.epochs,
        hidden=args.hidden,
        seed=args.seed,
        net_hash=network.net_hash,
        tls_hash=network.tls_hash,
    )
    print(f"Trained model {metrics['model_version']} for {metrics['horizon_s']} seconds ahead.")
    print(f"Test GNN MAE: {metrics['test']['gnn']['mae']:.4f}; checkpoint: {settings.bengaluru_checkpoint_file}")
    print("NOTE: trained on SUMO-simulated traffic on OSM roads, not TomTom observations.")
except NexFlowError as exc:
    print(f"ERROR: {exc.message}\n{exc.hint or ''}")
    sys.exit(1)
