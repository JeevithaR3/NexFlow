"""Decision engine: forecast -> twin update -> memory lookup -> SUMO verification / search -> choice.

This is the end-to-end flow of the system:
  baseline SUMO run (live observations) -> GNN forecast -> Digital Twin update -> feature vector ->
  Experience-Memory lookup (+ compatibility checks) -> verify a retrieved plan in SUMO (if any) ->
  otherwise simulate the candidate set -> select the best *valid* plan under the documented objective ->
  store the new experience.  Nothing here touches real traffic signals: results are recommendations.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Callable

import numpy as np

from app.core.config import Settings, get_settings
from app.core.errors import DataValidationError, ModelNotTrainedError
from app.core.logging import get_logger
from app.digital_twin.congestion import congestion_index, distribution, level_of
from app.digital_twin.network import NetworkModel
from app.digital_twin.twin import DigitalTwin
from app.experience_memory.compat import QueryContext
from app.experience_memory.features import FEATURE_SCHEMA_VERSION, build_state_vector
from app.experience_memory.memory import ExperienceMemory
from app.interventions.candidates import reroute_candidates, signal_candidates
from app.interventions.models import Intervention, SignalLimits, validate_intervention
from app.interventions.objective import OBJECTIVE_VERSION, ObjectiveConfig, evaluate_candidate
from app.ml.inference import ForecastService
from app.sumo.collector import F_HALT, F_SPEED
from app.sumo.runner import RunResult, SumoRunner
from app.sumo.scenario import ScenarioConfig

log = get_logger("decision")
DISCLAIMER = "Simulated recommendation only. Nothing is applied to any real traffic signal."


class DecisionEngine:
    def __init__(
        self,
        net: NetworkModel,
        runner: SumoRunner,
        forecaster: ForecastService | None,
        memory: ExperienceMemory | None = None,
        twin: DigitalTwin | None = None,
        settings: Settings | None = None,
        objective: ObjectiveConfig | None = None,
        limits: SignalLimits | None = None,
    ) -> None:
        self.net, self.runner, self.forecaster, self.memory, self.twin = net, runner, forecaster, memory, twin
        self.s = settings or get_settings()
        self.objective = objective or ObjectiveConfig(min_improvement=self.s.memory_min_improvement)
        self.limits = limits or SignalLimits()
        self.free_flow = np.array([e.speed for e in net.edges])

    # ---- phase 1: live observation + forecast ----------------------------------------------
    def observe_and_forecast(
        self, sc: ScenarioConfig, *, stop_event: threading.Event | None = None, update_twin: bool = True,
        progress: Callable[[float, str], None] | None = None,
    ) -> tuple[RunResult, dict]:
        if self.forecaster is None:
            raise ModelNotTrainedError("No trained GNN checkpoint is loaded.", hint="Run `python scripts/train_gnn.py`.")
        fc = self.forecaster
        interval = fc.interval_s
        t_d = self.s.decision_time_s
        if t_d % interval != 0:
            raise DataValidationError("decision_time_s must be a multiple of the aggregation interval")
        k = t_d // interval - 1
        if k - fc.window + 1 < 0 or t_d >= sc.duration_s:
            raise DataValidationError("Scenario too short for the configured forecast window / decision time")
        base = self.runner.run(
            sc, None, activate_at_s=0, metrics_from_s=t_d, collect_observations=True, interval_s=interval,
            stop_event=stop_event, progress=(lambda f: progress(f, "baseline simulation")) if progress else None,
        )
        obs = base.observations
        window = obs[k - fc.window + 1 : k + 1]
        cur_ci = congestion_index(obs[k][:, F_SPEED], self.free_flow)
        t0 = time.perf_counter()
        pred = fc.predict(window)
        infer_s = time.perf_counter() - t0
        verification = None
        if k + fc.horizon < obs.shape[0]:
            real = congestion_index(obs[k + fc.horizon][:, F_SPEED], self.free_flow)
            verification = {
                "target_sim_time_s": float(base.obs_times[k + fc.horizon]),
                "mae": float(np.mean(np.abs(pred - real))),
                "persistence_mae": float(np.mean(np.abs(cur_ci - real))),
                "level_accuracy": float(np.mean([level_of(a) == level_of(b) for a, b in zip(pred, real)])),
                "note": "single-scenario check: the simulation was continued past the forecast time",
            }
        if self.twin is not None and update_twin:
            self.twin.sync_observations(
                base.obs_times, obs, source="sumo_simulation", scenario=sc.to_dict(), tls_states=base.tls_states,
                tls_programs=base.tls_programs, run_id=base.run_id, up_to=k,
            )
            self.twin.set_prediction(pred, horizon_s=fc.horizon * interval, model_version=fc.version, source="gnn")
            if verification:
                self.twin.set_verification(verification)
        ctx = {
            "k": k, "cur_ci": cur_ci, "pred_ci": pred, "halting": obs[k][:, F_HALT], "verification": verification,
            "inference_s": infer_s, "decision_time_s": t_d,
        }
        return base, ctx

    # ---- phase 2: decision --------------------------------------------------------------------
    def decide(
        self,
        sc: ScenarioConfig,
        *,
        junction_id: str | None = None,
        use_memory: bool = True,
        include_rerouting: bool = False,
        store: bool = True,
        provenance: str = "decision_api",
        stop_event: threading.Event | None = None,
        progress: Callable[[float, str], None] | None = None,
        update_twin: bool = True,
    ) -> dict:
        t_start = time.perf_counter()
        fc = self.forecaster
        t_d = self.s.decision_time_s
        runs: list[dict] = []
        base, st = self.observe_and_forecast(
            sc, stop_event=stop_event, update_twin=update_twin,
            progress=(lambda f, m: progress(f * 0.1, m)) if progress else None,
        )
        runs.append({"role": "baseline", "run_id": base.run_id, "runtime_s": round(base.runtime_s, 3)})

        # target junction: highest mean predicted CI over its incoming segments (documented rule)
        pred_by_junction = {
            j: float(np.mean([st["pred_ci"][self.net.edge_index[e]] for e in self.net.incoming_edges(j)]))
            for j in self.net.tls_ids
        }
        if junction_id is None:
            target = max(sorted(pred_by_junction), key=lambda j: pred_by_junction[j])
            target_rule = "junction with the highest predicted congestion index on its incoming roads"
        else:
            if junction_id not in self.net.tls_ids:
                raise DataValidationError(f"'{junction_id}' is not a signalised junction of this network")
            target, target_rule = junction_id, "selected by the user"

        vector = build_state_vector(self.net, st["cur_ci"], st["pred_ci"], st["halting"])
        neighbors = [j for j in self.net.neighbors(target) if j in self.net.tls_ids]
        candidates = signal_candidates(self.net, target, self.limits)
        if include_rerouting:
            candidates += reroute_candidates()
        planned = 1 + len(candidates)
        done_runs = 1

        def tick(msg: str) -> None:
            if progress:
                progress(min(0.99, done_runs / planned), msg)

        evaluated: dict[str, dict] = {}

        def evaluate(iv: Intervention, origin: str) -> dict:
            nonlocal done_runs
            validate_intervention(self.net, iv, self.limits)
            res = self.runner.run(
                sc, iv, activate_at_s=t_d, metrics_from_s=t_d, collect_observations=False, stop_event=stop_event
            )
            done_runs += 1
            ev = evaluate_candidate(
                self.objective, base.metrics, base.junction_queues, res.metrics, res.junction_queues, target, neighbors
            )
            rec = {
                "intervention": iv.to_dict(), "origin": origin, "metrics": res.metrics,
                "junction_queues": res.junction_queues, "runtime_s": round(res.runtime_s, 3), **ev,
            }
            evaluated[iv.key()] = rec
            runs.append({"role": f"candidate:{origin}", "run_id": res.run_id, "runtime_s": round(res.runtime_s, 3)})
            tick(f"evaluated {iv.label or iv.describe()}")
            return rec

        # ---- Experience-Memory lookup --------------------------------------------------------
        mem_info: dict = {"enabled": bool(use_memory and self.memory is not None), "outcome": "disabled", "matches": [],
                          "lookup_s": 0.0, "threshold": self.s.memory_similarity_threshold}
        chosen: dict | None = None
        source = "simulated"
        reused_id: str | None = None
        if mem_info["enabled"]:
            ctx = QueryContext(
                network_id=self.net.net_hash, tls_hash=self.net.tls_hash, feature_schema=FEATURE_SCHEMA_VERSION,
                objective_version=OBJECTIVE_VERSION, model_version=fc.version, horizon_s=fc.horizon * fc.interval_s,
                interval_s=fc.interval_s, step_length_s=sc.step_length_s, sim_duration_s=sc.duration_s,
                decision_time_s=t_d, demand_scale=sc.demand_scale, junction_id=target,
            )
            t0 = time.perf_counter()
            matches = self.memory.search(
                vector, ctx, k=self.s.memory_top_k, threshold=self.s.memory_similarity_threshold,
                demand_tolerance=self.s.memory_demand_tolerance,
            )
            mem_info["lookup_s"] = time.perf_counter() - t0
            mem_info["matches"] = [m.to_dict() for m in matches]
            if self.memory.count() == 0:
                mem_info["outcome"] = "empty"
            accepted = [m for m in matches if m.accepted]
            if not accepted:
                if mem_info["outcome"] != "empty":
                    mem_info["outcome"] = "miss"
            else:
                top = accepted[0]
                iv = Intervention.from_dict(top.experience["intervention"])
                rec = evaluate(iv, "memory")
                rec["memory_experience_id"] = top.experience["experience_id"]
                rec["similarity"] = round(top.similarity, 4)
                ok = rec["valid"] and rec["improvement"] >= self.objective.min_improvement
                self.memory.mark_reuse(top.experience["experience_id"], verified=ok)
                if ok:
                    chosen, source, reused_id = rec, "memory_verified", top.experience["experience_id"]
                    mem_info["outcome"] = "reused"
                else:
                    mem_info["outcome"] = "failed_verification"
                    why = rec["violations"] or [f"improvement {rec['improvement'] * 100:.1f}% below the required "
                                                f"{self.objective.min_improvement * 100:.1f}%"]
                    mem_info["verification_failure"] = {"experience_id": top.experience["experience_id"], "reasons": why}
                    top.reasons.append("verification in SUMO failed: " + "; ".join(why))
                    mem_info["matches"] = [m.to_dict() for m in matches]
                    for m in mem_info["matches"]:
                        if m["experience_id"] == top.experience["experience_id"]:
                            m["verification"] = "failed"
        # ---- candidate search when memory could not provide a verified plan -----------------
        stored_id = None
        if chosen is None:
            for iv in candidates:
                if iv.key() in evaluated:
                    continue
                evaluate(iv, "search")
            valid = [r for r in evaluated.values() if r["valid"]]
            pool = valid if valid else list(evaluated.values())
            best = max(pool, key=lambda r: r["improvement"]) if pool else None
            if best and best["valid"] and best["improvement"] >= self.objective.min_improvement:
                chosen = best
            if store and self.memory is not None and best is not None:
                improved = bool(best["valid"] and best["improvement"] >= self.objective.min_improvement)
                stored_id = self.memory.add(
                    {
                        "network_id": self.net.net_hash, "tls_hash": self.net.tls_hash, "scenario_id": sc.scenario_id,
                        "feature_schema": FEATURE_SCHEMA_VERSION, "objective_version": OBJECTIVE_VERSION,
                        "model_version": fc.version, "horizon_s": fc.horizon * fc.interval_s, "interval_s": fc.interval_s,
                        "step_length_s": sc.step_length_s, "sim_duration_s": sc.duration_s, "decision_time_s": t_d,
                        "demand_pattern": sc.pattern, "demand_scale": sc.demand_scale, "junction_id": target,
                        "vector": vector.tolist(), "intervention": best["intervention"],
                        "baseline_metrics": {**base.metrics, "target_junction_queue": base.junction_queues.get(target, 0.0)},
                        "result_metrics": {**best["metrics"], "target_junction_queue": best["junction_queues"].get(target, 0.0)},
                        "improvement": float(best["improvement"]), "improved": improved,
                        "search_runtime_s": float(sum(r["runtime_s"] for r in runs)), "runs_used": len(runs),
                        "provenance": provenance,
                        "config": {"limits": self.limits.to_dict(), "objective": self.objective.to_dict(),
                                   "candidates": len(candidates)},
                    }
                )
        decision_s = time.perf_counter() - t_start
        sumo_s = float(sum(r["runtime_s"] for r in runs))
        cands = list(evaluated.values())
        result = {
            "decision_id": uuid.uuid4().hex[:12],
            "disclaimer": DISCLAIMER,
            "scenario": sc.to_dict(),
            "source": source if chosen else "no_change",
            "recommendation": "apply" if chosen else "keep_current_plan",
            "evidence": "validated by SUMO simulation of this scenario",
            "target_junction": target,
            "target_rule": target_rule,
            "predicted_congestion_by_junction": {k: round(v, 4) for k, v in pred_by_junction.items()},
            "prediction": {
                "model_version": fc.version, "horizon_s": fc.horizon * fc.interval_s, "decision_time_s": t_d,
                "distribution_current": distribution([level_of(float(x)) for x in st["cur_ci"]]),
                "distribution_predicted": distribution([level_of(float(x)) for x in st["pred_ci"]]),
                "verification": st["verification"],
            },
            "baseline": {"metrics": base.metrics, "junction_queues": base.junction_queues},
            "candidates": cands,
            "selected": chosen,
            "memory": mem_info,
            "experience_id": stored_id or reused_id,
            "experience_stored": stored_id is not None,
            "objective": self.objective.to_dict(),
            "cost": {
                "sumo_runs": len(runs), "sumo_seconds": round(sumo_s, 3), "decision_seconds": round(decision_s, 3),
                "lookup_seconds": round(mem_info["lookup_s"], 5), "runs": runs,
            },
        }
        if self.twin is not None and update_twin:
            if chosen:
                self.twin.set_intervention(
                    chosen["intervention"], "recommended_simulated",
                    {"source": result["source"], "improvement": chosen["improvement"], "experience_id": result["experience_id"]},
                )
            else:
                self.twin.set_intervention(None, "no_beneficial_change_found")
        if progress:
            progress(1.0, "done")
        return result
