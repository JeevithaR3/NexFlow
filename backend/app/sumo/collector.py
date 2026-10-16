"""Traffic-measurement collector: turns per-step edge data into interval observations and
window metrics.  It is independent of TraCI (takes plain dictionaries), so it is unit-testable.

Observation features (per edge, per interval):
  0 flow_vph       vehicles that *entered* the edge during the interval, scaled to veh/h
  1 mean_speed     vehicle-weighted mean speed in m/s (free-flow speed if no vehicle was present)
  2 occupancy_pct  mean lane occupancy in %
  3 vehicle_count  mean number of vehicles on the edge
  4 halting_count  mean number of halted vehicles (speed < 0.1 m/s) -> queue proxy
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.digital_twin.network import NetworkModel

FEATURES = ("flow_vph", "mean_speed", "occupancy_pct", "vehicle_count", "halting_count")
F_FLOW, F_SPEED, F_OCC, F_COUNT, F_HALT = range(5)


@dataclass
class EdgeStep:
    count: int
    speed: float
    occupancy: float
    halting: int
    ids: tuple[str, ...]


class MeasurementCollector:
    def __init__(
        self,
        net: NetworkModel,
        step_length_s: float,
        interval_s: int,
        metrics_from_s: float = 0.0,
        collect_observations: bool = True,
    ) -> None:
        self.net = net
        self.dt = float(step_length_s)
        self.interval_s = int(interval_s)
        self.metrics_from = float(metrics_from_s)
        self.collect_obs = collect_observations
        n = net.n_edges
        self._free = np.array([e.speed for e in net.edges], dtype=np.float64)
        self._reset_interval()
        self._prev_ids: list[set[str]] = [set() for _ in range(n)]
        self._next_boundary = float(interval_s)
        self.obs: list[np.ndarray] = []
        self.obs_times: list[float] = []
        # window (decision-period) accumulators
        self._wait_veh_s = 0.0
        self._speed_num = 0.0
        self._speed_den = 0.0
        self._seen: set[str] = set()
        self._depart: dict[str, float] = {}
        self._travel_times: list[float] = []
        self._arrived_window = 0
        self._queue_sum_by_edge = np.zeros(n)
        self._window_steps = 0
        self.teleports = 0
        self.total_departed = 0
        self.vehicles_in_network = 0
        self._inc_idx = {
            j: [net.edge_index[e] for e in net.junction_by_id[j].incoming] for j in net.tls_ids
        }

    def _reset_interval(self) -> None:
        n = self.net.n_edges
        self._steps = 0
        self._sum_count = np.zeros(n)
        self._sum_speed_w = np.zeros(n)
        self._sum_occ = np.zeros(n)
        self._sum_halt = np.zeros(n)
        self._entries = np.zeros(n)

    def update(
        self,
        t: float,
        edges: dict[str, EdgeStep],
        departed: list[str],
        arrived: list[str],
        teleported: int = 0,
        vehicles_in_network: int | None = None,
    ) -> None:
        """Register the state after a simulation step that ended at time ``t``."""
        in_window = t > self.metrics_from + 1e-9
        for vid in departed:
            self._depart[vid] = t
        self.total_departed += len(departed)
        self.teleports += teleported
        halting_total = 0
        for i, eid in enumerate(self.net.edge_ids):
            st = edges.get(eid)
            if st is None:
                continue
            cur = set(st.ids)
            self._entries[i] += len(cur - self._prev_ids[i])
            self._prev_ids[i] = cur
            self._sum_count[i] += st.count
            self._sum_speed_w[i] += st.speed * st.count if st.count else 0.0
            self._sum_occ[i] += st.occupancy
            self._sum_halt[i] += st.halting
            halting_total += st.halting
            if in_window:
                self._queue_sum_by_edge[i] += st.halting
                if st.count:
                    self._speed_num += st.speed * st.count
                    self._speed_den += st.count
                self._seen.update(st.ids)
        self._steps += 1
        if in_window:
            self._window_steps += 1
            self._wait_veh_s += halting_total * self.dt
            for vid in arrived:
                d = self._depart.get(vid)
                if d is not None:
                    self._travel_times.append(t - d)
                    self._arrived_window += 1
        if vehicles_in_network is not None:
            self.vehicles_in_network = vehicles_in_network
        if t + 1e-9 >= self._next_boundary:
            self._finish_interval(t)

    def _finish_interval(self, t: float) -> None:
        if self.collect_obs and self._steps:
            s = float(self._steps)
            count = self._sum_count / s
            speed = np.where(
                self._sum_count > 0, self._sum_speed_w / np.maximum(self._sum_count, 1e-9), self._free
            )
            arr = np.zeros((self.net.n_edges, len(FEATURES)), dtype=np.float32)
            arr[:, F_FLOW] = self._entries * 3600.0 / (self._steps * self.dt)
            arr[:, F_SPEED] = speed
            arr[:, F_OCC] = self._sum_occ / s
            arr[:, F_COUNT] = count
            arr[:, F_HALT] = self._sum_halt / s
            self.obs.append(arr)
            self.obs_times.append(t)
        self._reset_interval()
        self._next_boundary += self.interval_s

    # ---- results -----------------------------------------------------------------
    def observations(self) -> tuple[list[float], np.ndarray]:
        if not self.obs:
            return [], np.zeros((0, self.net.n_edges, len(FEATURES)), dtype=np.float32)
        return list(self.obs_times), np.stack(self.obs)

    def window_metrics(self) -> dict:
        w_steps = max(self._window_steps, 1)
        n_seen = len(self._seen)
        window_s = self._window_steps * self.dt
        queue_edges = self._queue_sum_by_edge / w_steps
        return {
            "avg_wait_s": (self._wait_veh_s / n_seen) if n_seen else 0.0,
            "avg_travel_time_s": float(np.mean(self._travel_times)) if self._travel_times else 0.0,
            "queue_proxy_veh": float(queue_edges.sum()),  # time-avg halted vehicles, whole network
            "throughput_veh": int(self._arrived_window),
            "mean_speed_ms": (self._speed_num / self._speed_den) if self._speed_den else 0.0,
            "vehicles_in_window": n_seen,
            "vehicles_in_network_end": int(self.vehicles_in_network),
            "teleports": int(self.teleports),
            "window_s": window_s,
        }

    def junction_queues(self) -> dict[str, float]:
        w_steps = max(self._window_steps, 1)
        q = self._queue_sum_by_edge / w_steps
        return {j: float(q[idx].sum()) for j, idx in self._inc_idx.items()}
