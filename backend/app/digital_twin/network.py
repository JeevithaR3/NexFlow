"""Static road-network model loaded from the SUMO network file (via ``sumolib``).

The *road segment* (a SUMO non-internal edge) is the GNN node; the *junction* is the
unit on which signal interventions act.  This module is the single source of truth for
identifiers, topology, geometry and the traffic-light configuration used by every other
component (GNN, digital twin, memory, API, front-end).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import SumoConfigError

SIDES = ("left", "right", "top", "bottom")


@dataclass(frozen=True)
class EdgeInfo:
    id: str
    from_node: str
    to_node: str
    length: float  # metres
    speed: float  # free-flow speed, m/s
    lanes: int
    shape: tuple[tuple[float, float], ...]  # SUMO x/y metres


@dataclass(frozen=True)
class JunctionInfo:
    id: str
    x: float
    y: float
    type: str
    has_tls: bool
    incoming: tuple[str, ...]
    outgoing: tuple[str, ...]


@dataclass(frozen=True)
class GreenPhase:
    index: int
    duration: float
    axis: str  # "NS" | "EW" | "MIXED" - derived from the controlled incoming edges
    incoming_edges: tuple[str, ...]


@dataclass
class NetworkModel:
    path: Path
    edges: list[EdgeInfo]
    junctions: list[JunctionInfo]
    tls_programs: dict[str, list[dict]]  # tls id -> [{"duration","state","index"}]
    tls_green_phases: dict[str, list[GreenPhase]]
    edge_links: list[tuple[str, str]]  # (from_edge, to_edge) allowed connections
    net_hash: str
    tls_hash: str
    origin_by_side: dict[str, list[str]] = field(default_factory=dict)
    dest_by_side: dict[str, list[str]] = field(default_factory=dict)

    # ---- lookups ---------------------------------------------------------------
    def __post_init__(self) -> None:
        self.edge_ids = [e.id for e in self.edges]
        self.edge_index = {e: i for i, e in enumerate(self.edge_ids)}
        self.edge_by_id = {e.id: e for e in self.edges}
        self.junction_by_id = {j.id: j for j in self.junctions}
        self.tls_ids = sorted(self.tls_programs)
        self.junction_ids = [j.id for j in self.junctions]
        # junction adjacency: two junctions are neighbours if an edge connects them
        nb: dict[str, set[str]] = {j.id: set() for j in self.junctions}
        for e in self.edges:
            if e.from_node in nb and e.to_node in nb:
                nb[e.from_node].add(e.to_node)
                nb[e.to_node].add(e.from_node)
        self._neighbors = {k: sorted(v) for k, v in nb.items()}

    @property
    def n_edges(self) -> int:
        return len(self.edges)

    def neighbors(self, junction_id: str) -> list[str]:
        return self._neighbors.get(junction_id, [])

    def incoming_edges(self, junction_id: str) -> list[str]:
        return list(self.junction_by_id[junction_id].incoming)

    # ---- geometry --------------------------------------------------------------
    def bounds(self) -> tuple[float, float, float, float]:
        xs = [p[0] for e in self.edges for p in e.shape]
        ys = [p[1] for e in self.edges for p in e.shape]
        return min(xs), min(ys), max(xs), max(ys)

    def to_latlon(self, x: float, y: float, lat0: float, lon0: float) -> tuple[float, float]:
        """Local equirectangular placement of SUMO metres around a reference origin.

        This is an *explicit synthetic placement*: the generated grid is not aligned to real
        OpenStreetMap streets.
        """
        dlat = y / 111_320.0
        dlon = x / (111_320.0 * math.cos(math.radians(lat0)))
        return lat0 + dlat, lon0 + dlon

    def edge_latlon_shape(self, edge_id: str, lat0: float, lon0: float, offset_m: float = 6.0) -> list[list[float]]:
        """Edge polyline in lat/lon, shifted ``offset_m`` to the right so that the two
        directions of a road are drawn side by side."""
        e = self.edge_by_id[edge_id]
        pts = list(e.shape)
        out: list[list[float]] = []
        for i, (x, y) in enumerate(pts):
            a = pts[max(i - 1, 0)]
            b = pts[min(i + 1, len(pts) - 1)]
            dx, dy = b[0] - a[0], b[1] - a[1]
            n = math.hypot(dx, dy) or 1.0
            rx, ry = dy / n, -dx / n  # right-hand normal
            lat, lon = self.to_latlon(x + rx * offset_m, y + ry * offset_m, lat0, lon0)
            out.append([round(lat, 7), round(lon, 7)])
        return out

    # ---- traffic lights ----------------------------------------------------------
    def green_phases(self, tls_id: str) -> list[GreenPhase]:
        return self.tls_green_phases.get(tls_id, [])

    def tls_summary(self, tls_id: str) -> dict:
        phases = self.tls_programs[tls_id]
        return {
            "junction_id": tls_id,
            "phases": phases,
            "cycle_s": sum(p["duration"] for p in phases),
            "green_phases": [gp.__dict__ for gp in self.green_phases(tls_id)],
        }


def _hash_bytes(*chunks: bytes) -> str:
    h = hashlib.sha256()
    for c in chunks:
        h.update(c)
    return h.hexdigest()[:16]


def _axis_of(edge: EdgeInfo) -> str:
    (x0, y0), (x1, y1) = edge.shape[0], edge.shape[-1]
    return "NS" if abs(y1 - y0) > abs(x1 - x0) else "EW"


def load_network(path: Path | str) -> NetworkModel:
    """Load and validate a SUMO ``.net.xml`` file."""
    import sumolib

    path = Path(path)
    if not path.exists():
        raise SumoConfigError(
            f"SUMO network file not found: {path}",
            hint="Run `python scripts/generate_network.py` to create the demonstration network.",
        )
    try:
        net = sumolib.net.readNet(str(path), withInternal=False, withPrograms=True)
    except Exception as exc:
        raise SumoConfigError(f"Could not parse SUMO network '{path.name}': {type(exc).__name__}") from exc

    edges: list[EdgeInfo] = []
    for e in sorted(net.getEdges(), key=lambda x: x.getID()):
        if e.getFunction() not in ("", "normal"):
            continue
        shape = tuple((float(x), float(y)) for x, y in e.getRawShape())
        edges.append(
            EdgeInfo(
                id=e.getID(),
                from_node=e.getFromNode().getID(),
                to_node=e.getToNode().getID(),
                length=float(e.getLength()),
                speed=float(e.getSpeed()),
                lanes=int(e.getLaneNumber()),
                shape=shape,
            )
        )
    if not edges:
        raise SumoConfigError("The network contains no drivable edges.")
    edge_by_id = {e.id: e for e in edges}

    junctions: list[JunctionInfo] = []
    for n in sorted(net.getNodes(), key=lambda x: x.getID()):
        inc = tuple(sorted(e.getID() for e in n.getIncoming() if e.getID() in edge_by_id))
        out = tuple(sorted(e.getID() for e in n.getOutgoing() if e.getID() in edge_by_id))
        x, y = n.getCoord()
        junctions.append(
            JunctionInfo(n.getID(), float(x), float(y), n.getType(), n.getType() == "traffic_light", inc, out)
        )

    tls_programs: dict[str, list[dict]] = {}
    tls_green: dict[str, list[GreenPhase]] = {}
    for tls in net.getTrafficLights():
        progs = tls.getPrograms()
        if not progs:
            continue
        prog = progs[sorted(progs)[0]] if "0" not in progs else progs["0"]
        phases = [
            {"index": i, "duration": float(p.duration), "state": p.state} for i, p in enumerate(prog.getPhases())
        ]
        tls_programs[tls.getID()] = phases
        link_edges: dict[int, str] = {}
        for in_lane, _out_lane, link_no in tls.getConnections():
            link_edges[int(link_no)] = in_lane.getEdge().getID()
        greens: list[GreenPhase] = []
        for ph in phases:
            if not any(c in "Gg" for c in ph["state"]):
                continue
            if all(c in "Ggy" for c in ph["state"]):
                continue
            ins = sorted({link_edges[i] for i, c in enumerate(ph["state"]) if c in "Gg" and i in link_edges})
            axes = {_axis_of(edge_by_id[x]) for x in ins if x in edge_by_id}
            axis = axes.pop() if len(axes) == 1 else "MIXED"
            greens.append(GreenPhase(ph["index"], ph["duration"], axis, tuple(ins)))
        tls_green[tls.getID()] = greens

    links: set[tuple[str, str]] = set()
    for e in net.getEdges():
        if e.getID() not in edge_by_id:
            continue
        for succ in e.getOutgoing():
            if succ.getID() in edge_by_id:
                links.add((e.getID(), succ.getID()))

    origin: dict[str, list[str]] = {s: [] for s in SIDES}
    dest: dict[str, list[str]] = {s: [] for s in SIDES}
    node_type = {j.id: j for j in junctions}
    for e in edges:
        for side in SIDES:
            if node_type[e.from_node].type == "dead_end" and e.from_node.startswith(side):
                origin[side].append(e.id)
            if node_type[e.to_node].type == "dead_end" and e.to_node.startswith(side):
                dest[side].append(e.id)

    raw = path.read_bytes()
    tls_sig = repr(sorted((k, [(p["duration"], p["state"]) for p in v]) for k, v in tls_programs.items())).encode()
    return NetworkModel(
        path=path,
        edges=edges,
        junctions=junctions,
        tls_programs=tls_programs,
        tls_green_phases=tls_green,
        edge_links=sorted(links),
        net_hash=_hash_bytes(raw),
        tls_hash=_hash_bytes(tls_sig),
        origin_by_side={k: sorted(v) for k, v in origin.items()},
        dest_by_side={k: sorted(v) for k, v in dest.items()},
    )
