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
ROUTE_URL = "https://api.tomtom.com/routing/1/calculateRoute"


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


def _level_for_speed(speed_kph: float, free_flow_speed_kph: float) -> str:
    ratio = speed_kph / free_flow_speed_kph
    return "low" if ratio >= 0.8 else "moderate" if ratio >= 0.5 else "high"


def _point_polyline_distance_m(point: list[float], line: list[list[float]]) -> float:
    """Approximate local distance in meters for the short Bengaluru road segments."""
    if not line:
        return math.inf
    latitude_scale = 111_320.0
    longitude_scale = latitude_scale * math.cos(math.radians(point[0]))
    px, py = point[1] * longitude_scale, point[0] * latitude_scale
    if len(line) == 1:
        return math.hypot(px - line[0][1] * longitude_scale, py - line[0][0] * latitude_scale)

    nearest = math.inf
    for start, end in zip(line, line[1:]):
        ax, ay = start[1] * longitude_scale, start[0] * latitude_scale
        bx, by = end[1] * longitude_scale, end[0] * latitude_scale
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        fraction = 0.0 if length_squared == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
        nearest = min(nearest, math.hypot(px - (ax + fraction * dx), py - (ay + fraction * dy)))
    return nearest


def _geometries_match(first: list[list[float]] | None, second: list[list[float]], tolerance_m: float = 50.0) -> bool:
    if not first or len(first) < 2 or len(second) < 2:
        return False
    return (
        min(_point_polyline_distance_m(point, second) for point in first) <= tolerance_m
        or min(_point_polyline_distance_m(point, first) for point in second) <= tolerance_m
    )


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

    def route_options(self, origin_id: str, destination_id: str) -> dict:
        if not self.api_key:
            raise LiveTrafficUnavailableError(
                "TomTom live routing is not configured.",
                hint="Set NEXFLOW_TOMTOM_API_KEY in the backend environment and restart the API.",
            )
        if origin_id not in _SENSOR_BY_ID or destination_id not in _SENSOR_BY_ID:
            raise DataValidationError("Choose an origin and destination from the monitored Bengaluru corridors.")
        if origin_id == destination_id:
            raise DataValidationError("Choose two different roads for the trip.")

        origin, destination = _SENSOR_BY_ID[origin_id], _SENSOR_BY_ID[destination_id]
        locations = (
            f"{origin.latitude},{origin.longitude}:"
            f"{destination.latitude},{destination.longitude}"
        )
        try:
            with self._client_factory() as client:
                response = client.get(
                    f"{ROUTE_URL}/{locations}/json",
                    params={
                        "key": self.api_key,
                        "traffic": "true",
                        "routeType": "fastest",
                        "maxAlternatives": 2,
                        "computeTravelTimeFor": "all",
                        "routeRepresentation": "polyline",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            log.warning("TomTom live route request failed", extra={"status": status})
            raise LiveTrafficUnavailableError(
                f"TomTom live routing returned HTTP {status}.",
                hint="Check that your API key and TomTom account have access to the Routing API.",
            ) from exc
        except httpx.RequestError as exc:
            log.warning("TomTom live route request could not connect")
            raise LiveTrafficUnavailableError(
                "Could not connect to TomTom live routing.",
                hint="Check the backend internet connection and try again.",
            ) from exc
        except ValueError as exc:
            raise DataValidationError("TomTom returned invalid route JSON.") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("routes"), list):
            raise DataValidationError("TomTom route response is missing routes.")
        routes = []
        for index, route in enumerate(payload["routes"]):
            if not isinstance(route, dict) or not isinstance(route.get("summary"), dict):
                raise DataValidationError("TomTom returned a route without a summary.")
            summary = route["summary"]
            legs = route.get("legs")
            if not isinstance(legs, list):
                raise DataValidationError("TomTom returned a route without geometry.")
            geometry = []
            for leg in legs:
                if not isinstance(leg, dict) or not isinstance(leg.get("points"), list):
                    raise DataValidationError("TomTom returned invalid route geometry.")
                for point in leg["points"]:
                    if not isinstance(point, dict):
                        raise DataValidationError("TomTom returned invalid route geometry.")
                    lat = self._number(point, "latitude", minimum=-90)
                    lon = self._number(point, "longitude", minimum=-180)
                    if lat > 90 or lon > 180:
                        raise DataValidationError("TomTom returned invalid route geometry.")
                    geometry.append([lat, lon])
            if len(geometry) < 2:
                raise DataValidationError("TomTom route geometry must contain at least two points.")

            distance_m = self._number(summary, "lengthInMeters")
            travel_time_s = self._number(summary, "travelTimeInSeconds")
            traffic_delay = summary.get("trafficDelayInSeconds")
            if traffic_delay is not None:
                traffic_delay = self._number({"trafficDelayInSeconds": traffic_delay}, "trafficDelayInSeconds")
            routes.append({
                "rank": index + 1,
                "label": "Fastest with current traffic" if index == 0 else f"Alternative {index}",
                "distance_m": distance_m,
                "travel_time_s": travel_time_s,
                "traffic_delay_s": traffic_delay,
                "geometry": geometry,
            })
        if not routes:
            raise LiveTrafficUnavailableError(
                "TomTom did not find a route for the selected Bengaluru trip.",
                hint="Choose different monitored roads and try again.",
            )
        predictions = {
            forecast["sensor_id"]: forecast
            for forecast in self.predictions()["sensors"]
            if forecast["available"]
        }
        for route in routes:
            matched = [
                forecast for forecast in predictions.values()
                if _geometries_match(forecast["geometry"], route["geometry"])
            ]
            adjustment = 0.0
            for forecast in matched:
                latest = forecast["latest"]
                predicted_speed = forecast["predicted_speed_kph"]
                if latest["road_closure"] or predicted_speed <= 0.1:
                    adjustment += latest["current_travel_time_s"] * 4
                    continue
                if latest["current_speed_kph"] <= 0.1:
                    continue
                current_segment_time = latest["current_travel_time_s"]
                predicted_segment_time = current_segment_time * latest["current_speed_kph"] / predicted_speed
                adjustment += predicted_segment_time - current_segment_time

            route["forecast_sensor_ids"] = [forecast["sensor_id"] for forecast in matched]
            route["forecast_sensor_count"] = len(matched)
            route["forecast_adjustment_s"] = adjustment

        forecast_available = any(route["forecast_sensor_count"] for route in routes)
        for route in routes:
            route["predicted_travel_time_s"] = (
                max(0.0, route["travel_time_s"] + route["forecast_adjustment_s"])
                if forecast_available else None
            )
            if not forecast_available:
                route["forecast_adjustment_s"] = None

        if forecast_available:
            routes.sort(key=lambda route: (route["predicted_travel_time_s"], route["travel_time_s"]))
            for recommendation_rank, route in enumerate(routes, start=1):
                route["recommendation_rank"] = recommendation_rank
                route["recommended"] = recommendation_rank == 1
        else:
            for route in routes:
                route["recommendation_rank"] = None
                route["recommended"] = False

        if forecast_available:
            notice = (
                "TomTom provides the current-traffic route ETAs. NexFlow ranks routes using trend forecasts for "
                "monitored road segments that match each route; unmonitored portions retain TomTom's current ETA. "
                "This is a limited history-based estimate, not the synthetic GNN or a full-trip forecast."
            )
        elif predictions:
            notice = (
                "TomTom provides current-traffic route ETAs, but none of the available forecast geometries matched "
                "these routes. NexFlow cannot rank them by forecast for this trip."
            )
        else:
            notice = (
                "TomTom provides current-traffic route ETAs. NexFlow cannot rank these routes by forecast yet; "
                "collect at least three readings spanning two poll intervals for the monitored roads."
            )

        return {
            "provider": "TomTom Routing API",
            "source": "live_traffic_routing",
            "traffic_aware": True,
            "forecast_source": "tomtom_history_trend" if forecast_available else None,
            "origin": {"id": origin.id, "road_name": origin.road_name, "latitude": origin.latitude, "longitude": origin.longitude},
            "destination": {
                "id": destination.id,
                "road_name": destination.road_name,
                "latitude": destination.latitude,
                "longitude": destination.longitude,
            },
            "requested_at": _iso_now(),
            "routes": routes,
            "notice": notice,
        }

    def predictions(self, horizon_s: int = 900) -> dict:
        if horizon_s < 1:
            raise DataValidationError("Prediction horizon must be positive.")
        forecasts = []
        with self.db.session() as session:
            for sensor in SENSORS:
                rows = list(session.scalars(
                    select(LiveTrafficReadingRow)
                    .where(LiveTrafficReadingRow.sensor_id == sensor.id)
                    .order_by(LiveTrafficReadingRow.observed_at.desc())
                    .limit(6)
                ))
                readings = [_row_dict(row) for row in reversed(rows)]
                available = len(readings) >= 3
                parsed_times = [datetime.fromisoformat(row["observed_at"]) for row in readings]
                span_s = (parsed_times[-1] - parsed_times[0]).total_seconds() if len(parsed_times) >= 2 else 0.0
                available = available and span_s >= 2 * self.poll_interval_s
                latest_age_s = (
                    max(0.0, (datetime.now(timezone.utc) - parsed_times[-1].astimezone(timezone.utc)).total_seconds())
                    if parsed_times else None
                )
                available = available and latest_age_s is not None and latest_age_s <= 2 * self.poll_interval_s
                latest = readings[-1] if readings else None
                forecast = {
                    "sensor_id": sensor.id,
                    "road_name": sensor.road_name,
                    "available": available,
                    "reason": None if available else "Collect three recent readings spanning two poll intervals.",
                    "sample_count": len(readings),
                    "history_span_s": max(0.0, span_s),
                    "latest_age_s": latest_age_s,
                    "latest": latest,
                    "geometry": latest["geometry"] if latest else None,
                    "predicted_speed_kph": None,
                    "predicted_travel_time_s": None,
                    "congestion_level": None,
                }
                if available and latest:
                    times = [(timestamp - parsed_times[0]).total_seconds() for timestamp in parsed_times]
                    ratios = [row["current_speed_kph"] / row["free_flow_speed_kph"] for row in readings]
                    mean_time = sum(times) / len(times)
                    mean_ratio = sum(ratios) / len(ratios)
                    variance = sum((time - mean_time) ** 2 for time in times)
                    slope = (
                        sum((time - mean_time) * (ratio - mean_ratio) for time, ratio in zip(times, ratios)) / variance
                        if variance > 0 else 0.0
                    )
                    predicted_ratio = max(0.0, min(1.0, mean_ratio + slope * (times[-1] + horizon_s - mean_time)))
                    predicted_speed = predicted_ratio * latest["free_flow_speed_kph"]
                    forecast.update({
                        "predicted_speed_kph": predicted_speed,
                        "predicted_travel_time_s": (
                            latest["current_travel_time_s"] * latest["current_speed_kph"] / predicted_speed
                            if predicted_speed > 0.1 else None
                        ),
                        "congestion_level": _level_for_speed(predicted_speed, latest["free_flow_speed_kph"]),
                    })
                forecasts.append(forecast)
        return {
            "available": any(forecast["available"] for forecast in forecasts),
            "source": "tomtom_history_trend",
            "method": "Linear trend of speed/free-flow ratio over up to six recent TomTom readings, clamped to 0-100% of free-flow speed.",
            "horizon_s": horizon_s,
            "minimum_samples": 3,
            "minimum_history_span_s": 2 * self.poll_interval_s,
            "maximum_latest_age_s": 2 * self.poll_interval_s,
            "sensors": forecasts,
        }

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
