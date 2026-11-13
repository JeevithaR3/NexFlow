import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ScenarioIn } from "../api/client";
import { useAsync, useRunner } from "../hooks/useAsync";
import { ScenarioFields } from "../components/PredictPanel";
import { ErrorBox, SourceBadge, num, pct } from "../components/ui";

const ROWS: [string, string, number][] = [
  ["avg_wait_s", "Mean waiting time (s)", 1],
  ["avg_travel_time_s", "Mean travel time (s)", 1],
  ["queue_proxy_veh", "Queue proxy: halted vehicles (avg)", 1],
  ["throughput_veh", "Throughput (vehicles arrived)", 0],
  ["vehicles_in_network_end", "Vehicles still in network", 0],
];

function MetricsTable({ base, iv }: { base: any; iv?: any }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-[11px] text-slate-400">
          <th className="p-2">Metric (Evaluation Window)</th>
          <th className="p-2">Baseline</th>
          {iv && <th className="p-2">Intervention</th>}
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-800/60 font-mono">
        {ROWS.map(([k, label, d]) => (
          <tr key={k} className="hover:bg-slate-800/30">
            <td className="p-2 font-sans font-medium text-slate-300">{label}</td>
            <td className="p-2 text-white">{num(base?.metrics?.[k], d)}</td>
            {iv && <td className="p-2 text-cyan-400">{num(iv?.metrics?.[k], d)}</td>}
          </tr>
        ))}
        <tr className="hover:bg-slate-800/30">
          <td className="p-2 font-sans font-medium text-slate-300">Simulation Runtime (s)</td>
          <td className="p-2 text-white">{num(base?.runtime_s, 1)}</td>
          {iv && <td className="p-2 text-cyan-400">{num(iv?.runtime_s, 1)}</td>}
        </tr>
      </tbody>
    </table>
  );
}

function NeighborTable({ eff }: { eff: Record<string, any> }) {
  return (
    <table className="mt-2 w-full text-xs">
      <thead>
        <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-[11px] text-slate-400">
          <th className="p-1.5">Neighbor Junction</th>
          <th className="p-1.5">Queue Before</th>
          <th className="p-1.5">Queue After</th>
          <th className="p-1.5">&Delta;</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-800/60 font-mono">
        {Object.entries(eff).map(([j, v]) => (
          <tr key={j} className="hover:bg-slate-800/30">
            <td className="p-1.5 font-bold text-white">{j}</td>
            <td className="p-1.5 text-slate-400">{v.baseline_queue}</td>
            <td className="p-1.5 text-slate-300">{v.candidate_queue}</td>
            <td className={`p-1.5 font-bold ${v.delta > 1.5 ? "text-rose-400" : v.delta < -1.5 ? "text-emerald-400" : "text-slate-400"}`}>
              {v.delta > 0 ? "+" : ""}{v.delta}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function EvaluationView({ ev }: { ev: any }) {
  return (
    <div className="space-y-2 rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase ${ev.valid ? "bg-emerald-500/20 text-emerald-400" : "bg-rose-500/20 text-rose-400"}`}>
          {ev.valid ? "Valid Guardrails" : "Rejected by Safety Guardrails"}
        </span>
        <span className="font-semibold text-white">
          Improvement: <b className="font-mono text-cyan-400">{pct(ev.improvement)}</b>
        </span>
      </div>
      {ev.violations?.map((v: string) => (
        <div key={v} className="text-rose-400 text-[11px]">&bull; {v}</div>
      ))}
      {ev.neighbor_effects && <NeighborTable eff={ev.neighbor_effects} />}
    </div>
  );
}

export default function Scenario() {
  const net = useAsync(() => api.network());
  const tls: string[] = net.data?.junctions.filter((j) => j.has_tls).map((j) => j.id) ?? [];
  const [sc, setSc] = useState<ScenarioIn>({ pattern: "ew_heavy", demand_scale: 1.3, seed: 50001 });
  const [junction, setJunction] = useState("B1");
  const cand = useAsync(() => (tls.includes(junction) ? api.candidates(junction) : Promise.resolve(null)), [junction, tls.length]);
  const [greens, setGreens] = useState<Record<string, number>>({});
  const sim = useRunner();
  const dec = useRunner();
  const [useMem, setUseMem] = useState(true);
  const lim = net.data?.signal_limits;

  useEffect(() => {
    if (!junction && tls.length) setJunction(tls[0]);
  }, [tls, junction]);

  useEffect(() => {
    if (cand.data?.green_phases) {
      setGreens(Object.fromEntries(cand.data.green_phases.map((g: any) => [String(g.index), g.duration])));
    }
  }, [cand.data]);

  const runSim = () =>
    sim.start(() => api.runSimulation(sc, { type: "signal_timing", junction_id: junction, green_s: greens }));

  const runDecision = () =>
    dec.start(() => api.evaluate({ scenario: sc, junction_id: null, use_memory: useMem, include_rerouting: false, store_experience: true }));

  const sres = sim.run?.status === "succeeded" ? sim.run.result : null;
  const dres = dec.run?.status === "succeeded" ? dec.run.result : null;

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-white md:text-3xl">
          Scenario Simulation Studio
        </h1>
        <p className="mt-1 text-xs font-medium text-slate-400 md:text-sm">
          Run high-fidelity microscopic SUMO simulations comparing baseline signal schedules with adaptive green-timing interventions
        </p>
      </div>

      {/* Real-World Context Callout Banner */}
      <div
        role="note"
        className="rounded-2xl border border-blue-500/20 bg-gradient-to-r from-[#0c1427] to-[#080d1a] p-3.5 text-xs text-slate-300 shadow-md backdrop-blur-md"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="flex h-2 w-2 rounded-full bg-cyan-400" />
            <span className="font-semibold text-white">Simulation Safety Protocol:</span>
          </div>
          <Link to="/map?source=bengaluru" className="font-semibold text-cyan-400 hover:underline">
            View Live Corridors &rarr;
          </Link>
        </div>
        <p className="mt-1 text-slate-400 leading-relaxed">
          The shared Bengaluru readings provide real-world city context. These intervention tests run strictly on the synthetic SUMO grid; TomTom observations are not converted into traffic demand or real signal plans.
        </p>
      </div>

      {/* Scenario Parameters Console */}
      <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl">
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-600/20 text-cyan-400">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
            </svg>
          </div>
          <h2 className="text-sm font-bold text-white tracking-wide">Traffic Scenario Parameters</h2>
        </div>
        <ScenarioFields value={sc} onChange={setSc} />
      </div>

      {/* Grid: Signal Timing Change vs Result */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Section 1: Signal Timing Manual Change */}
        <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl flex flex-col justify-between">
          <div>
            <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
              <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-cyan-500/20 text-cyan-400 text-xs font-bold">
                1
              </span>
              <h3 className="text-sm font-bold text-white tracking-wide">Test a Signal-Timing Change</h3>
            </div>

            <div className="mt-4 space-y-4">
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Target Signalized Junction
                </label>
                <select
                  className="mt-1.5 w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500"
                  value={junction}
                  onChange={(e) => setJunction(e.target.value)}
                >
                  {tls.map((j: string) => (
                    <option key={j} value={j}>
                      Junction {j}
                    </option>
                  ))}
                </select>
              </div>

              {cand.data?.green_phases?.map((g: any) => (
                <div key={g.index} className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-slate-300">
                      Phase {g.index} Green ({g.axis} approaches)
                    </span>
                    <span className="font-mono font-bold text-cyan-400">
                      {greens[String(g.index)] ?? g.duration}s{" "}
                      <span className="text-slate-500 font-normal">(baseline {g.duration}s)</span>
                    </span>
                  </div>
                  <input
                    type="range"
                    className="mt-3 w-full accent-cyan-400"
                    min={lim?.min_green_s ?? 10}
                    max={lim?.max_green_s ?? 60}
                    step={1}
                    value={greens[String(g.index)] ?? g.duration}
                    onChange={(e) =>
                      setGreens({ ...greens, [String(g.index)]: Number(e.target.value) })
                    }
                  />
                  <div className="mt-1 flex justify-between text-[10px] text-slate-500 font-mono">
                    <span>Min: {lim?.min_green_s ?? 10}s</span>
                    <span>Max: {lim?.max_green_s ?? 60}s</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-6 border-t border-slate-800 pt-4">
            <button
              type="button"
              onClick={runSim}
              disabled={sim.busy || !cand.data}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 py-3 text-xs font-bold text-white shadow-lg shadow-blue-500/25 transition hover:brightness-110 disabled:opacity-50"
            >
              {sim.busy ? "Running Dual SUMO Simulations..." : "Run Baseline vs Intervention"}
            </button>
            <ErrorBox error={sim.error} />

            {/* Manual Evaluation Result */}
            {sres && (
              <div className="mt-4 space-y-3 rounded-xl border border-slate-800 bg-slate-900/80 p-4 text-xs">
                <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                  <span className="font-bold text-white">Comparative Simulation Metrics</span>
                  <SourceBadge source="simulated" />
                </div>
                <MetricsTable base={sres.baseline} iv={sres.intervention} />
                {sres.evaluation && <EvaluationView ev={sres.evaluation} />}
                <p className="text-[11px] text-slate-500">{sres.disclaimer}</p>
              </div>
            )}
          </div>
        </div>

        {/* Section 2: Automated Adaptive Policy Search */}
        <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl flex flex-col justify-between">
          <div>
            <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
              <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-purple-500/20 text-purple-400 text-xs font-bold">
                2
              </span>
              <h3 className="text-sm font-bold text-white tracking-wide">
                Automated Adaptive Policy Search
              </h3>
            </div>

            <div className="mt-4 space-y-4">
              <label className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3 cursor-pointer">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded accent-cyan-400"
                  checked={useMem}
                  onChange={(e) => setUseMem(e.target.checked)}
                />
                <div>
                  <div className="text-xs font-bold text-white">Search FAISS Experience Memory First</div>
                  <div className="text-[11px] text-slate-400">Re-verify candidate plans inside microscopic SUMO runs</div>
                </div>
              </label>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-xs text-slate-300">
                <span className="font-semibold text-white">Adaptive Policy Pipeline:</span>
                <p className="mt-1 text-slate-400 leading-relaxed text-[11px]">
                  1. Evaluates multi-junction bottleneck pressure using ST-GCN forecasts.<br />
                  2. Retrieves proven historical interventions from FAISS memory bank.<br />
                  3. Simulates green-extension timing in SUMO under strict safety guardrails.
                </p>
              </div>
            </div>
          </div>

          <div className="mt-6 border-t border-slate-800 pt-4">
            <button
              type="button"
              onClick={runDecision}
              disabled={dec.busy}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 py-3 text-xs font-bold text-white shadow-lg shadow-purple-500/25 transition hover:brightness-110 disabled:opacity-50"
            >
              {dec.busy ? "Executing Policy Search & Verification..." : "Find Best Intervention"}
            </button>
            <ErrorBox error={dec.error} />

            {/* Decision Run Results */}
            {dres && (
              <div className="mt-4 space-y-3 rounded-xl border border-slate-800 bg-slate-900/80 p-4 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
                  <div className="flex items-center gap-2">
                    <SourceBadge source={dres.source} />
                    <span className="text-slate-300">
                      Target Intersection: <b className="font-mono text-cyan-400 text-sm">{dres.target_junction}</b>{" "}
                      <span className="text-slate-500">({dres.target_rule})</span>
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-400">
                    SUMO Runs: <b className="text-white font-mono">{dres.cost?.sumo_runs}</b> &bull; Decision:{" "}
                    <b className="text-white font-mono">{dres.cost?.decision_seconds}s</b>
                  </div>
                </div>

                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 p-3 text-emerald-300">
                  {dres.selected ? (
                    <div className="space-y-0.5">
                      <div className="text-xs font-semibold text-emerald-400">Optimal Intervention Found:</div>
                      <div className="text-sm font-bold text-white">{dres.selected.intervention?.label}</div>
                      <div className="text-xs text-emerald-300">
                        Objective Improvement: <b className="font-mono text-white">{pct(dres.selected.improvement)}</b>
                      </div>
                    </div>
                  ) : (
                    <div>No candidate beat the current plan under safety guardrails: maintain existing timing schedule.</div>
                  )}
                </div>

                {/* Candidate table */}
                <div className="overflow-x-auto rounded-xl border border-slate-800">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-[11px] text-slate-400">
                        <th className="p-2.5">Candidate Plan</th>
                        <th className="p-2.5">Origin</th>
                        <th className="p-2.5">Improvement</th>
                        <th className="p-2.5">Valid</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono">
                      {dres.candidates?.map((c: any, i: number) => (
                        <tr key={i} className="hover:bg-slate-800/30">
                          <td className="p-2.5 font-sans font-medium text-white">{c.intervention?.label}</td>
                          <td className="p-2.5 text-slate-400">{c.origin}</td>
                          <td className="p-2.5 font-bold text-cyan-400">{pct(c.improvement)}</td>
                          <td className="p-2.5">
                            {c.valid ? (
                              <span className="text-emerald-400 font-semibold">Yes</span>
                            ) : (
                              <span title={c.violations?.join("; ")} className="text-rose-400 font-semibold">
                                No
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <p className="text-[11px] text-slate-500">{dres.disclaimer}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
