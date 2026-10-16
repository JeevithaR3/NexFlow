"""Alternative-route proposal from the forecast (an *estimate*, not a simulation result)."""
from __future__ import annotations

import heapq

import numpy as np

from app.core.errors import ConflictError, DataValidationError
from app.digital_twin.network import NetworkModel


def _tt(net: NetworkModel, ci: np.ndarray | None) -> dict[str, float]:
    out = {}
    for e in net.edges:
        c = float(ci[net.edge_index[e.id]]) if ci is not None else 0.0
        out[e.id] = e.length / (e.speed * max(1.0 - 0.9 * c, 0.1))
    return out


def shortest(net: NetworkModel, src: str, dst: str, tt: dict[str, float]) -> list[str] | None:
    succ: dict[str, list[str]] = {}
    for a, b in net.edge_links:
        succ.setdefault(a, []).append(b)
    dist = {src: tt[src]}
    prev: dict[str, str] = {}
    pq = [(tt[src], src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == dst:
            path = [u]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            return path[::-1]
        if d > dist.get(u, 1e18):
            continue
        for v in succ.get(u, []):
            nd = d + tt[v]
            if nd < dist.get(v, 1e18):
                dist[v], prev[v] = nd, u
                heapq.heappush(pq, (nd, v))
    return None


def alternative_route(net: NetworkModel, pred_ci: np.ndarray | None, src: str, dst: str, lat0: float, lon0: float) -> dict:
    if pred_ci is None:
        raise ConflictError("No forecast available to base a route on.", hint="Run a prediction first.")
    for e in (src, dst):
        if e not in net.edge_by_id:
            raise DataValidationError(f"Unknown road segment '{e}'")
    free, congested = _tt(net, None), _tt(net, pred_ci)
    base = shortest(net, src, dst, free)
    alt = shortest(net, src, dst, congested)
    if base is None or alt is None:
        raise DataValidationError("No drivable route exists between these road segments")
    est = lambda p, tt: round(sum(tt[x] for x in p), 1)  # noqa: E731
    geo = lambda p: [net.edge_latlon_shape(x, lat0, lon0) for x in p]  # noqa: E731
    return {
        "kind": "estimated_from_forecast",
        "note": "Travel times are estimated from predicted congestion (speed = free-flow x (1 - 0.9 CI)); not a SUMO result.",
        "default_route": {"edges": base, "estimated_s_under_forecast": est(base, congested), "geometry": geo(base)},
        "alternative_route": {"edges": alt, "estimated_s_under_forecast": est(alt, congested), "geometry": geo(alt)},
        "differs": base != alt,
        "estimated_saving_s": round(est(base, congested) - est(alt, congested), 1),
    }
