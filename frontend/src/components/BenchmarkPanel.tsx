import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { useAsync, useRunner } from "../hooks/useAsync";
import { ErrorBox, ProgressBar, num, pct } from "./ui";

export default function BenchmarkPanel() {
  const list = useAsync(() => api.benchmarks());
  const { run, error, busy, start } = useRunner();
  const [size, setSize] = useState({ n_warmup: 4, n_eval: 4 });
  const latest = list.data?.benchmarks?.[0];
  const s = latest?.summary;

  const go = async () => {
    const r = await start(() => api.runBenchmark({ ...size, seed_base: 50000, include_rerouting: false }));
    if (r?.status === "succeeded") list.reload();
  };

  const bars = s
    ? [
        { metric: "SUMO Runs Required", "Simulate All (A)": s.A.sumo_runs, "Memory First (B)": s.B.sumo_runs },
        { metric: "Decision Latency (s)", "Simulate All (A)": s.A.decision_seconds, "Memory First (B)": s.B.decision_seconds },
      ]
    : [];

  return (
    <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-600/20 text-cyan-400">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <h2 className="text-sm font-bold text-white tracking-wide">
            Benchmark: Direct Simulation (A) vs. Memory-First (B)
          </h2>
        </div>

        {latest && (
          <span className="font-mono text-[11px] text-slate-400">
            Last Run: {new Date(latest.created_at).toLocaleTimeString()} &bull; {latest.config.n_eval} Scenarios &bull; {latest.config.n_warmup} Warmup
          </span>
        )}
      </div>

      <div className="mt-4">
        {!s ? (
          <div className="py-8 text-center text-xs text-slate-400">
            No benchmark records found. Run an evaluation below to benchmark decision efficiency.
          </div>
        ) : (
          <div className="space-y-4">
            {/* 4 Stat Cards */}
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">SUMO Runs Saved</div>
                <div className="mt-1 font-mono text-2xl font-extrabold text-emerald-400">
                  {s.runs_saved} <span className="text-xs font-normal">({s.runs_saved_pct}%)</span>
                </div>
                <div className="mt-0.5 text-[11px] text-slate-500 font-mono">
                  A: {s.A.sumo_runs} &rarr; B: {s.B.sumo_runs}
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Decision Time Saved</div>
                <div className="mt-1 font-mono text-2xl font-extrabold text-cyan-400">
                  {s.time_saved_pct}%
                </div>
                <div className="mt-0.5 text-[11px] text-slate-500 font-mono">
                  {s.A.decision_seconds}s &rarr; {s.B.decision_seconds}s
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Memory Reuse Rate</div>
                <div className="mt-1 font-mono text-2xl font-extrabold text-purple-400">
                  {pct(s.reuse_rate, 0)}
                </div>
                <div className="mt-0.5 text-[11px] text-slate-500 font-mono">
                  Lookup cost: {num(s.B.lookup_seconds, 3)}s
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Verification Rejections</div>
                <div className="mt-1 font-mono text-2xl font-extrabold text-white">
                  {s.verification_failures}
                </div>
                <div className="mt-0.5 text-[11px] text-slate-500">
                  Guardrails prevented invalid reuses
                </div>
              </div>
            </div>

            {/* Benchmark Comparative Chart */}
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <div className="h-52 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={bars} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#1e293b" />
                    <XAxis dataKey="metric" stroke="#64748b" tick={{ fill: "#94a3b8", fontSize: 11 }} tickLine={false} />
                    <YAxis stroke="#64748b" tick={{ fill: "#94a3b8", fontSize: 11 }} tickLine={false} />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        return (
                          <div className="rounded-xl border border-slate-700 bg-slate-900/95 p-2.5 shadow-xl text-xs">
                            <div className="font-semibold text-white">{payload[0].payload.metric}</div>
                            {payload.map((p, i) => (
                              <div key={i} className="flex justify-between gap-4 mt-1 text-slate-300">
                                <span style={{ color: p.color }}>{p.name}:</span>
                                <span className="font-mono font-bold text-white">{p.value}</span>
                              </div>
                            ))}
                          </div>
                        );
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="Simulate All (A)" fill="#64748b" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="Memory First (B)" fill="#00f0ff" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="text-xs text-slate-300">
              Mean Objective Improvement: <span className="font-semibold text-white">Baseline A: {pct(s.A.mean_improvement)}</span> &bull;{" "}
              <span className="font-semibold text-cyan-400">Memory-First B: {pct(s.B.mean_improvement)}</span>
            </div>
          </div>
        )}

        {/* Benchmark Runner Controls */}
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 pt-4">
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <label className="text-slate-400 font-medium">
              Warm-up Scenarios:
              <input
                type="number"
                min={0}
                max={30}
                className="ml-2 w-16 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 font-mono text-white outline-none focus:border-cyan-500"
                value={size.n_warmup}
                onChange={(e) => setSize({ ...size, n_warmup: Number(e.target.value) })}
              />
            </label>
            <label className="text-slate-400 font-medium">
              Evaluation Scenarios:
              <input
                type="number"
                min={1}
                max={30}
                className="ml-2 w-16 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 font-mono text-white outline-none focus:border-cyan-500"
                value={size.n_eval}
                onChange={(e) => setSize({ ...size, n_eval: Number(e.target.value) })}
              />
            </label>
            <span className="text-[11px] text-slate-500">
              &approx; {Math.round((size.n_warmup + 2 * size.n_eval) * 0.5)} min simulation run
            </span>
          </div>

          <button
            type="button"
            onClick={go}
            disabled={busy}
            className="rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 px-5 py-2.5 text-xs font-bold text-white shadow-md shadow-cyan-500/20 transition hover:brightness-110 disabled:opacity-50"
          >
            {busy ? "Running Benchmark..." : "Execute Benchmark Suite"}
          </button>
        </div>

        {busy && (
          <div className="mt-3">
            <ProgressBar value={run?.progress ?? 0.02} label={run?.message ?? "Running benchmark batch..."} />
          </div>
        )}
        <div className="mt-2">
          <ErrorBox error={error} />
        </div>
      </div>
    </div>
  );
}
