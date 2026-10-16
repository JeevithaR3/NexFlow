"""Reproducible benchmark: Approach A (simulate every candidate) vs Approach B (memory first).

Both approaches see the *same* evaluation scenarios, the same candidate set, the same objective and run
on the same machine, interleaved scenario by scenario.  Memory used by B lives in an isolated database and
FAISS index created for the benchmark, pre-filled by ``n_warmup`` ordinary searches (their cost is
reported separately) and then updated online as B decides.  Nothing is hard-coded: every number in the
result comes from measured SUMO runs and timers.
"""
from __future__ import annotations

import platform
import shutil
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from app.core.config import Settings, get_settings
from app.core.errors import DataValidationError, SimulationCancelled
from app.core.logging import get_logger
from app.digital_twin.network import NetworkModel
from app.experience_memory.memory import ExperienceMemory
from app.ml.dataset import BENCHMARK_SEED_BASE
from app.ml.inference import ForecastService
from app.models.db import Database
from app.services.decision import DecisionEngine
from app.sumo.environment import check_sumo
from app.sumo.runner import SumoRunner
from app.sumo.scenario import PATTERNS, ScenarioConfig

log = get_logger("benchmark")
IMPROVEMENT_TOLERANCE = 0.01  # B counts as "less effective" if it is >1 percentage point worse than A


def make_scenarios(n: int, base_seed: int, duration_s: int, rng_seed: int) -> list[ScenarioConfig]:
    rng = np.random.default_rng(rng_seed)
    return [
        ScenarioConfig(PATTERNS[i % len(PATTERNS)], round(float(rng.uniform(0.9, 1.4)), 2), base_seed + i, duration_s)
        for i in range(n)
    ]


def _digest(res: dict) -> dict:
    sel = res["selected"]
    best_eval = max((c["improvement"] for c in res["candidates"] if c["valid"]), default=None)
    mem = res["memory"]
    top = next((m for m in mem["matches"] if m["accepted"]), None)
    return {
        "sumo_runs": res["cost"]["sumo_runs"],
        "decision_s": res["cost"]["decision_seconds"],
        "sumo_s": res["cost"]["sumo_seconds"],
        "lookup_s": res["cost"]["lookup_seconds"],
        "source": res["source"],
        "target_junction": res["target_junction"],
        "recommendation": res["recommendation"],
        "intervention": sel["intervention"]["label"] if sel else None,
        "improvement": sel["improvement"] if sel else 0.0,
        "best_evaluated_improvement": best_eval,
        "memory_outcome": mem["outcome"],
        "matches_inspected": len(mem["matches"]),
        "matches_accepted": sum(1 for m in mem["matches"] if m["accepted"]),
        "top_similarity": top["similarity"] if top else (mem["matches"][0]["similarity"] if mem["matches"] else None),
        "rejection_reasons": [r for m in mem["matches"] if not m["accepted"] for r in m["reasons"]],
        "verification_failure": mem.get("verification_failure"),
    }


def summarize(rows: list[dict], warmup: dict) -> dict:
    n = len(rows)
    A = [r["A"] for r in rows]
    B = [r["B"] for r in rows]
    runs_a, runs_b = sum(a["sumo_runs"] for a in A), sum(b["sumo_runs"] for b in B)
    sec_a, sec_b = sum(a["decision_s"] for a in A), sum(b["decision_s"] for b in B)
    outcomes = Counter(b["memory_outcome"] for b in B)
    reused = outcomes.get("reused", 0)
    reasons = Counter()
    for b in B:
        for r in b["rejection_reasons"]:
            reasons[r.split(" (")[0].split(" below")[0]] += 1
    less_eff = [r["scenario"]["scenario_id"] for r in rows if r["A"]["improvement"] - r["B"]["improvement"] > IMPROVEMENT_TOLERANCE]
    slower = [r["scenario"]["scenario_id"] for r in rows if r["B"]["decision_s"] > r["A"]["decision_s"]]
    saved_per_decision = (runs_a - runs_b) / n if n else 0.0
    summary = {
        "n_scenarios": n,
        "A": {"sumo_runs": runs_a, "decision_seconds": round(sec_a, 2),
              "mean_improvement": round(float(np.mean([a["improvement"] for a in A])), 4) if n else 0.0},
        "B": {"sumo_runs": runs_b, "decision_seconds": round(sec_b, 2),
              "lookup_seconds": round(sum(b["lookup_s"] for b in B), 4),
              "mean_improvement": round(float(np.mean([b["improvement"] for b in B])), 4) if n else 0.0},
        "runs_saved": runs_a - runs_b,
        "runs_saved_pct": round(100.0 * (runs_a - runs_b) / runs_a, 1) if runs_a else 0.0,
        "time_saved_s": round(sec_a - sec_b, 2),
        "time_saved_pct": round(100.0 * (sec_a - sec_b) / sec_a, 1) if sec_a else 0.0,
        "memory_outcomes": dict(outcomes),
        "reuse_rate": round(reused / n, 3) if n else 0.0,
        "verification_failures": outcomes.get("failed_verification", 0),
        "rejected_match_reasons": dict(reasons.most_common()),
        "cases_B_less_effective": less_eff,
        "cases_B_slower": slower,
        "warmup": warmup,
        "break_even_decisions": (
            round(warmup["sumo_runs"] / saved_per_decision, 1) if saved_per_decision > 0 else None
        ),
    }
    notes = []
    if runs_b < runs_a:
        notes.append(f"Memory-first used {summary['runs_saved']} fewer SUMO runs ({summary['runs_saved_pct']}%) over {n} scenarios.")
    elif runs_b == runs_a:
        notes.append("Memory-first used the same number of SUMO runs as the full search: no efficiency gain was measured.")
    else:
        notes.append(f"Memory-first used {runs_b - runs_a} MORE SUMO runs than the full search (failed verifications add runs).")
    if sec_b < sec_a:
        notes.append(f"Total decision time fell by {summary['time_saved_pct']}% ({sec_a:.0f}s -> {sec_b:.0f}s).")
    else:
        notes.append(f"Total decision time did not improve ({sec_a:.0f}s -> {sec_b:.0f}s).")
    if less_eff:
        notes.append(f"In {len(less_eff)} of {n} scenarios the memory-first choice was more than 1 percentage point less effective than the full search.")
    if summary["verification_failures"]:
        notes.append(f"{summary['verification_failures']} retrieved plan(s) failed verification in SUMO and were discarded.")
    if summary["break_even_decisions"] is None:
        notes.append("Warm-up cost is never recovered at the measured saving rate.")
    else:
        notes.append(f"Populating the memory cost {warmup['sumo_runs']} SUMO runs; it pays back after about {summary['break_even_decisions']} decisions at the measured saving.")
    notes.append("Results come from one machine, one memory warm-up and a small scenario set; they are indicative, not statistically conclusive.")
    summary["notes"] = notes
    return summary


def run_benchmark(
    net: NetworkModel,
    forecaster: ForecastService,
    *,
    n_warmup: int = 8,
    n_eval: int = 12,
    seed_base: int = BENCHMARK_SEED_BASE,
    include_rerouting: bool = False,
    settings: Settings | None = None,
    work_dir: Path | None = None,
    progress: Callable[[float, str], None] | None = None,
    stop_event: threading.Event | None = None,
    keep_work_dir: bool = False,
) -> dict:
    s = settings or get_settings()
    if seed_base < BENCHMARK_SEED_BASE:
        raise DataValidationError(f"seed_base must be >= {BENCHMARK_SEED_BASE} (lower seeds are used for training data)")
    bench_id = uuid.uuid4().hex[:10]
    work = Path(work_dir or (s.data_dir / "benchmarks" / f"bench_{bench_id}"))
    work.mkdir(parents=True, exist_ok=True)
    db = Database(f"sqlite:///{(work / 'bench.db').as_posix()}")
    memory = ExperienceMemory(db, work / "faiss", net)
    engine = DecisionEngine(net, SumoRunner(net, s), forecaster, memory, None, s)
    warm = make_scenarios(n_warmup, seed_base, s.scenario_duration_s, rng_seed=seed_base)
    evals = make_scenarios(n_eval, seed_base + 1000, s.scenario_duration_s, rng_seed=seed_base + 1)
    total = n_warmup + 2 * n_eval
    done = 0

    def tick(msg: str) -> None:
        nonlocal done
        done += 1
        if progress:
            progress(min(0.99, done / total), msg)

    try:
        warm_runs, warm_s = 0, 0.0
        for i, sc in enumerate(warm):
            r = engine.decide(sc, use_memory=False, store=True, include_rerouting=include_rerouting,
                              provenance="benchmark_warmup", stop_event=stop_event, update_twin=False)
            warm_runs += r["cost"]["sumo_runs"]
            warm_s += r["cost"]["decision_seconds"]
            tick(f"warm-up {i + 1}/{n_warmup}")
        warmup = {"scenarios": n_warmup, "sumo_runs": warm_runs, "seconds": round(warm_s, 2),
                  "experiences_stored": memory.count()}
        rows: list[dict] = []
        for i, sc in enumerate(evals):
            ra = engine.decide(sc, use_memory=False, store=False, include_rerouting=include_rerouting,
                               stop_event=stop_event, update_twin=False)
            tick(f"A {i + 1}/{n_eval}")
            rb = engine.decide(sc, use_memory=True, store=True, include_rerouting=include_rerouting,
                               provenance="benchmark_b", stop_event=stop_event, update_twin=False)
            tick(f"B {i + 1}/{n_eval}")
            rows.append({"scenario": {**sc.to_dict(), "scenario_id": sc.scenario_id}, "A": _digest(ra), "B": _digest(rb)})
        st = check_sumo()
        result = {
            "id": bench_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "config": {
                "n_warmup": n_warmup, "n_eval": n_eval, "seed_base": seed_base, "include_rerouting": include_rerouting,
                "similarity_threshold": s.memory_similarity_threshold, "demand_tolerance": s.memory_demand_tolerance,
                "min_improvement": s.memory_min_improvement, "scenario_duration_s": s.scenario_duration_s,
                "decision_time_s": s.decision_time_s, "objective": engine.objective.to_dict(),
                "candidate_workers": 1, "isolated_memory": True,
            },
            "environment": {
                "sumo_version": st.version, "model_version": forecaster.version, "python": platform.python_version(),
                "cpu_count": __import__("os").cpu_count(), "platform": platform.platform(),
            },
            "scenarios": rows,
            "summary": summarize(rows, warmup),
            "synthetic": True,
        }
        if progress:
            progress(1.0, "done")
        return result
    except SimulationCancelled:
        raise
    finally:
        db.dispose()
        if not keep_work_dir:
            shutil.rmtree(work, ignore_errors=True)
