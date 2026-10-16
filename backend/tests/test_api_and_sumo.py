import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.errors import SumoConfigError
from app.main import create_app
from app.sumo.collector import EdgeStep, MeasurementCollector
from app.sumo.config_check import validate_sumocfg
from app.sumo.runner import SumoRunner
from app.sumo.scenario import ScenarioConfig, build_trips


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    s = get_settings().model_copy(update={"data_dir": d, "database_url": None})
    s.ensure_dirs()
    import shutil
    shutil.copy(get_settings().dataset_dir / 'traffic_dataset.npz', s.dataset_dir / 'traffic_dataset.npz')
    with TestClient(create_app(s)) as c:
        yield c


def wait(client, rid, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/v1/runs/{rid}").json()
        if r["status"] in ("succeeded", "failed", "cancelled"):
            return r
        time.sleep(0.5)
    raise AssertionError("run timed out")


def test_health_and_network_contract(client):
    h = client.get("/api/v1/health").json()
    assert h["network"]["edges"] == 48 and "sumo" in h
    n = client.get("/api/v1/network").json()
    assert n["synthetic"] is True and len(n["edges"]) == 48 and all(len(e["shape"]) >= 2 for e in n["edges"])


def test_validation_errors_are_consistent_json(client):
    r = client.post("/api/v1/predictions/run", json={"scenario": {"pattern": "nope", "demand_scale": 99}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error" and r.json()["error"]["details"]
    assert client.get("/api/v1/runs/doesnotexist").status_code == 404
    assert client.get("/api/v1/experiences/search", params={"source": "bad"}).status_code == 422
    r = client.get("/api/v1/experiences/search", params={"source": "current"})
    assert r.status_code == 409 and "prediction" in r.json()["error"]["message"].lower()


def test_empty_state_is_not_fabricated(client):
    assert client.get("/api/v1/traffic/current").json()["available"] is False
    assert client.get("/api/v1/traffic/predictions").json()["available"] is False


def test_replay_prediction_is_labelled_and_populates_twin(client):
    r = client.post("/api/v1/predictions/run", json={"mode": "dataset_replay"})
    assert r.status_code == 202
    run = wait(client, r.json()["run_id"])
    assert run["status"] == "succeeded" and "SYNTHETIC" in run["result"]["label"]
    p = client.get("/api/v1/traffic/predictions").json()
    assert p["available"] and p["source"] == "dataset_replay" and len(p["edges"]) == 48


def test_simulation_rejects_illegal_green_time(client):
    r = client.post("/api/v1/simulations/run", json={"intervention": {"type": "signal_timing", "junction_id": "B1", "green_s": {"0": 3}}})
    assert r.status_code in (422, 503)  # 503 only when SUMO is missing (environment)


def test_alternative_route_endpoint(client):
    r = client.get("/api/v1/routes/alternative", params={"from_edge": "left1A1", "to_edge": "C1right1"})
    assert r.status_code == 200 and r.json()["estimated"] is True
    assert client.get("/api/v1/routes/alternative", params={"from_edge": "x", "to_edge": "y"}).status_code == 422


def test_collector_metrics_without_sumo(net):
    col = MeasurementCollector(net, 1.0, 5, metrics_from_s=2.0)
    e = net.edge_ids[0]
    for t in range(1, 11):
        col.update(float(t), {e: EdgeStep(2, 0.0, 10.0, 2, ("a", "b"))}, ["a", "b"] if t == 1 else [], ["a"] if t == 9 else [])
    times, obs = col.observations()
    assert times == [5.0, 10.0] and obs.shape == (2, net.n_edges, 5)
    m = col.window_metrics()
    assert m["avg_wait_s"] > 0 and m["throughput_veh"] == 1 and m["avg_travel_time_s"] == 8.0


def test_scenarios_are_reproducible(net):
    a = build_trips(net, ScenarioConfig("ew_heavy", 1.0, 5, 600))
    assert a == build_trips(net, ScenarioConfig("ew_heavy", 1.0, 5, 600))
    assert a != build_trips(net, ScenarioConfig("ew_heavy", 1.0, 6, 600))


def test_sumocfg_validation_detects_problems(tmp_path):
    bad = tmp_path / "x.sumocfg"
    bad.write_text('<configuration><input><net-file value="missing.net.xml"/></input></configuration>')
    with pytest.raises(SumoConfigError):
        validate_sumocfg(bad, dry_run=False)
    bad.write_text("<not xml")
    with pytest.raises(SumoConfigError):
        validate_sumocfg(bad, dry_run=False)


@pytest.mark.sumo
def test_demo_sumocfg_is_valid():
    assert validate_sumocfg(get_settings().sumocfg_file)["ok"]


@pytest.mark.sumo
def test_runner_produces_observations_and_cleans_up(net):
    import traci

    r = SumoRunner(net).run(ScenarioConfig("balanced", 1.0, 3, 300), metrics_from_s=100)
    assert r.observations.shape == (3, net.n_edges, 5) and r.metrics["total_departed"] > 0
    assert not traci.connection.has(f"nexflow-{r.run_id}")  # connection released
    assert not (get_settings().runs_dir / f"run_{r.run_id}").exists()  # temp files removed


@pytest.mark.sumo
def test_runner_cleans_up_after_error(net):
    import threading, traci

    ev = threading.Event(); ev.set()
    from app.core.errors import SimulationCancelled
    with pytest.raises(SimulationCancelled):
        SumoRunner(net).run(ScenarioConfig("balanced", 1.0, 3, 300), stop_event=ev, run_id="cleanuptest")
    assert not traci.connection.has("nexflow-cleanuptest")


@pytest.mark.sumo
def test_signal_intervention_changes_program(net):
    from app.interventions.models import SIGNAL, Intervention
    r = SumoRunner(net).run(ScenarioConfig("ew_heavy", 1.0, 3, 200), Intervention(SIGNAL, "B1", {0: 20, 2: 50}), activate_at_s=50, collect_observations=False)
    ph = r.tls_programs["B1"]
    assert ph["program_id"] == "nexflow" and ph["phases"][0]["duration"] == 20 and ph["phases"][2]["duration"] == 50
