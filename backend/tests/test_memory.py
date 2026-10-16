import numpy as np
import pytest

from app.experience_memory.compat import QueryContext
from app.experience_memory.faiss_store import FaissStore
from app.experience_memory.features import FEATURE_SCHEMA_VERSION, build_state_vector, feature_dim, feature_names
from app.experience_memory.memory import ExperienceMemory
from app.interventions.models import SIGNAL, Intervention, SignalLimits, validate_intervention
from app.core.errors import DataValidationError
from app.interventions.objective import OBJECTIVE_VERSION, ObjectiveConfig, evaluate_candidate
from app.models.db import Database


def record(net, vec, junction="B1", improved=True, scale=1.2, **kw):
    r = {
        "network_id": net.net_hash, "tls_hash": net.tls_hash, "scenario_id": "s", "feature_schema": FEATURE_SCHEMA_VERSION,
        "objective_version": OBJECTIVE_VERSION, "model_version": "m1", "horizon_s": 270, "interval_s": 90, "step_length_s": 1.0,
        "sim_duration_s": 1260, "decision_time_s": 540, "demand_pattern": "ew_heavy", "demand_scale": scale, "junction_id": junction,
        "vector": list(vec), "intervention": Intervention(SIGNAL, junction, {0: 25, 2: 55}).to_dict(),
        "baseline_metrics": {}, "result_metrics": {}, "improvement": 0.08 if improved else -0.02, "improved": improved,
        "search_runtime_s": 30.0, "runs_used": 9, "provenance": "test", "config": {},
    }
    r.update(kw)
    return r


def ctx(net, vec_junction="B1", scale=1.2, **kw):
    d = dict(network_id=net.net_hash, tls_hash=net.tls_hash, feature_schema=FEATURE_SCHEMA_VERSION, objective_version=OBJECTIVE_VERSION,
             model_version="m1", horizon_s=270, interval_s=90, step_length_s=1.0, sim_duration_s=1260, decision_time_s=540,
             demand_scale=scale, junction_id=vec_junction)
    d.update(kw)
    return QueryContext(**d)


@pytest.fixture()
def mem(net, tmp_path):
    db = Database(f"sqlite:///{tmp_path / 't.db'}")
    yield ExperienceMemory(db, tmp_path / "faiss", net)
    db.dispose()


def test_feature_vector_schema(net):
    n = net.n_edges
    v = build_state_vector(net, np.full(n, 0.5), np.full(n, 0.7), np.full(n, 3.0))
    assert v.shape == (feature_dim(net),) == (len(feature_names(net)),)
    assert ((v >= 0) & (v <= 1)).all()
    with pytest.raises(ValueError):
        build_state_vector(net, np.zeros(3), np.zeros(n), np.zeros(n))


def test_faiss_store_add_search_persist(tmp_path):
    s = FaissStore(tmp_path, 4, "fv1")
    s.add(1, np.array([0, 0, 0, 0])); s.add(2, np.array([1, 1, 1, 1]))
    assert s.search(np.array([0.1, 0, 0, 0]), 1)[0][0] == 1
    s2 = FaissStore(tmp_path, 4, "fv1")
    assert s2.load() and s2.ntotal == 2 and s2.ids() == {1, 2}
    assert not FaissStore(tmp_path, 5, "fv1").load()  # dimension mismatch is rejected


def test_add_search_accepts_close_compatible_match(net, mem):
    base = np.full(feature_dim(net), 0.4, np.float32)
    exp_id = mem.add(record(net, base))
    assert mem.count() == 1 and mem.stats()["index_in_sync"]
    m = mem.search(base + 0.01, ctx(net), k=3, threshold=0.9, demand_tolerance=0.25)
    assert m[0].experience["experience_id"] == exp_id and m[0].accepted and m[0].similarity > 0.95


@pytest.mark.parametrize("override,expected", [
    ({"network_id": "other"}, "different road network"),
    ({"tls_hash": "other"}, "traffic-light configuration"),
    ({"junction_id": "C1"}, "different target junction"),
    ({"horizon_s": 300}, "prediction horizon"),
    ({"model_version": "m2"}, "model version"),
    ({"demand_scale": 2.5}, "demand level differs"),
    ({"improved": False}, "did not improve"),
    ({"sim_duration_s": 900}, "duration"),
])
def test_incompatible_experiences_are_rejected_even_when_identical(net, mem, override, expected):
    v = np.full(feature_dim(net), 0.4, np.float32)
    mem.add(record(net, v, **override))
    m = mem.search(v, ctx(net), k=3, threshold=0.9, demand_tolerance=0.25)
    assert m and not m[0].accepted and any(expected in r for r in m[0].reasons)


def test_similarity_threshold_rejects_distant_state(net, mem):
    mem.add(record(net, np.full(feature_dim(net), 0.1, np.float32)))
    m = mem.search(np.full(feature_dim(net), 0.9, np.float32), ctx(net), k=3, threshold=0.9, demand_tolerance=0.25)
    assert not m[0].accepted and "below threshold" in m[0].reasons[0]


def test_index_rebuilds_from_database_when_missing(net, tmp_path):
    db = Database(f"sqlite:///{tmp_path / 't.db'}")
    m1 = ExperienceMemory(db, tmp_path / "f", net)
    m1.add(record(net, np.full(feature_dim(net), 0.3, np.float32)))
    (tmp_path / "f" / "experience.faiss").unlink()
    m2 = ExperienceMemory(db, tmp_path / "f", net)
    assert m2.store.ntotal == 1 and m2.stats()["index_in_sync"]


def test_reuse_counters(net, mem):
    eid = mem.add(record(net, np.full(feature_dim(net), 0.3, np.float32)))
    mem.mark_reuse(eid, True); mem.mark_reuse(eid, False)
    e = mem.get(eid)
    assert (e["reuse_count"], e["verified_count"], e["failed_verification_count"]) == (2, 1, 1)


def test_intervention_validation_limits(net):
    lim = SignalLimits()
    validate_intervention(net, Intervention(SIGNAL, "B1", {0: 25, 2: 55}), lim)
    for bad in (Intervention(SIGNAL, "B1", {0: 5}), Intervention(SIGNAL, "B1", {1: 30}), Intervention(SIGNAL, "ZZ", {0: 30}),
                Intervention(SIGNAL, "B1", {0: 60, 2: 60})):
        with pytest.raises(DataValidationError):
            validate_intervention(net, bad, lim)


def test_objective_baseline_scores_one_and_guardrails():
    m = {"avg_wait_s": 50, "avg_travel_time_s": 200, "queue_proxy_veh": 60, "throughput_veh": 400}
    q = {"B1": 10.0, "A1": 5.0}
    same = evaluate_candidate(ObjectiveConfig(), m, q, m, q, "B1", ["A1"])
    assert abs(same["score"] - 1.0) < 1e-9 and same["valid"]
    better = evaluate_candidate(ObjectiveConfig(), m, q, {**m, "avg_wait_s": 40}, {"B1": 6.0, "A1": 5.0}, "B1", ["A1"])
    assert better["improvement"] > 0
    spill = evaluate_candidate(ObjectiveConfig(), m, q, m, {"B1": 5.0, "A1": 12.0}, "B1", ["A1"])
    assert not spill["valid"] and "neighbouring junction A1" in spill["violations"][0]
    slow = evaluate_candidate(ObjectiveConfig(), m, q, {**m, "throughput_veh": 300}, q, "B1", ["A1"])
    assert not slow["valid"]
