"""Alternative-route proposal on the digital twin (an *estimate*, not a simulation result)."""
from __future__ import annotations

import heapq

import numpy as np

from app.core.errors import DataValidationError
from app.digital_twin.network import NetworkModel

MIN_SPEED_FRACTION = 0.15


def _dijkstra(net: NetworkModel, src: str, dst: str, cost: dict[str, float]) -> list[str] | None:
    succ: dict[str, list[str]] = {}
    for a, b in net.edge_links:
        succ.setdefault(a, []).append(b)
    best = {src: cost[src]}
    prev: dict[str, str] = {}
    heap = [(cost[src], src)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == dst:
            path = [u]
            while u in prev:
                u = prev[u]
                path.append(u)
            return path[::-1]
        if d > best.get(u, float("inf")):
            continue
        for v in succ.get(u, []):
            nd = d + cost[v]
            if nd < best.get(v, float("inf")):
                best[v], prev[v] = nd, u
                heapq.heappush(heap, (nd, v))
    return None


def propose_route(net: NetworkModel, from_edge: str, to_edge: str, pred_ci: np.ndarray | None) -> dict:
    for e in (from_edge, to_edge):
        if e not in net.edge_by_id:
            raise DataValidationError(f"Unknown road segment '{e}'")
    free = {e.id: e.length / e.speed for e in net.edges}
    if pred_ci is None:
        pred = free
    else:
        pred = {e.id: e.length / (e.speed * max(1.0 - float(pred_ci[i]), MIN_SPEED_FRACTION)) for i, e in enumerate(net.edges)}
    base = _dijkstra(net, from_edge, to_edge, free)
    alt = _dijkstra(net, from_edge, to_edge, pred)
    if base is None or alt is None:
        raise DataValidationError("No drivable route exists between these road segments")
    t = lambda path, c: round(sum(c[x] for x in path), 1)  # noqa: E731
    return {
        "default_route": base, "alternative_route": alt, "differs": base != alt,
        "default_time_predicted_s": t(base, pred), "alternative_time_predicted_s": t(alt, pred),
        "default_time_free_flow_s": t(base, free),
        "basis": "estimate from the GNN-predicted congestion index (speed = free-flow x (1 - CI)); not verified in SUMO"
        if pred_ci is not None else "free-flow times only (no prediction available)",
    }
