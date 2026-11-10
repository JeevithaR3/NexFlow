"""Poll and persist TomTom traffic-flow observations at selected Bengaluru road points."""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import ConflictError, DataValidationError, LiveTrafficUnavailableError
from app.core.logging import get_logger
from app.models.db import Database, LiveTrafficReadingRow

log = get_logger("tomtom_traffic")

FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"


@dataclass(frozen=True)
class TrafficSensor:
    id: str
    road_name: str
    latitude: float
    longitude: float


SENSORS = (
    TrafficSensor("mg-road", "Mahatma Gandhi Road", 12.9757, 77.6055),
    TrafficSensor("indiranagar", "100 Feet Road, Indiranagar", 12.9784, 77.6408),
    TrafficSensor("whitefield", "ITPL Main Road, Whitefield", 12.9887, 77.7285),
    TrafficSensor("koramangala", "80 Feet Road, Koramangala", 12.9352, 77.6148),
    TrafficSensor("silk-board", "Silk Board Junction", 12.9177, 77.6233),
)
_SENSOR_BY_ID = {sensor.id: sensor for sensor in SENSORS}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_dict(row: LiveTrafficReadingRow) -> dict:
    return {
        "id": row.id,
        "sensor_id": row.sensor_id,
        "road_name": row.road_name,
        "observed_at": row.observed_at,
        "latitude": row.latitude,
        "longitude": row.longitude,
        "current_speed_kph": row.current_speed_kph,
        "free_flow_speed_kph": row.free_flow_speed_kph,
        "current_travel_time_s": row.current_travel_time_s,
        "free_flow_travel_time_s": row.free_flow_travel_time_s,
        "confidence": row.confidence,
        "road_closure": row.road_closure,
        "geometry": row.geometry,
    }


class TomTomTrafficCollector:
    def __init__(
        self,
        db: Database,
        api_key: str | None,
        poll_interval_s: int = 300,
        retention_days: int = 30,
        client_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self.db = db
        self.api_key = api_key.strip() if api_key else ""
        self.poll_interval_s = poll_interval_s
        self.retention_days = retention_days
        self._client_factory = client_factory or (lambda: httpx.Client(timeout=8.0))
        self._poll_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = "not_configured" if not self.api_key else "waiting"
        self._last_poll_at: str | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if not self.api_key:
            return
        with self._state_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="tomtom-traffic", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=45)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except (SQLAlchemyError, LiveTrafficUnavailableError) as exc:
                message = "Could not persist or retrieve live traffic readings."
                with self._state_lock:
                    self._status, self._last_error = "error", message
                log.error(message, exc_info=exc)
            self._stop.wait(self.poll_interval_s)

    @staticmethod
    def _number(data: dict, key: str, *, minimum: float = 0.0) -> float:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DataValidationError(f"TomTom response has an invalid {key} value.")
        result = float(value)
        if not math.isfinite(result) or result < minimum:
            raise DataValidationError(f"TomTom response has an invalid {key} value.")
        return result

    def _fetch(self, client: httpx.Client, sensor: TrafficSensor) -> dict:
        response = client.get(
            FLOW_URL,
            params={
                "key": self.api_key,
                "point": f"{sensor.latitude},{sensor.longitude}",
                "unit": "kmph",
            },
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataValidationError("TomTom returned invalid JSON.") from exc
        flow = payload.get("flowSegmentData") if isinstance(payload, dict) else None
        if not isinstance(flow, dict):
            raise DataValidationError("TomTom response is missing flowSegmentData.")

        free_flow = self._number(flow, "freeFlowSpeed", minimum=0.01)
        current_speed = self._number(flow, "currentSpeed")
        current_time = self._number(flow, "currentTravelTime")
        free_flow_time = self._number(flow, "freeFlowTravelTime")
        confidence = self._number(flow, "confidence")
        if confidence > 1:
            raise DataValidationError("TomTom response has an invalid confidence value.")
        coordinates = flow.get("coordinates")
        if coordinates is None:
            raw_coordinates = []
        elif isinstance(coordinates, dict):
            raw_coordinates = coordinates.get("coordinate", [])
        else:
            raise DataValidationError("TomTom response has invalid road geometry.")
        if not isinstance(raw_coordinates, list):
            raise DataValidationError("TomTom response has invalid road geometry.")
        geometry = []
        if raw_coordinates:
            for point in raw_coordinates:
                if not isinstance(point, dict):
                    raise DataValidationError("TomTom response has invalid road geometry.")
                geometry.append([
                    self._number(point, "latitude", minimum=-90),
                    self._number(point, "longitude", minimum=-180),
                ])
                if abs(geometry[-1][0]) > 90 or abs(geometry[-1][1]) > 180:
                    raise DataValidationError("TomTom response has invalid road geometry.")
        road_closure = flow.get("roadClosure", False)
        if not isinstance(road_closure, bool):
            raise DataValidationError("TomTom response has an invalid roadClosure value.")
        return {
            "current_speed_kph": current_speed,
            "free_flow_speed_kph": free_flow,
            "current_travel_time_s": current_time,
            "free_flow_travel_time_s": free_flow_time,
            "confidence": confidence,
            "road_closure": road_closure,
            "geometry": geometry or None,
        }

    def poll_once(self) -> dict:
        if not self.api_key:
            raise LiveTrafficUnavailableError(
                "TomTom live traffic is not configured.",
                hint="Set NEXFLOW_TOMTOM_API_KEY in the backend environment and restart the API.",
            )
        if not self._poll_lock.acquire(blocking=False):
            raise ConflictError("A Bengaluru traffic poll is already in progress.")
        try:
            observed_at = _iso_now()
            readings, failures = [], []
            with self._client_factory() as client:
                for sensor in SENSORS:
                    try:
                        readings.append((sensor, self._fetch(client, sensor)))
                    except httpx.HTTPStatusError as exc:
                        status = exc.response.status_code
                        failures.append({"sensor_id": sensor.id, "message": f"TomTom returned HTTP {status}."})
                        log.warning("TomTom traffic request failed", extra={"sensor_id": sensor.id, "status": status})
                    except httpx.RequestError:
                        failures.append({"sensor_id": sensor.id, "message": "Could not connect to TomTom."})
                        log.warning("TomTom traffic request could not connect", extra={"sensor_id": sensor.id})
                    except DataValidationError as exc:
                        failures.append({"sensor_id": sensor.id, "message": exc.message})
                        log.warning("TomTom returned invalid traffic data", extra={"sensor_id": sensor.id})

            cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat(timespec="seconds")
            with self.db.session() as session:
                for sensor, values in readings:
                    session.add(LiveTrafficReadingRow(
                        sensor_id=sensor.id,
                        road_name=sensor.road_name,
                        observed_at=observed_at,
                        latitude=sensor.latitude,
                        longitude=sensor.longitude,
                        **values,
                    ))
                session.execute(delete(LiveTrafficReadingRow).where(LiveTrafficReadingRow.observed_at < cutoff))

            status = "ok" if not failures else "partial" if readings else "error"
            error = "; ".join(item["message"] for item in failures) if failures else None
            with self._state_lock:
                self._status, self._last_poll_at, self._last_error = status, observed_at, error
            return {
                "status": status,
                "observed_at": observed_at,
                "saved_readings": len(readings),
                "failures": failures,
            }
        finally:
            self._poll_lock.release()

    def snapshot(self) -> dict:
        latest = {}
        with self.db.session() as session:
            for sensor in SENSORS:
                row = session.scalar(
                    select(LiveTrafficReadingRow)
                    .where(LiveTrafficReadingRow.sensor_id == sensor.id)
                    .order_by(LiveTrafficReadingRow.observed_at.desc())
                    .limit(1)
                )
                latest[sensor.id] = _row_dict(row) if row else None
            count = session.scalar(select(func.count()).select_from(LiveTrafficReadingRow)) or 0
            first = session.scalar(select(func.min(LiveTrafficReadingRow.observed_at)))
        with self._state_lock:
            status, last_poll, last_error = self._status, self._last_poll_at, self._last_error
        return {
            "provider": "TomTom Traffic Flow",
            "configured": bool(self.api_key),
            "polling_enabled": bool(self.api_key and self._thread and self._thread.is_alive()),
            "poll_interval_s": self.poll_interval_s,
            "status": status,
            "last_poll_at": last_poll,
            "last_error": last_error,
            "observation_count": count,
            "first_observation_at": first,
            "sensors": [
                {
                    "id": sensor.id,
                    "road_name": sensor.road_name,
                    "latitude": sensor.latitude,
                    "longitude": sensor.longitude,
                    "latest": latest[sensor.id],
                }
                for sensor in SENSORS
            ],
        }

    def history(self, *, sensor_id: str | None = None, limit: int = 1000) -> list[dict]:
        if sensor_id is not None and sensor_id not in _SENSOR_BY_ID:
            raise DataValidationError(f"Unknown Bengaluru traffic sensor: {sensor_id}")
        with self.db.session() as session:
            query = select(LiveTrafficReadingRow).order_by(LiveTrafficReadingRow.observed_at.desc())
            if sensor_id:
                query = query.where(LiveTrafficReadingRow.sensor_id == sensor_id)
            rows = list(session.scalars(query.limit(limit)))
        return [_row_dict(row) for row in reversed(rows)]
