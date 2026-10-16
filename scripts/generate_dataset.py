"""Generate the synthetic training dataset by running baseline SUMO simulations."""
import argparse
import sys
import time

import _path  # noqa: F401
from app.core.config import get_settings
from app.core.errors import NexFlowError
from app.digital_twin.network import load_network
from app.ml.dataset import generate_synthetic_dataset, save_dataset
from app.sumo.runner import SumoRunner

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--runs", type=int, default=90, help="number of SUMO simulations (default 90)")
p.add_argument("--seed", type=int, default=1000, help="base seed (must be < 50000, reserved for benchmarks)")
p.add_argument("--workers", type=int, default=2)
a = p.parse_args()
s = get_settings()
try:
    net = load_network(s.network_file)
    t0 = time.perf_counter()
    ds = generate_synthetic_dataset(
        net, SumoRunner(net), a.runs, base_seed=a.seed, duration_s=s.scenario_duration_s,
        interval_s=s.interval_s, workers=a.workers,
        progress=lambda d, n: print(f"\r  simulated {d}/{n}", end="", flush=True),
    )
    path = save_dataset(ds, s.dataset_dir)
    print(f"\nSaved {ds.obs.shape} (runs, intervals, segments, features) to {path} in {time.perf_counter()-t0:.0f}s")
    print("NOTE: synthetic data produced by SUMO; not real traffic.")
except NexFlowError as e:
    print(f"ERROR: {e.message}\n{e.hint or ''}")
    sys.exit(1)
