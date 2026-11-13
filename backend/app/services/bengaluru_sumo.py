"""Map live TomTom speed observations onto the nearby OSM SUMO road edges."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from app.core.errors import LiveTrafficUnavailableError
from app.digital_twin.network import NetworkModel
from app.services.tomtom_traffic import _point_polyline_distance_m


MATCH_TOLERANCE_M = 150.0
ROUTE_MATCH_TOLERANCE_M = 35.0


def match_live_speeds(network: NetworkModel, traffic_snapshot: dict) -> tuple[dict[str, float], list[dict]]:
    speed_limits: dict[str, float] = {}
    matches = []
    for sensor in traffic_snapshot["sensors"]:
        reading = sensor["latest"]
        if not reading:
            continue
        observed_at = datetime.fromisoformat(reading["observed_at"])
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        age_s = max(0.0, (datetime.now(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds())
        if age_s > 2 * traffic_snapshot["poll_interval_s"]:
            continue

        point = [sensor["latitude"], sensor["longitude"]]
        best_edge, best_distance = None, float("inf")
        for edge in network.edges:
            if not edge.shape_latlon:
                continue
            distance = _point_polyline_distance_m(point, [list(coord) for coord in edge.shape_latlon])
            if distance < best_distance:
                best_edge, best_distance = edge, distance
        if best_edge is None or best_distance > MATCH_TOLERANCE_M:
            continue

        speed_ms = max(0.1, min(best_edge.speed, float(reading["current_speed_kph"]) / 3.6))
        speed_limits[best_edge.id] = min(speed_limits.get(best_edge.id, best_edge.speed), speed_ms)
        matches.append({
            "sensor_id": sensor["id"],
            "road_name": sensor["road_name"],
            "edge_id": best_edge.id,
            "distance_m": round(best_distance, 1),
            "observed_speed_kph": float(reading["current_speed_kph"]),
            "applied_speed_kph": round(speed_ms * 3.6, 1),
            "observed_at": reading["observed_at"],
        })

    if not speed_limits:
        raise LiveTrafficUnavailableError(
            "No fresh TomTom reading could be matched to the Bengaluru OSM SUMO roads.",
            hint="Wait for a new poll and check that the OSM network was generated around all five configured sensors.",
        )
    for match in matches:
        match["applied_speed_kph"] = round(speed_limits[match["edge_id"]] * 3.6, 1)
    return speed_limits, matches


def rank_routes_with_sumo_forecast(
    route_response: dict,
    network: NetworkModel,
    predicted_edges: list[dict],
    *,
    simulation_run_id: str,
    horizon_s: int,
) -> dict:
    """Re-rank TomTom route candidates by applying GNN congestion changes on matched OSM roads."""
    prediction_by_id = {edge["id"]: edge for edge in predicted_edges}
    road_shapes = [
        (edge.id, [list(point) for point in edge.shape_latlon], prediction_by_id.get(edge.id))
        for edge in network.edges
        if edge.shape_latlon and edge.id in prediction_by_id
    ]
    routes = route_response["routes"]
    for route in routes:
        geometry = route["geometry"]
        segment_distances = []
        for start, end in zip(geometry, geometry[1:]):
            lat_scale = 111_320.0
            lon_scale = lat_scale * math.cos(math.radians((start[0] + end[0]) / 2))
            segment_distances.append(math.hypot(
                (end[1] - start[1]) * lon_scale,
                (end[0] - start[0]) * lat_scale,
            ))
        total_distance_m = sum(segment_distances)
        covered_distance_m = 0.0
        adjustment_s = 0.0
        matched_edges: set[str] = set()
        for start, end, segment_distance_m in zip(geometry, geometry[1:], segment_distances):
            if segment_distance_m <= 0:
                continue
            sample_count = max(1, math.ceil(segment_distance_m / 25.0))
            sample_distance_m = segment_distance_m / sample_count
            for sample_index in range(sample_count):
                fraction = (sample_index + 0.5) / sample_count
                point = [
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                ]
                best_id, best_prediction, best_distance = None, None, float("inf")
                for edge_id, shape, prediction in road_shapes:
                    distance = _point_polyline_distance_m(point, shape)
                    if distance < best_distance:
                        best_id, best_prediction, best_distance = edge_id, prediction, distance
                if best_prediction is None or best_distance > ROUTE_MATCH_TOLERANCE_M:
                    continue
                current_ci = float(best_prediction["ci"])
                predicted_ci = float(best_prediction["pred_ci"])
                if not 0 <= current_ci <= 1 or not 0 <= predicted_ci <= 1:
                    continue
                covered_distance_m += sample_distance_m
                matched_edges.add(best_id)
                current_speed_ratio = max(0.1, 1.0 - current_ci)
                predicted_speed_ratio = max(0.1, 1.0 - predicted_ci)
                forecast_time_ratio = min(5.0, current_speed_ratio / predicted_speed_ratio)
                adjustment_s += (
                    route["travel_time_s"] * sample_distance_m / total_distance_m
                    * (forecast_time_ratio - 1.0)
                )

        coverage = covered_distance_m / total_distance_m if total_distance_m else 0.0
        route["simulation_forecast_edge_ids"] = sorted(matched_edges)
        route["simulation_forecast_edge_count"] = len(matched_edges)
        route["simulation_forecast_coverage_pct"] = round(100.0 * coverage, 1)
        route["simulation_forecast_adjustment_s"] = adjustment_s
        route["forecast_adjustment_s"] = adjustment_s
        route["forecast_sensor_ids"] = []
        route["forecast_sensor_count"] = 0
        route["predicted_travel_time_s"] = max(0.0, route["travel_time_s"] + adjustment_s)

    routes.sort(key=lambda route: (route["predicted_travel_time_s"], route["travel_time_s"]))
    for recommendation_rank, route in enumerate(routes, start=1):
        route["recommendation_rank"] = recommendation_rank
        route["recommended"] = recommendation_rank == 1

    max_coverage = max((route["simulation_forecast_coverage_pct"] for route in routes), default=0.0)
    if max_coverage == 0:
        notice = (
            "TomTom supplied the route options and current ETAs. No route segment matched the OSM roads "
            "covered by this SUMO/GNN run, so recommendations fall back to TomTom current ETA."
        )
    else:
        notice = (
            "TomTom supplied route geometry and current-traffic ETAs. NexFlow re-ranked these options using "
            f"the SUMO/GNN forecast {horizon_s} seconds ahead on matching OSM roads; up to "
            f"{max_coverage:.1f}% of a route was covered. Unmatched portions retain TomTom's current ETA. "
            "This is a route-choice estimate, not live traffic control."
        )
    return {
        **route_response,
        "forecast_source": "bengaluru_sumo_gnn",
        "simulation_run_id": simulation_run_id,
        "forecast_horizon_s": horizon_s,
        "notice": notice,
    }
