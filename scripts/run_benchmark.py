"""Run the Approach-A vs Approach-B benchmark and store the result (database + JSON file)."""
import argparse
import json
import sys

import _path  # noqa: F401
from app.core.config import get_settings
from app.core.errors import NexFlowError
from app.digital_twin.network import load_network
from app.ml.inference import ForecastService
from app.models.db import BenchmarkRow, Database
from app.benchmark.runner import run_benchmark

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--warmup", type=int, default=8, help="scenarios used to pre-populate the memory")
p.add_argument("--eval", type=int, default=12, help="evaluation scenarios (each is decided twice: A and B)")
p.add_argument("--seed-base", type=int, default=50000)
p.add_argument("--rerouting", action="store_true", help="also evaluate rerouting candidates")
a = p.parse_args()
s = get_settings()
try:
    net = load_network(s.network_file)
    fc = ForecastService.load(s.checkpoint_file, net)
    res = run_benchmark(
        net, fc, n_warmup=a.warmup, n_eval=a.eval, seed_base=a.seed_base, include_rerouting=a.rerouting,
        progress=lambda f, m: print(f"  [{f * 100:5.1f}%] {m}", flush=True),
    )
    out = s.data_dir / "benchmarks"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"benchmark_{res['id']}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    db = Database(s.db_url)
    with db.session() as sess:
        sess.add(BenchmarkRow(id=res["id"], config=res["config"], result=res))
    sm = res["summary"]
    print(json.dumps({k: sm[k] for k in ("A", "B", "runs_saved_pct", "time_saved_pct", "reuse_rate", "memory_outcomes")}, indent=2))
    print("\n".join(sm["notes"]))
except NexFlowError as e:
    print(f"ERROR: {e.message}\n{e.hint or ''}")
    sys.exit(1)
