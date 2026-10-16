"""Job bodies executed by the JobManager (prediction, simulation, evaluation, benchmark)."""
from __future__ import annotations

import numpy as np

from app.benchmark.runner import run_benchmark
from app.core.errors import ConflictError, DataValidationError, ModelNotTrainedError
from app.digital_twin.congestion import congestion_index, distribution, level_of
from app.experience_memory.features import build_state_vector
from app.interventions.models import REROUTE, SIGNAL, Intervention, validate_intervention
from app.interventions.objective import ObjectiveConfig, evaluate_candidate
from app.ml.dataset import chronological_split, impute_missing, load_dataset
from app.schemas.api import InterventionIn, ScenarioIn
from app.services.decision import DecisionEngine
from app.services.state import AppState
from app.sumo.collector import F_SPEED
from app.sumo.environment import require_sumo
from app.sumo.scenario import ScenarioConfig


def scenario_cfg(st: AppState, sc: ScenarioIn) -> ScenarioConfig:
    return ScenarioConfig(sc.pattern, sc.demand_scale, sc.seed, sc.duration_s or st.settings.scenario_duration_s)


def intervention_from_in(i: InterventionIn) -> Intervention:
    if i.type == SIGNAL:
        return Intervention(SIGNAL, i.junction_id, {int(k): float(v) for k, v in (i.greens or {}).items()})
    return Intervention(REROUTE, None, {"share": i.share, "period_s": i.period_s})


def engine(st: AppState) -> DecisionEngine:
    if st.forecaster is None:
        raise ModelNotTrainedError(st.forecaster_error or "No trained GNN model.", hint="Run `python scripts/train_gnn.py`, then POST /api/v1/models/reload.")
    return DecisionEngine(st.net, st.runner, st.forecaster, st.memory, st.twin, st.settings, limits=st.limits)


def prediction_task(st: AppState, body):
    sc = scenario_cfg(st, body.scenario)

    def run(progress, stop):
        if body.mode == "sumo":
            require_sumo()
            eng = engine(st)
            base, ctx = eng.observe_and_forecast(sc, stop_event=stop, progress=progress)
            return {
                "source": "sumo_simulation", "synthetic": True, "scenario": sc.to_dict(), "run_id": base.run_id,
                "sim_runtime_s": round(base.runtime_s, 2), "horizon_s": st.forecaster.horizon * st.forecaster.interval_s,
                "decision_time_s": ctx["decision_time_s"], "model_version": st.forecaster.version,
                "distribution_current": distribution([level_of(float(x)) for x in ctx["cur_ci"]]),
                "distribution_predicted": distribution([level_of(float(x)) for x in ctx["pred_ci"]]),
                "verification": ctx["verification"], "inference_s": round(ctx["inference_s"], 4),
            }
        # replay: recorded synthetic SUMO data, no live simulation, clearly labelled
        fc = st.forecaster
        if fc is None:
            raise ModelNotTrainedError(st.forecaster_error or "No trained GNN model.")
        ds = load_dataset(st.settings.dataset_dir)
        if ds.meta.get("net_hash") != st.net.net_hash:
            raise ConflictError("Recorded dataset belongs to a different network.")
        obs = impute_missing(ds.obs, np.array([e.speed for e in st.net.edges]))
        _, _, te = chronological_split(obs.shape[0])
        idx = te.start + ((body.replay_index if body.replay_index is not None else body.scenario.seed) % (te.stop - te.start))
        k = st.settings.decision_time_s // fc.interval_s - 1
        times = [(i + 1) * fc.interval_s for i in range(obs.shape[1])]
        st.twin.sync_observations(times, obs[idx], source="dataset_replay", scenario=ds.scenarios[idx], up_to=k)
        win = st.twin.latest_window()
        pred = fc.predict(win)
        st.twin.set_prediction(pred, horizon_s=fc.horizon * fc.interval_s, model_version=fc.version, source="gnn")
        free = np.array([e.speed for e in st.net.edges])
        real = congestion_index(obs[idx][k + fc.horizon][:, F_SPEED], free)
        cur = congestion_index(obs[idx][k][:, F_SPEED], free)
        ver = {"mae": float(np.mean(np.abs(pred - real))), "persistence_mae": float(np.mean(np.abs(cur - real))),
               "note": "recorded held-out run (test split)"}
        st.twin.set_verification(ver)
        return {"source": "dataset_replay", "synthetic": True, "scenario": ds.scenarios[idx], "replay_run_index": int(idx),
                "horizon_s": fc.horizon * fc.interval_s, "model_version": fc.version, "verification": ver,
                "distribution_current": distribution([level_of(float(x)) for x in cur]),
                "distribution_predicted": distribution([level_of(float(x)) for x in pred])}

    return run


def simulation_task(st: AppState, body):
    sc = scenario_cfg(st, body.scenario)
    t_d = st.settings.decision_time_s
    activate = body.activate_at_s if body.activate_at_s is not None else float(t_d)

    def run(progress, stop):
        require_sumo()
        iv = intervention_from_in(body.intervention) if body.intervention else None
        if iv:
            validate_intervention(st.net, iv, st.limits)
        base = st.runner.run(sc, None, metrics_from_s=activate, interval_s=st.settings.interval_s,
                             stop_event=stop, progress=lambda f: progress(f * (0.5 if iv else 1.0), "baseline"))
        out = {"source": "sumo_simulation", "synthetic": True, "scenario": sc.to_dict(), "activate_at_s": activate,
               "baseline": base.summary(), "intervention_result": None, "comparison": None}
        if iv:
            res = st.runner.run(sc, iv, activate_at_s=activate, metrics_from_s=activate, collect_observations=False,
                                stop_event=stop, progress=lambda f: progress(0.5 + f * 0.5, "intervention"))
            target = iv.junction_id or max(base.junction_queues, key=base.junction_queues.get)
            nb = [j for j in st.net.neighbors(target) if j in st.net.tls_ids]
            out["intervention_result"] = res.summary()
            out["comparison"] = {
                "target_junction": target,
                **evaluate_candidate(ObjectiveConfig(min_improvement=st.settings.memory_min_improvement),
                                     base.metrics, base.junction_queues, res.metrics, res.junction_queues, target, nb),
            }
        if body.update_twin and base.observations.shape[0]:
            st.twin.sync_observations(base.obs_times, base.observations, source="sumo_simulation",
                                      scenario=sc.to_dict(), tls_states=base.tls_states, tls_programs=base.tls_programs,
                                      run_id=base.run_id)
        return out

    return run


def evaluation_task(st: AppState, body):
    sc = scenario_cfg(st, body.scenario)

    def run(progress, stop):
        require_sumo()
        return engine(st).decide(
            sc, junction_id=body.junction_id, use_memory=body.use_memory, include_rerouting=body.include_rerouting,
            store=body.store_experience, provenance="decision_api", stop_event=stop, progress=progress,
        )

    return run


def benchmark_task(st: AppState, body):
    def run(progress, stop):
        require_sumo()
        if st.forecaster is None:
            raise ModelNotTrainedError(st.forecaster_error or "No trained GNN model.")
        res = run_benchmark(st.net, st.forecaster, warmup=body.warmup, evaluation=body.evaluation, seed=body.seed,
                            fixed_junction=body.fixed_junction, settings=st.settings, runner=st.runner,
                            stop_event=stop, progress=progress)
        from app.models.db import BenchmarkRow
        from app.core.serialization import to_jsonable

        res = to_jsonable(res)
        with st.db.session() as s:
            s.add(BenchmarkRow(id=res["id"], config=res["config"], result=res))
        return {"benchmark_id": res["id"], "summary": res["summary"]}

    return run


def state_vector_from_twin(st: AppState, junction_id: str | None):
    tw = st.twin
    snap = tw.snapshot()
    if not snap["available"] or tw.prediction is None:
        raise ConflictError("The digital twin has no forecast yet.", hint="POST /api/v1/predictions/run first.")
    from app.sumo.collector import F_HALT

    cur = tw.current_ci()
    pred = np.array(tw.prediction["pred_ci"])
    vec = build_state_vector(st.net, cur, pred, tw.current[:, F_HALT])
    by_j = {j: float(np.mean([pred[st.net.edge_index[e]] for e in st.net.incoming_edges(j)])) for j in st.net.tls_ids}
    target = junction_id or max(sorted(by_j), key=lambda j: by_j[j])
    if target not in by_j:
        raise DataValidationError(f"'{target}' is not a signalised junction")
    return vec, target, snap
