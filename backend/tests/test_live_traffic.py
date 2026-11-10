import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.errors import DataValidationError
from app.main import create_app
from app.models.db import Database
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

        poll = client.post("/api/v1/traffic/bengaluru/poll")
        assert poll.status_code == 503
        assert poll.json()["error"]["code"] == "live_traffic_unavailable"
