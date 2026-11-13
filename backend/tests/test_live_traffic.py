from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.errors import DataValidationError, LiveTrafficUnavailableError
from app.digital_twin.network import EdgeInfo, NetworkModel
from app.main import create_app
from app.models.db import Database, LiveTrafficReadingRow
from app.services.bengaluru_sumo import match_live_speeds, rank_routes_with_sumo_forecast
from app.services.tomtom_traffic import SENSORS, TomTomTrafficCollector


def _flow_response():
    return {
        "flowSegmentData": {
            "currentSpeed": 18.5,
            "freeFlowSpeed": 42.0,
            "currentTravelTime": 75,
            "freeFlowTravelTime": 32,
            "confidence": 0.91,
            "roadClosure": False,
            "coordinates": {
                "coordinate": [
                    {"latitude": 12.9757, "longitude": 77.6055},
                    {"latitude": 12.9758, "longitude": 77.6056},
                ]
            },
        }
    }


def _collector(tmp_path, handler):
    db = Database(f"sqlite:///{(tmp_path / 'traffic.db').as_posix()}")
    transport = httpx.MockTransport(handler)
    collector = TomTomTrafficCollector(
        db,
        "test-key",
        client_factory=lambda: httpx.Client(transport=transport),
    )
    return db, collector


def _insert_history(db, sensor, speeds, *, travel_time_s=60, geometry=None, age_s=0):
    observed_at = datetime.now(timezone.utc) - timedelta(seconds=(len(speeds) - 1) * 300 + age_s)
    with db.session() as session:
        for index, speed in enumerate(speeds):
            session.add(LiveTrafficReadingRow(
                sensor_id=sensor.id,
                road_name=sensor.road_name,
                observed_at=(observed_at + timedelta(seconds=index * 300)).isoformat(timespec="seconds"),
                latitude=sensor.latitude,
                longitude=sensor.longitude,
                current_speed_kph=speed,
                free_flow_speed_kph=40,
                current_travel_time_s=travel_time_s,
                free_flow_travel_time_s=30,
                confidence=0.9,
                road_closure=False,
                geometry=geometry or [[sensor.latitude, sensor.longitude], [sensor.latitude + 0.0001, sensor.longitude + 0.0001]],
            ))


def test_tomtom_poll_persists_all_corridors_and_history(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path.endswith("/flowSegmentData/absolute/10/json")
        assert request.url.params["unit"] == "kmph"
        assert request.url.params["point"]
        return httpx.Response(200, json=_flow_response())

    db, collector = _collector(tmp_path, handler)
    result = collector.poll_once()

    assert result["status"] == "ok"
    assert result["saved_readings"] == len(SENSORS)
    assert len(requests) == len(SENSORS)
    snapshot = collector.snapshot()
    assert snapshot["configured"] is True
    assert snapshot["observation_count"] == len(SENSORS)
    assert snapshot["sensors"][0]["latest"]["current_speed_kph"] == 18.5
    assert snapshot["sensors"][0]["latest"]["geometry"] == [[12.9757, 77.6055], [12.9758, 77.6056]]
    assert len(collector.history(sensor_id="mg-road", limit=1)) == 1
    db.dispose()


def test_tomtom_poll_reports_provider_failures_without_leaking_key(tmp_path):
    def handler(_request):
        return httpx.Response(401, json={"error": "unauthorized"})

    db, collector = _collector(tmp_path, handler)
    result = collector.poll_once()

    assert result["status"] == "error"
    assert result["saved_readings"] == 0
    assert len(result["failures"]) == len(SENSORS)
    assert all("401" in item["message"] for item in result["failures"])
    assert "test-key" not in repr(result)
    db.dispose()


def test_tomtom_rejects_malformed_traffic_values(tmp_path):
    def handler(_request):
        payload = _flow_response()
        payload["flowSegmentData"]["currentSpeed"] = "fast"
        return httpx.Response(200, json=payload)

    db, collector = _collector(tmp_path, handler)
    result = collector.poll_once()

    assert result["status"] == "error"
    assert "invalid currentSpeed" in result["failures"][0]["message"]
    with pytest.raises(DataValidationError):
        collector.history(sensor_id="unknown")
    db.dispose()


def test_tomtom_live_routing_returns_current_traffic_routes(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        assert "/calculateRoute/" in request.url.path
        assert request.url.params["traffic"] == "true"
        assert request.url.params["routeType"] == "fastest"
        assert request.url.params["maxAlternatives"] == "2"
        return httpx.Response(200, json={
            "routes": [
                {
                    "summary": {"lengthInMeters": 7200, "travelTimeInSeconds": 1100, "trafficDelayInSeconds": 240},
                    "legs": [{"points": [
                        {"latitude": 12.9757, "longitude": 77.6055},
                        {"latitude": 12.9177, "longitude": 77.6233},
                    ]}],
                },
                {
                    "summary": {"lengthInMeters": 8100, "travelTimeInSeconds": 1300, "trafficDelayInSeconds": 90},
                    "legs": [{"points": [
                        {"latitude": 12.9757, "longitude": 77.6055},
                        {"latitude": 12.95, "longitude": 77.62},
                        {"latitude": 12.9177, "longitude": 77.6233},
                    ]}],
                },
            ]
        })

    db, collector = _collector(tmp_path, handler)
    result = collector.route_options("mg-road", "silk-board")

    assert len(seen) == 1
    assert result["source"] == "live_traffic_routing"
    assert result["traffic_aware"] is True
    assert result["origin"]["road_name"] == "Mahatma Gandhi Road"
    assert result["destination"]["road_name"] == "Silk Board Junction"
    assert [route["label"] for route in result["routes"]] == ["Fastest with current traffic", "Alternative 1"]
    assert result["routes"][0]["travel_time_s"] == 1100
    assert result["routes"][1]["geometry"][1] == [12.95, 77.62]
    assert result["forecast_source"] is None
    assert result["routes"][0]["recommended"] is False
    assert "cannot rank these routes by forecast yet" in result["notice"]
    db.dispose()


def test_real_road_forecast_requires_history_and_extrapolates_bounded_speed_trend(tmp_path):
    db, collector = _collector(tmp_path, lambda _request: httpx.Response(200, json=_flow_response()))
    _insert_history(db, SENSORS[0], [10, 20, 30])

    result = collector.predictions()
    forecast = result["sensors"][0]

    assert result["available"] is True
    assert result["source"] == "tomtom_history_trend"
    assert result["horizon_s"] == 900
    assert forecast["available"] is True
    assert forecast["sample_count"] == 3
    assert forecast["predicted_speed_kph"] == 40
    assert forecast["congestion_level"] == "low"
    assert result["sensors"][1]["available"] is False
    db.dispose()


def test_real_road_forecast_expires_when_tomtom_readings_are_stale(tmp_path):
    db, collector = _collector(tmp_path, lambda _request: httpx.Response(200, json=_flow_response()))
    _insert_history(db, SENSORS[0], [10, 20, 30], age_s=3600)

    forecast = collector.predictions()["sensors"][0]

    assert forecast["available"] is False
    assert forecast["latest_age_s"] > collector.poll_interval_s * 2
    db.dispose()


def test_live_routes_are_ranked_by_forecast_for_matching_monitored_road_segments(tmp_path):
    kor_geometry = [[12.95, 77.70], [12.9501, 77.7001]]
    db = Database(f"sqlite:///{(tmp_path / 'traffic.db').as_posix()}")
    _insert_history(db, SENSORS[0], [30, 30, 30])
    _insert_history(db, SENSORS[3], [30, 20, 10], travel_time_s=120, geometry=kor_geometry)
    route_geometry = [[12.9757, 77.6055], *kor_geometry, [12.9177, 77.6233]]
    direct_geometry = [[12.9757, 77.6055], [12.9177, 77.6233]]

    def handler(_request):
        return httpx.Response(200, json={
            "routes": [
                {"summary": {"lengthInMeters": 7000, "travelTimeInSeconds": 1000, "trafficDelayInSeconds": 0},
                 "legs": [{"points": [{"latitude": lat, "longitude": lon} for lat, lon in route_geometry]}]},
                {"summary": {"lengthInMeters": 8000, "travelTimeInSeconds": 1200, "trafficDelayInSeconds": 0},
                 "legs": [{"points": [{"latitude": lat, "longitude": lon} for lat, lon in direct_geometry]}]},
            ]
        })

    collector = TomTomTrafficCollector(
        db, "test-key", client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = collector.route_options("mg-road", "silk-board")

    assert result["routes"][0]["rank"] == 2
    assert result["routes"][0]["recommended"] is True
    assert result["routes"][0]["predicted_travel_time_s"] == 1200
    slower = next(route for route in result["routes"] if route["rank"] == 1)
    assert slower["forecast_sensor_ids"] == ["mg-road", "koramangala"]
    assert slower["predicted_travel_time_s"] > 1200
    db.dispose()


def test_tomtom_live_routing_rejects_unmonitored_trips_and_hides_provider_details(tmp_path):
    db, collector = _collector(tmp_path, lambda _request: httpx.Response(401, text="denied: do not expose this"))

    with pytest.raises(DataValidationError):
        collector.route_options("unknown", "silk-board")
    with pytest.raises(DataValidationError):
        collector.route_options("mg-road", "mg-road")
    with pytest.raises(LiveTrafficUnavailableError) as err:
        collector.route_options("mg-road", "silk-board")
    assert "HTTP 401" in str(err.value)
    assert "denied" not in str(err.value)
    assert "test-key" not in str(err.value)
    db.dispose()


def test_live_traffic_routes_are_explicit_when_provider_is_not_configured(tmp_path):
    settings = get_settings().model_copy(
        update={
            "data_dir": tmp_path,
            "database_url": f"sqlite:///{(tmp_path / 'api.db').as_posix()}",
            "tomtom_api_key": None,
        }
    )
    with TestClient(create_app(settings)) as client:
        status = client.get("/api/v1/traffic/bengaluru")
        assert status.status_code == 200
        assert status.json()["configured"] is False
        assert len(status.json()["sensors"]) == len(SENSORS)
        assert status.json()["sensors"][0]["latest"] is None
        predictions = client.get("/api/v1/traffic/bengaluru/predictions")
        assert predictions.status_code == 200
        assert predictions.json()["available"] is False

        poll = client.post("/api/v1/traffic/bengaluru/poll")
        assert poll.status_code == 503
        assert poll.json()["error"]["code"] == "live_traffic_unavailable"
        route = client.get("/api/v1/traffic/bengaluru/routes", params={"origin_id": "mg-road", "destination_id": "silk-board"})
        assert route.status_code == 503
        assert route.json()["error"]["code"] == "live_traffic_unavailable"


def test_tomtom_speed_match_uses_nearest_osm_edge_and_handles_stopped_traffic():
    edge = EdgeInfo(
        "osm-road",
        "from",
        "to",
        100,
        13.89,
        1,
        ((0, 0), (1, 0)),
        ((12.9757, 77.6055), (12.9758, 77.6056)),
    )
    network = NetworkModel(Path("bengaluru.net.xml"), [edge], [], {}, {}, [], "net", "tls")
    snapshot = {
        "poll_interval_s": 300,
        "sensors": [{
            "id": "mg-road",
            "road_name": "Mahatma Gandhi Road",
            "latitude": 12.9757,
            "longitude": 77.6055,
            "latest": {
                "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "current_speed_kph": 0,
            },
        }],
    }

    speed_limits, matches = match_live_speeds(network, snapshot)

    assert speed_limits == {"osm-road": 0.1}
    assert matches[0]["edge_id"] == "osm-road"
    assert matches[0]["applied_speed_kph"] == 0.4


def test_sumo_gnn_forecast_reorders_routes_using_matched_osm_road_predictions():
    edges = [
        EdgeInfo(
            "congested-road", "a", "b", 100, 13.89, 1, ((0, 0), (1, 0)),
            ((12.9757, 77.6055), (12.9757, 77.6065)),
        ),
        EdgeInfo(
            "clear-road", "c", "d", 100, 13.89, 1, ((0, 0), (1, 0)),
            ((12.978, 77.6055), (12.978, 77.6065)),
        ),
    ]
    network = NetworkModel(Path("bengaluru.net.xml"), edges, [], {}, {}, [], "net", "tls")
    response = {
        "routes": [
            {"rank": 1, "travel_time_s": 600, "geometry": [[12.9757, 77.6055], [12.9757, 77.6065]]},
            {"rank": 2, "travel_time_s": 650, "geometry": [[12.978, 77.6055], [12.978, 77.6065]]},
        ],
    }

    ranked = rank_routes_with_sumo_forecast(
        response,
        network,
        [
            {"id": "congested-road", "ci": 0.1, "pred_ci": 0.9},
            {"id": "clear-road", "ci": 0.1, "pred_ci": 0.1},
        ],
        simulation_run_id="run-123456789",
        horizon_s=270,
    )

    assert ranked["forecast_source"] == "bengaluru_sumo_gnn"
    assert ranked["simulation_run_id"] == "run-123456789"
    assert ranked["routes"][0]["travel_time_s"] == 650
    assert ranked["routes"][0]["recommended"] is True
    assert ranked["routes"][0]["simulation_forecast_edge_ids"] == ["clear-road"]
    assert ranked["routes"][0]["simulation_forecast_coverage_pct"] == 100
    assert ranked["routes"][1]["simulation_forecast_adjustment_s"] > 0


def test_bengaluru_sumo_api_explains_setup_requirements_when_network_is_missing(tmp_path):
    settings = get_settings().model_copy(
        update={
            "data_dir": tmp_path,
            "database_url": f"sqlite:///{(tmp_path / 'api.db').as_posix()}",
            "tomtom_api_key": None,
        }
    )
    with TestClient(create_app(settings)) as client:
        network = client.get("/api/v1/traffic/bengaluru/sumo/network")
        assert network.status_code == 422
        assert "setup_bengaluru_sumo.py" in network.json()["error"]["hint"]
        run = client.post(
            "/api/v1/traffic/bengaluru/sumo/run",
            json={"scenario": {"pattern": "balanced", "demand_scale": 1.0, "seed": 2}},
        )
        assert run.status_code == 422
        assert "setup_bengaluru_sumo.py" in run.json()["error"]["hint"]


def test_live_route_endpoint_accepts_completed_bengaluru_gnn_run_for_ranking(tmp_path, monkeypatch):
    settings = get_settings().model_copy(
        update={
            "data_dir": tmp_path,
            "database_url": f"sqlite:///{(tmp_path / 'api.db').as_posix()}",
            "tomtom_api_key": None,
        }
    )
    edge = EdgeInfo(
        "osm-road",
        "from",
        "to",
        100,
        13.89,
        1,
        ((0, 0), (1, 0)),
        ((12.9757, 77.6055), (12.9757, 77.6065)),
    )
    network = NetworkModel(Path("bengaluru.net.xml"), [edge], [], {}, {}, [], "net-hash", "tls")
    route_response = {
        "routes": [{
            "rank": 1,
            "travel_time_s": 600,
            "geometry": [[12.9757, 77.6055], [12.9757, 77.6065]],
        }],
    }
    completed_run = {
        "kind": "bengaluru_sumo",
        "status": "succeeded",
        "result": {
            "network_id": "net-hash",
            "horizon_s": 270,
            "edges": [{"id": "osm-road", "ci": 0.1, "pred_ci": 0.8}],
        },
    }
    with TestClient(create_app(settings)) as client:
        state = client.app.state.nexflow
        state.bengaluru_net = network
        monkeypatch.setattr(state.traffic, "route_options", lambda *_args: route_response)
        monkeypatch.setattr(state.jobs, "get", lambda run_id: completed_run if run_id == "run-12345678" else None)

        response = client.get(
            "/api/v1/traffic/bengaluru/routes",
            params={"origin_id": "mg-road", "destination_id": "silk-board", "simulation_run_id": "run-12345678"},
        )

        assert response.status_code == 200
        result = response.json()
        assert result["forecast_source"] == "bengaluru_sumo_gnn"
        assert result["routes"][0]["simulation_forecast_edge_ids"] == ["osm-road"]
        assert result["routes"][0]["predicted_travel_time_s"] > result["routes"][0]["travel_time_s"]
