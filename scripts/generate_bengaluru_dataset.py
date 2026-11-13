"""Generate SUMO training data for the real-road OSM network around the TomTom sensors."""
from __future__ import annotations

import argparse
import sys

import _path  # noqa: F401
from app.core.config import get_settings
from app.core.errors import NexFlowError, SumoConfigError
from app.digital_twin.network import load_network
from app.ml.dataset import generate_synthetic_dataset, save_dataset
from app.sumo.runner import SumoRunner


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--runs", type=int, default=60)
parser.add_argument("--seed", type=int, default=2000)
args = parser.parse_args()

settings = get_settings()
try:
    if not settings.bengaluru_network_file.exists() or not settings.bengaluru_sumocfg_file.exists():
        raise SumoConfigError("Bengaluru OSM SUMO network has not been generated.",
                              hint="Run `python scripts/setup_bengaluru_sumo.py` first.")
    network = load_network(settings.bengaluru_network_file)
    runner = SumoRunner(network, settings, sumocfg_file=settings.bengaluru_sumocfg_file)
    dataset = generate_synthetic_dataset(
        network,
        runner,
        args.runs,
        base_seed=args.seed,
        duration_s=settings.scenario_duration_s,
        interval_s=settings.interval_s,
        workers=settings.max_concurrent_sumo,
        progress=lambda done, total: print(f"\r  simulated {done}/{total}", end="", flush=True),
    )
    dataset.meta.update({
        "synthetic": True,
        "source": "sumo_openstreetmap_network",
        "description": "Simulated demand on OpenStreetMap roads around the five TomTom sensor locations. "
                       "This is not measured or citywide Bengaluru traffic.",
    })
    path = save_dataset(dataset, settings.bengaluru_dataset_dir)
    print(f"\nSaved SUMO observations {dataset.obs.shape} to {path}")
    print("NOTE: OSM geometry is real; vehicle demand and traffic observations are simulated.")
except NexFlowError as exc:
    print(f"ERROR: {exc.message}\n{exc.hint or ''}")
    sys.exit(1)
