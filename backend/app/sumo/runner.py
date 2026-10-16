"""SUMO/TraCI adapter: starts SUMO headless (or with the GUI), steps the simulation, applies
signal-timing / rerouting interventions, collects measurements and always cleans up.

Concurrency: every run gets its own TraCI label, TCP port and run directory, so parallel
runs never share a connection or temporary files.  A semaphore bounds how many SUMO
processes run at once (``NEXFLOW_MAX_CONCURRENT_SUMO``).
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
import uuid
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from app.core.config import Settings, get_settings
from app.core.errors import SimulationCancelled, SimulationError, TwinSyncError
from app.core.logging import get_logger
from app.digital_twin.network import NetworkModel
from app.interventions.models import REROUTE, SIGNAL, Intervention, SignalLimits, validate_intervention
from app.sumo.collector import EdgeStep, MeasurementCollector
from app.sumo.config_check import validate_sumocfg
from app.sumo.environment import require_sumo
from app.sumo.scenario import ScenarioConfig, write_route_file

log = get_logger("sumo.runner")

_START_LOCK = threading.Lock()  # traci.start() is documented as not thread-safe
_SLOT_LOCK = threading.Lock()
_SLOTS: dict[int, threading.BoundedSemaphore] = {}
_CFG_OK: dict[str, float] = {}


def _slot(n: int) -> threading.BoundedSemaphore:
    with _SLOT_LOCK:
        return _SLOTS.setdefault(n, threading.BoundedSemaphore(n))


@dataclass
class RunResult:
    run_id: str
    scenario: dict
    intervention: dict | None
    metrics: dict
    junction_queues: dict[str, float]
    obs_times: list[float]
    observations: np.ndarray  # [T, N, F]
    tls_states: dict[str, str]  # final red/yellow/green state strings
    tls_programs: dict[str, dict]  # active programs at the end
    runtime_s: float
    sim_steps: int
    gui: bool = False
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "scenario": self.scenario,
            "intervention": self.intervention,
            "metrics": self.metrics,
            "junction_queues": self.junction_queues,
            "runtime_s": round(self.runtime_s, 3),
            "sim_steps": self.sim_steps,
            "intervals_observed": len(self.obs_times),
            "gui": self.gui,
            "warnings": self.warnings,
        }


class SumoRunner:
    def __init__(self, net: NetworkModel, settings: Settings | None = None, limits: SignalLimits | None = None):
        self.net = net
        self.s = settings or get_settings()
        self.limits = limits or SignalLimits()

    # ---- public API -----------------------------------------------------------------
    def run(
        self,
        scenario: ScenarioConfig,
        intervention: Intervention | None = None,
        *,
        activate_at_s: float = 0.0,
        metrics_from_s: float = 0.0,
        collect_observations: bool = True,
        interval_s: int | None = None,
        stop_event: threading.Event | None = None,
        progress: Callable[[float], None] | None = None,
        max_wall_s: float = 900.0,
        run_id: str | None = None,
        gui: bool | None = None,
    ) -> RunResult:
        """Run one scenario to completion.

        ``activate_at_s``: simulation time at which the intervention takes effect.
        ``metrics_from_s``: start of the evaluation window for network metrics.
        """
        import traci  # imported lazily so the API can start without SUMO installed

        status = require_sumo()
        self._check_config_once()
        if intervention is not None:
            validate_intervention(self.net, intervention, self.limits)
        run_id = run_id or uuid.uuid4().hex[:10]
        use_gui = self.s.sumo_gui if gui is None else gui
        binary = status.sumo_gui_binary if use_gui and status.sumo_gui_binary else status.sumo_binary
        if use_gui and not status.sumo_gui_binary:
            use_gui = False  # reported through result.warnings below
        warnings: list[str] = []
        if (gui if gui is not None else self.s.sumo_gui) and not use_gui:
            warnings.append("sumo-gui not available; ran headless")

        run_dir = self.s.runs_dir / f"run_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        route_file = run_dir / "routes.rou.xml"
        write_route_file(self.net, scenario, route_file)
        interval = interval_s or self.s.interval_s
        cmd = [
            binary, "-c", str(self.s.sumocfg_file), "-r", str(route_file),
            "--seed", str(scenario.seed), "--begin", "0", "--end", str(scenario.duration_s),
            "--step-length", str(scenario.step_length_s), "--no-step-log", "true", "--no-warnings", "true",
            "--duration-log.disable", "true", "--waiting-time-memory", "3600",
        ]
        if use_gui:
            cmd += ["--start", "true", "--quit-on-end", "true"]
        label = f"nexflow-{run_id}"
        collector = MeasurementCollector(
            self.net, scenario.step_length_s, interval, metrics_from_s, collect_observations
        )
        t_wall = time.perf_counter()
        sem = _slot(self.s.max_concurrent_sumo)
        sem.acquire()
        conn = None
        steps = 0
        applied = intervention is None
        try:
            with _START_LOCK:
                try:
                    from sumolib.miscutils import getFreeSocketPort

                    port = getFreeSocketPort()
                    traci.start(cmd, port=port, label=label, doSwitch=False, numRetries=20)
                    conn = traci.getConnection(label)
                except Exception as exc:
                    raise SimulationError(
                        f"SUMO could not be started ({type(exc).__name__}).",
                        hint="Check the SUMO installation and the simulation configuration.",
                    ) from exc
            self._verify_ids(conn)
            self._subscribe(conn)
            reroute_vehicles = REROUTE == (intervention.type if intervention else None)
            next_reroute = activate_at_s
            end = float(scenario.duration_s)
            t = 0.0
            while t < end - 1e-9:
                if stop_event is not None and stop_event.is_set():
                    raise SimulationCancelled("Simulation was cancelled")
                if time.perf_counter() - t_wall > max_wall_s:
                    raise SimulationError(f"Simulation exceeded the wall-clock limit of {max_wall_s:g}s")
                if not applied and t + 1e-9 >= activate_at_s and intervention.type == SIGNAL:
                    self._apply_signal(conn, intervention)
                    applied = True
                if reroute_vehicles and t + 1e-9 >= next_reroute:
                    self._reroute(conn, intervention)
                    next_reroute += float(intervention.params["period_s"])
                conn.simulationStep()
                steps += 1
                t = conn.simulation.getTime()
                collector.update(
                    t,
                    self._edge_steps(conn),
                    list(conn.simulation.getDepartedIDList()),
                    list(conn.simulation.getArrivedIDList()),
                    teleported=int(conn.simulation.getStartingTeleportNumber()),
                    vehicles_in_network=int(conn.vehicle.getIDCount()),
                )
                if progress and steps % 50 == 0:
                    progress(min(t / end, 1.0))
            tls_states = {j: conn.trafficlight.getRedYellowGreenState(j) for j in self.net.tls_ids}
            tls_programs = self._tls_programs(conn)
            times, obs = collector.observations()
            return RunResult(
                run_id=run_id,
                scenario=scenario.to_dict(),
                intervention=intervention.to_dict() if intervention else None,
                metrics={**collector.window_metrics(), "total_departed": collector.total_departed},
                junction_queues=collector.junction_queues(),
                obs_times=times,
                observations=obs,
                tls_states=tls_states,
                tls_programs=tls_programs,
                runtime_s=time.perf_counter() - t_wall,
                sim_steps=steps,
                gui=use_gui,
                warnings=warnings,
            )
        except (SimulationError, SimulationCancelled, TwinSyncError):
            raise
        except Exception as exc:  # traci.FatalTraCIError, socket errors, ...
            log.error("simulation failed", extra={"run_id": run_id, "error": type(exc).__name__}, exc_info=True)
            raise SimulationError(
                f"The simulation ended unexpectedly ({type(exc).__name__}).",
                hint="See the server log for details.",
            ) from exc
        finally:
            self._close(conn)
            sem.release()
            if not self.s.keep_run_dirs:
                shutil.rmtree(run_dir, ignore_errors=True)

    # ---- helpers -----------------------------------------------------------------
    def _check_config_once(self) -> None:
        cfg = self.s.sumocfg_file
        key = str(cfg)
        mtime = cfg.stat().st_mtime if cfg.exists() else -1
        if _CFG_OK.get(key) != mtime:
            validate_sumocfg(cfg, dry_run=True)
            _CFG_OK[key] = mtime

    def _verify_ids(self, conn) -> None:
        sumo_edges = {e for e in conn.edge.getIDList() if not e.startswith(":")}
        missing = set(self.net.edge_ids) - sumo_edges
        extra = sumo_edges - set(self.net.edge_ids)
        if missing or extra:
            raise TwinSyncError(
                f"Road IDs of the running SUMO network do not match the loaded network "
                f"(missing {len(missing)}, unexpected {len(extra)}).",
                hint="Regenerate the network or reload the digital twin.",
            )
        tls = set(conn.trafficlight.getIDList())
        if not set(self.net.tls_ids) <= tls:
            raise TwinSyncError("Traffic-light IDs of the running SUMO network do not match the loaded network.")

    def _subscribe(self, conn) -> None:
        import traci.constants as tc

        self._vars = [
            tc.LAST_STEP_VEHICLE_NUMBER, tc.LAST_STEP_MEAN_SPEED, tc.LAST_STEP_OCCUPANCY,
            tc.LAST_STEP_VEHICLE_HALTING_NUMBER, tc.LAST_STEP_VEHICLE_ID_LIST,
        ]
        self._tc = tc
        for eid in self.net.edge_ids:
            conn.edge.subscribe(eid, self._vars)

    def _edge_steps(self, conn) -> dict[str, EdgeStep]:
        tc = self._tc
        res = conn.edge.getAllSubscriptionResults()
        out: dict[str, EdgeStep] = {}
        for eid, d in res.items():
            out[eid] = EdgeStep(
                count=int(d[tc.LAST_STEP_VEHICLE_NUMBER]),
                speed=float(d[tc.LAST_STEP_MEAN_SPEED]),
                occupancy=float(d[tc.LAST_STEP_OCCUPANCY]),
                halting=int(d[tc.LAST_STEP_VEHICLE_HALTING_NUMBER]),
                ids=tuple(d[tc.LAST_STEP_VEHICLE_ID_LIST]),
            )
        return out

    def _tls_programs(self, conn) -> dict[str, dict]:
        out = {}
        for j in self.net.tls_ids:
            pid = conn.trafficlight.getProgram(j)
            logic = next((lg for lg in conn.trafficlight.getAllProgramLogics(j) if lg.programID == pid), None)
            phases = (
                [{"index": i, "duration": float(p.duration), "state": p.state} for i, p in enumerate(logic.phases)]
                if logic else []
            )
            out[j] = {"program_id": pid, "phases": phases, "cycle_s": sum(p["duration"] for p in phases)}
        return out

    def _apply_signal(self, conn, iv: Intervention) -> None:
        from traci._trafficlight import Logic, Phase

        j = iv.junction_id
        current = conn.trafficlight.getProgram(j)
        logic = next(lg for lg in conn.trafficlight.getAllProgramLogics(j) if lg.programID == current)
        phases = []
        for i, p in enumerate(logic.phases):
            dur = float(iv.params[i]) if i in iv.params else float(p.duration)
            phases.append(Phase(dur, p.state, dur, dur))
        new = Logic("nexflow", 0, 0, phases=phases)
        conn.trafficlight.setProgramLogic(j, new)
        conn.trafficlight.setProgram(j, "nexflow")
        conn.trafficlight.setPhase(j, 0)
        conn.trafficlight.setPhaseDuration(j, phases[0].duration)
        log.info("signal plan applied", extra={"junction": j, "params": iv.params})

    def _reroute(self, conn, iv: Intervention) -> None:
        share = int(round(float(iv.params["share"]) * 100))
        for vid in conn.vehicle.getIDList():
            if zlib.crc32(vid.encode()) % 100 < share:
                try:
                    conn.vehicle.rerouteTraveltime(vid)
                except Exception:  # vehicle may have left the network meanwhile
                    continue

    @staticmethod
    def _close(conn) -> None:
        if conn is None:
            return
        proc = getattr(conn, "_process", None)
        try:
            conn.close(wait=False)
        except Exception:
            pass
        if proc is not None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
