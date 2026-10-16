"""Versioned REST API (/api/v1)."""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app import __version__
from app.benchmark.runner import run_benchmark
from app.core.errors import ConflictError, DataValidationError, ModelNotTrainedError, NotFoundError
from app.digital_twin.congestion import COLORS, HIGH_MIN, LOW_MAX, distribution, level_of
from app.experience_memory.compat import QueryContext
from app.experience_memory.features import FEATURE_SCHEMA_VERSION, build_state_vector
from app.interventions.candidates import reroute_candidates, signal_candidates
from app.interventions.models import SIGNAL, Intervention, validate_intervention
from app.interventions.objective import OBJECTIVE_VERSION, evaluate_candidate
from app.interventions.routing import propose_route
from app.ml.dataset import load_dataset
from app.models.db import BenchmarkRow
from app.schemas.api import BenchmarkRunIn, EvaluateIn, PredictionRunIn, SimulationRunIn
from app.services.container import AppState
from app.sumo.collector import F_HALT, F_SPEED
from app.sumo.environment import check_sumo, require_sumo
from app.sumo.scenario import ScenarioConfig

router = APIRouter(prefix="/api/v1")


def state(request: Request) -> AppState:
    return request.app.state.nexflow


def _sc(s: AppState, sc_in) -> ScenarioConfig:
    return ScenarioConfig(sc_in.pattern, sc_in.demand_scale, sc_in.seed, s.s.scenario_duration_s)


def _accepted(job_id: str) -> JSONResponse:
    return JSONResponse(status_code=202, content={"run_id": job_id, "status": "queued", "poll": f"/api/v1/runs/{job_id}"})


# ---- health / network ------------------------------------------------------------------
@router.get("/health")
def health(s: AppState = Depends(state)):
    sumo = check_sumo()
    fc = s.forecaster if s.net else None
    ok = sumo.available and s.net is not None and fc is not None
    return {
        "status": "ok" if ok else "degraded", "version": __version__,
        "sumo": sumo.to_dict(),
        "network": {"loaded": s.net is not None, "error": s.net_error.message if s.net_error else None,
                    "edges": s.net.n_edges if s.net else 0, "signalised_junctions": len(s.net.tls_ids) if s.net else 0,
                    "net_hash": s.net.net_hash if s.net else None},
        "model": {"loaded": fc is not None, "version": fc.version if fc else None,
                  "horizon_s": fc.horizon * fc.interval_s if fc else None,
                  "error": s.fc_error.message if s.fc_error else None, "hint": s.fc_error.hint if s.fc_error else None},
        "memory": s.memory.stats() if s.memory else None,
        "twin_available": bool(s.twin and s.twin.current is not None),
        "demo_data_mode": "dataset_replay (explicitly labelled synthetic replay; interventions always need SUMO)",
    }


@router.get("/network")
def network(s: AppState = Depends(state)):
    net = s.require_net()
    lat0, lon0 = s.s.map_origin_lat, s.s.map_origin_lon
    return {
        "network_id": net.net_hash, "synthetic": True,
        "notice": "Synthetic SUMO grid placed at a configurable reference point. Its roads do not correspond to real OpenStreetMap streets.",
        "origin": {"lat": lat0, "lon": lon0},
        "congestion": {"low_max": LOW_MAX, "high_min": HIGH_MIN, "colors": COLORS},
        "edges": [
            {"id": e.id, "from": e.from_node, "to": e.to_node, "length_m": e.length, "speed_ms": e.speed,
             "lanes": e.lanes, "shape": net.edge_latlon_shape(e.id, lat0, lon0)}
            for e in net.edges
        ],
        "junctions": [
            {"id": j.id, "lat": net.to_latlon(j.x, j.y, lat0, lon0)[0], "lon": net.to_latlon(j.x, j.y, lat0, lon0)[1],
             "type": j.type, "has_tls": j.has_tls, "neighbors": net.neighbors(j.id),
             "tls": net.tls_summary(j.id) if j.has_tls and j.id in net.tls_programs else None}
            for j in net.junctions
        ],
        "signal_limits": s.limits.to_dict(),
    }


# ---- traffic -----------------------------------------------------------------------------
@router.get("/traffic/current")
def traffic_current(s: AppState = Depends(state)):
    snap = s.twin.snapshot() if s.twin else {"available": False, "reason": "Network not loaded"}
    if not snap.get("available"):
        return snap
    keep = ("id", "flow_vph", "speed_ms", "occupancy_pct", "vehicle_count", "halting_count", "ci", "level")
    return {**{k: v for k, v in snap.items() if k != "edges"},
            "edges": [{k: e[k] for k in keep} for e in snap["edges"]]}


@router.get("/traffic/predictions")
def traffic_predictions(s: AppState = Depends(state)):
    snap = s.twin.snapshot() if s.twin else {"available": False}
    if not snap.get("available") or not snap.get("prediction"):
        return {"available": False, "reason": "No prediction yet. Start a prediction run first."}
    return {
        "available": True, "source": snap["source"], "synthetic": True, "prediction": snap["prediction"],
        "sim_time_s": snap["sim_time_s"], "distribution": snap["distribution"],
        "edges": [{k: e[k] for k in ("id", "ci", "level", "pred_ci", "pred_level", "delta_ci")} for e in snap["edges"]],
        "intervention": snap["intervention"], "scenario": snap["scenario"],
    }


# ---- runs ----------------------------------------------------------------------------------
@router.post("/predictions/run", status_code=202)
def predictions_run(body: PredictionRunIn, s: AppState = Depends(state)):
    net = s.require_net()
    if s.forecaster is None:
        raise s.fc_error or ModelNotTrainedError("No trained model")
    sc = _sc(s, body.scenario)
    if body.mode == "sumo":
        require_sumo()

    def job(ctx):
        eng = s.engine()
        if body.mode == "sumo":
            base, st = eng.observe_and_forecast(sc, stop_event=ctx.stop_event, progress=ctx.progress)
            return {"mode": "sumo", "source": "sumo_simulation", "scenario": sc.to_dict(), "run_id": base.run_id,
                    "verification": st["verification"], "sim_runtime_s": round(base.runtime_s, 2),
                    "model_version": s.forecaster.version}
        ds = load_dataset(s.s.dataset_dir)
        fc = s.forecaster
        obs, k = ds.obs[-1], s.s.decision_time_s // fc.interval_s - 1
        times = [float((i + 1) * fc.interval_s) for i in range(obs.shape[0])]
        s.twin.sync_observations(times, obs, source="dataset_replay", scenario={**ds.scenarios[-1], "replayed": True},
                                 up_to=k, edge_ids=list(net.edge_ids))
        pred = fc.predict(obs[k - fc.window + 1 : k + 1])
        s.twin.set_prediction(pred, horizon_s=fc.horizon * fc.interval_s, model_version=fc.version, source="gnn")
        return {"mode": "dataset_replay", "source": "dataset_replay",
                "label": "Replay of a recorded SYNTHETIC simulation from the dataset (not a live SUMO run)",
                "scenario": ds.scenarios[-1], "model_version": fc.version}

    return _accepted(s.jobs.submit("prediction", {"scenario": sc.to_dict(), "mode": body.mode}, job))


@router.post("/simulations/run", status_code=202)
def simulations_run(body: SimulationRunIn, s: AppState = Depends(state)):
    net = s.require_net()
    require_sumo()
    sc = _sc(s, body.scenario)
    iv = None
    if body.intervention:
        b = body.intervention
        if b.type == SIGNAL:
            if not b.green_s:
                raise DataValidationError("signal_timing needs green_s (phase index -> seconds)")
            iv = Intervention(SIGNAL, b.junction_id, {int(k): float(v) for k, v in b.green_s.items()})
        else:
            iv = Intervention("reroute", None, {"share": b.reroute_share or 0, "period_s": b.reroute_period_s or 30})
        validate_intervention(net, iv, s.limits)
    t_d = s.s.decision_time_s

    def job(ctx):
        base = s.runner.run(sc, None, metrics_from_s=t_d, collect_observations=False, stop_event=ctx.stop_event)
        ctx.progress(0.5, "baseline done")
        out = {"source": "simulated", "scenario": sc.to_dict(), "baseline": base.summary(),
               "disclaimer": "Simulated only; no real signal is controlled."}
        if iv:
            res = s.runner.run(sc, iv, activate_at_s=t_d, metrics_from_s=t_d, collect_observations=False, stop_event=ctx.stop_event)
            target = iv.junction_id or max(base.junction_queues, key=base.junction_queues.get)
            from app.interventions.objective import ObjectiveConfig
            ev = evaluate_candidate(ObjectiveConfig(min_improvement=s.s.memory_min_improvement), base.metrics,
                                    base.junction_queues, res.metrics, res.junction_queues, target,
                                    [j for j in net.neighbors(target) if j in net.tls_ids])
            out.update({"intervention": res.summary(), "evaluation": ev, "target_junction": target})
        return out

    return _accepted(s.jobs.submit("simulation", {"scenario": sc.to_dict(), "intervention": iv.to_dict() if iv else None}, job))


@router.post("/interventions/evaluate", status_code=202)
def interventions_evaluate(body: EvaluateIn, s: AppState = Depends(state)):
    s.require_net()
    require_sumo()
    if s.forecaster is None:
        raise s.fc_error or ModelNotTrainedError("No trained model")
    sc = _sc(s, body.scenario)

    def job(ctx):
        return s.engine().decide(sc, junction_id=body.junction_id, use_memory=body.use_memory,
                                 include_rerouting=body.include_rerouting, store=body.store_experience,
                                 stop_event=ctx.stop_event, progress=ctx.progress)

    return _accepted(s.jobs.submit("decision", {"scenario": sc.to_dict(), **body.model_dump(exclude={"scenario"})}, job))


@router.get("/interventions/candidates")
def candidates(junction_id: str, s: AppState = Depends(state)):
    net = s.require_net()
    if junction_id not in net.tls_ids:
        raise NotFoundError(f"'{junction_id}' is not a signalised junction")
    return {"junction_id": junction_id, "limits": s.limits.to_dict(), "green_phases": net.tls_summary(junction_id)["green_phases"],
            "default_plan": net.tls_programs[junction_id],
            "signal_candidates": [c.to_dict() for c in signal_candidates(net, junction_id, s.limits)],
            "reroute_candidates": [c.to_dict() for c in reroute_candidates()]}


@router.get("/routes/alternative")
def alternative_route(from_edge: str, to_edge: str, s: AppState = Depends(state)):
    net = s.require_net()
    pred = np.array(s.twin.prediction["pred_ci"]) if s.twin and s.twin.prediction else None
    r = propose_route(net, from_edge, to_edge, pred)
    lat0, lon0 = s.s.map_origin_lat, s.s.map_origin_lon
    r["alternative_shape"] = [net.edge_latlon_shape(e, lat0, lon0) for e in r["alternative_route"]]
    r["default_shape"] = [net.edge_latlon_shape(e, lat0, lon0) for e in r["default_route"]]
    r["estimated"] = True
    return r


@router.get("/runs")
def list_runs(limit: int = Query(20, ge=1, le=100), kind: str | None = None, s: AppState = Depends(state)):
    return {"runs": s.jobs.list(limit, kind)}


@router.get("/runs/{run_id}")
def get_run(run_id: str, s: AppState = Depends(state)):
    r = s.jobs.get(run_id)
    if not r:
        raise NotFoundError(f"Run '{run_id}' not found")
    return r


@router.get("/simulations/{run_id}")
def get_simulation(run_id: str, s: AppState = Depends(state)):
    return get_run(run_id, s)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, s: AppState = Depends(state)):
    if not s.jobs.get(run_id):
        raise NotFoundError(f"Run '{run_id}' not found")
    if not s.jobs.cancel(run_id):
        raise ConflictError("Run is not active")
    return {"run_id": run_id, "cancel_requested": True}


# ---- experience memory -----------------------------------------------------------------------
@router.get("/experiences")
def experiences(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), s: AppState = Depends(state)):
    s.require_net()
    return {"stats": s.memory.stats(), "experiences": s.memory.list(limit, offset),
            "config": {"similarity_threshold": s.s.memory_similarity_threshold, "demand_tolerance": s.s.memory_demand_tolerance,
                       "top_k": s.s.memory_top_k, "feature_schema": FEATURE_SCHEMA_VERSION}}


@router.get("/experiences/search")
def experiences_search(
    source: str = Query("current", pattern="^(current|experience)$"), experience_id: str | None = None,
    junction_id: str | None = None, k: int = Query(5, ge=1, le=20), threshold: float | None = Query(None, ge=0, le=1),
    s: AppState = Depends(state),
):
    net = s.require_net()
    fc = s.forecaster
    thr = s.s.memory_similarity_threshold if threshold is None else threshold
    if source == "experience":
        row = s.memory.get(experience_id or "", include_vector=True)
        if not row:
            raise NotFoundError("experience_id not found")
        vec = np.array(row["vector"], dtype=np.float32)
        ctx = QueryContext(row["network_id"], row["tls_hash"], row["feature_schema"], row["objective_version"],
                           row["model_version"], row["horizon_s"], row["interval_s"], row["step_length_s"],
                           row["sim_duration_s"], row["decision_time_s"], row["demand_scale"], junction_id or row["junction_id"])
    else:
        if fc is None:
            raise s.fc_error or ModelNotTrainedError("No trained model")
        if not (s.twin and s.twin.prediction):
            raise ConflictError("No current prediction in the digital twin.", hint="Run a prediction first (Overview page).")
        pred, cur = np.array(s.twin.prediction["pred_ci"]), s.twin.current_ci()
        vec = build_state_vector(net, cur, pred, s.twin.current[:, F_HALT])
        target = junction_id or max(sorted(net.tls_ids), key=lambda j: float(np.mean([pred[net.edge_index[e]] for e in net.incoming_edges(j)])))
        sc = s.twin.scenario or {}
        ctx = QueryContext(net.net_hash, net.tls_hash, FEATURE_SCHEMA_VERSION, OBJECTIVE_VERSION, fc.version,
                           fc.horizon * fc.interval_s, fc.interval_s, float(sc.get("step_length_s", 1.0)),
                           int(sc.get("duration_s", s.s.scenario_duration_s)), s.s.decision_time_s,
                           float(sc.get("demand_scale", 1.0)), target)
    matches = s.memory.search(vec, ctx, k=k + (1 if source == "experience" else 0), threshold=thr,
                              demand_tolerance=s.s.memory_demand_tolerance)
    if source == "experience":
        matches = [m for m in matches if m.experience["experience_id"] != experience_id]
    return {"query": {"source": source, "junction_id": ctx.junction_id, "threshold": thr, "k": k},
            "matches": [m.to_dict() for m in matches],
            "note": "Similarity alone does not prove an intervention will work; every accepted match must still be verified in SUMO."}


@router.get("/experiences/{experience_id}")
def experience_detail(experience_id: str, s: AppState = Depends(state)):
    s.require_net()
    row = s.memory.get(experience_id)
    if not row:
        raise NotFoundError("Experience not found")
    return row


# ---- benchmarks / models --------------------------------------------------------------------------
@router.get("/benchmarks")
def benchmarks(s: AppState = Depends(state)):
    with s.db.session() as sess:
        rows = sess.scalars(select(BenchmarkRow).order_by(BenchmarkRow.created_at.desc()).limit(20)).all()
        return {"benchmarks": [{"id": r.id, "created_at": r.created_at.isoformat(), "config": r.config,
                                "summary": r.result["summary"], "environment": r.result.get("environment")} for r in rows]}


@router.get("/benchmarks/{bench_id}")
def benchmark_detail(bench_id: str, s: AppState = Depends(state)):
    with s.db.session() as sess:
        r = sess.get(BenchmarkRow, bench_id)
        if not r:
            raise NotFoundError("Benchmark not found")
        return r.result


@router.post("/benchmarks/run", status_code=202)
def benchmarks_run(body: BenchmarkRunIn, s: AppState = Depends(state)):
    net = s.require_net()
    require_sumo()
    if s.forecaster is None:
        raise s.fc_error or ModelNotTrainedError("No trained model")

    def job(ctx):
        res = run_benchmark(net, s.forecaster, n_warmup=body.n_warmup, n_eval=body.n_eval, seed_base=body.seed_base,
                            include_rerouting=body.include_rerouting, settings=s.s, progress=ctx.progress, stop_event=ctx.stop_event)
        with s.db.session() as sess:
            sess.add(BenchmarkRow(id=res["id"], config=res["config"], result=res))
        return {"benchmark_id": res["id"], "summary": res["summary"]}

    return _accepted(s.jobs.submit("benchmark", body.model_dump(), job))


@router.get("/models/evaluation")
def model_evaluation(s: AppState = Depends(state)):
    m = s.model_metrics()
    if m is None:
        return {"available": False, "reason": "No metrics yet. Train the model: python scripts/train_gnn.py"}
    return {"available": True, **m}
