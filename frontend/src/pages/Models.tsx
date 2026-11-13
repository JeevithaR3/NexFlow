import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { ErrorBox, num, pct } from "../components/ui";

const MODELS: [string, string][] = [
  ["gnn", "ST-GCN (Spatiotemporal Graph)"],
  ["persistence", "Persistence (Lagged Constant)"],
  ["historical_mean", "Historical Mean Baseline"],
];

export default function Models() {
  const m = useAsync(() => api.modelEvaluation());
  const d = m.data;

  const rows = d?.available
    ? MODELS.filter(([k]) => d.test[k]).map(([k, label]) => ({ key: k, label, ...d.test[k] }))
    : [];

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-white md:text-3xl">
          Model Evaluation &amp; Benchmarks
        </h1>
        <p className="mt-1 text-xs font-medium text-slate-400 md:text-sm">
          Comparative empirical validation of Spatio-Temporal Graph Neural Networks against baseline models
        </p>
      </div>

      {/* Dataset Context Callout Banner */}
      <div
        role="note"
        className="rounded-2xl border border-blue-500/20 bg-gradient-to-r from-[#0c1427] to-[#080d1a] p-3.5 text-xs text-slate-300 shadow-md backdrop-blur-md"
      >
        <div className="flex items-center gap-2">
          <span className="flex h-2 w-2 rounded-full bg-cyan-400" />
          <span className="font-semibold text-white">Evaluation Dataset Boundary:</span>
        </div>
        <p className="mt-1 text-slate-400 leading-relaxed">
          Trained and evaluated strictly on synthetic SUMO data. TomTom observations are shared elsewhere in the dashboard for real-world context; they are not part of this model’s training or evaluation dataset.
        </p>
      </div>

      <ErrorBox error={m.error} />

      {!d?.available ? (
        <div className="rounded-2xl border border-dashed border-slate-800 bg-slate-900/40 p-8 text-center text-xs text-slate-400">
          {d?.reason ?? (m.loading ? "Loading model telemetry..." : "No evaluation dataset currently loaded.")}
        </div>
      ) : (
        <>
          {/* Architecture & Dataset Telemetry */}
          <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl">
            <div className="mb-4 flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-600/20 text-cyan-400">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
                </svg>
              </div>
              <h2 className="text-sm font-bold text-white tracking-wide">
                Hyperparameters &amp; Training Specifications
              </h2>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6 text-xs">
              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-slate-400">Target Feature</div>
                <div className="mt-1 font-mono font-bold text-white truncate">{d.target}</div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-slate-400">Horizon</div>
                <div className="mt-1 font-mono font-bold text-cyan-400">
                  {d.horizon_s}s ({d.horizon_intervals}&times;{d.interval_s}s)
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-slate-400">Input Window</div>
                <div className="mt-1 font-mono font-bold text-white">{d.window_intervals} steps</div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-slate-400">Test Samples</div>
                <div className="mt-1 font-mono font-bold text-emerald-400">{d.test.n_samples}</div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-slate-400">Split Structure</div>
                <div className="mt-1 font-mono font-bold text-white">
                  {d.split.train_runs}/{d.split.val_runs}/{d.split.test_runs}
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-slate-400">Checkpoint</div>
                <div className="mt-1 font-mono font-bold text-cyan-400 truncate">{d.model_version}</div>
              </div>
            </div>
          </div>

          {/* Comparative Metrics & History Charts */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Card 1: Benchmark Error Comparison */}
            <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl flex flex-col justify-between">
              <div>
                <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
                  <svg className="h-4 w-4 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                  </svg>
                  <h3 className="text-sm font-bold text-white tracking-wide">
                    Test Set Error (Lower MAE / RMSE is Better)
                  </h3>
                </div>

                {/* Table */}
                <div className="mt-4 overflow-x-auto rounded-xl border border-slate-800">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-[11px] text-slate-400">
                        <th className="p-2.5">Model Architecture</th>
                        <th className="p-2.5">MAE</th>
                        <th className="p-2.5">RMSE</th>
                        <th className="p-2.5">Level Accuracy</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono">
                      {rows.map((r: any) => (
                        <tr
                          key={r.key}
                          className={`hover:bg-slate-800/30 ${r.key === "gnn" ? "bg-cyan-500/10 font-bold" : ""}`}
                        >
                          <td className="p-2.5 font-sans font-medium text-white">{r.label}</td>
                          <td className="p-2.5 text-cyan-400">{num(r.mae, 4)}</td>
                          <td className="p-2.5 text-slate-300">{num(r.rmse, 4)}</td>
                          <td className="p-2.5 text-emerald-400">{pct(r.level_accuracy)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Bar chart */}
                <div className="h-52 w-full mt-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={rows} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#1e293b" />
                      <XAxis dataKey="key" stroke="#64748b" tick={{ fill: "#94a3b8", fontSize: 10 }} tickLine={false} />
                      <YAxis stroke="#64748b" tick={{ fill: "#94a3b8", fontSize: 10 }} tickLine={false} />
                      <Tooltip
                        content={({ active, payload }) => {
                          if (!active || !payload?.length) return null;
                          return (
                            <div className="rounded-xl border border-slate-700 bg-slate-900/95 p-2.5 shadow-xl text-xs">
                              <div className="font-semibold text-white">{payload[0].payload.label}</div>
                              {payload.map((p, i) => (
                                <div key={i} className="flex justify-between gap-4 mt-1 text-slate-300">
                                  <span style={{ color: p.color }}>{p.name}:</span>
                                  <span className="font-mono font-bold text-white">{num(p.value as number, 4)}</span>
                                </div>
                              ))}
                            </div>
                          );
                        }}
                      />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar dataKey="mae" name="MAE Error" fill="#00f0ff" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="rmse" name="RMSE Error" fill="#64748b" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <p className="mt-3 text-[11px] text-slate-500 border-t border-slate-800 pt-2">
                Comparative evaluation strictly based on synthetic test data splits.
              </p>
            </div>

            {/* Card 2: Training History Line Chart */}
            <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl flex flex-col justify-between">
              <div>
                <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
                  <svg className="h-4 w-4 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                  </svg>
                  <h3 className="text-sm font-bold text-white tracking-wide">
                    Neural Convergence History (Epochs vs. Loss)
                  </h3>
                </div>

                <div className="h-72 w-full mt-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={d.history} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#1e293b" />
                      <XAxis dataKey="epoch" stroke="#64748b" tick={{ fill: "#94a3b8", fontSize: 10 }} tickLine={false} />
                      <YAxis stroke="#64748b" tick={{ fill: "#94a3b8", fontSize: 10 }} tickLine={false} />
                      <Tooltip
                        content={({ active, payload }) => {
                          if (!active || !payload?.length) return null;
                          const pt = payload[0].payload;
                          return (
                            <div className="rounded-xl border border-slate-700 bg-slate-900/95 p-2.5 shadow-xl text-xs">
                              <div className="font-semibold text-white">Epoch {pt.epoch}</div>
                              <div className="text-slate-400 mt-1">Train Loss: <span className="font-mono text-white">{num(pt.train_loss, 4)}</span></div>
                              <div className="text-cyan-400">Val MAE: <span className="font-mono text-white">{num(pt.val_mae, 4)}</span></div>
                            </div>
                          );
                        }}
                      />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Line type="monotone" dataKey="train_loss" name="Train Loss" stroke="#64748b" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="val_mae" name="Validation MAE" stroke="#a855f7" strokeWidth={2.5} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="mt-3 flex items-center justify-between text-[11px] text-slate-400 border-t border-slate-800 pt-2 font-mono">
                <span>{d.epochs_run} Epochs (Early Stopping)</span>
                <span>Best Val MAE: <b className="text-emerald-400">{num(d.best_val_mae, 4)}</b></span>
                <span>Training Time: {d.train_seconds}s</span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
