import { useState } from "react";
import { api, ScenarioIn } from "../api/client";
import { useRunner } from "../hooks/useAsync";
import { Button, ErrorBox, ProgressBar } from "./ui";

export function ScenarioFields({
  value,
  onChange,
  dark = false,
}: {
  value: ScenarioIn;
  onChange: (s: ScenarioIn) => void;
  dark?: boolean;
}) {
  const labelCls = dark
    ? "text-xs font-semibold tracking-wider uppercase text-slate-400 flex flex-col gap-1.5"
    : "text-xs font-medium text-slate-600 flex flex-col gap-1";

  const inputCls = dark
    ? "w-full rounded-lg border border-slate-700/80 bg-slate-900/90 px-3 py-2 text-sm text-slate-100 shadow-inner outline-none transition focus:border-blue-500 focus:ring-1 focus:ring-blue-500/40"
    : "w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm outline-none transition focus:border-teal-600";

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <label className={labelCls}>
        <span>Demand Pattern</span>
        <select
          className={inputCls}
          value={value.pattern}
          onChange={(e) => onChange({ ...value, pattern: e.target.value as ScenarioIn["pattern"] })}
        >
          <option value="ew_heavy">East–West Heavy (Rush Corridor)</option>
          <option value="ns_heavy">North–South Heavy (Peak Avenues)</option>
          <option value="balanced">Balanced Grid Distribution</option>
        </select>
      </label>

      <label className={labelCls}>
        <div className="flex items-center justify-between">
          <span>Traffic Demand Scale</span>
          <span className={dark ? "font-mono text-xs font-semibold text-blue-400" : "font-mono text-xs text-slate-700"}>
            {value.demand_scale.toFixed(2)}×
          </span>
        </div>
        <div className="flex items-center gap-2 pt-1">
          <input
            className={`h-2 w-full cursor-pointer appearance-none rounded-lg ${
              dark ? "bg-slate-800 accent-blue-500" : "bg-slate-200 accent-teal-600"
            }`}
            type="range"
            min={0.6}
            max={1.6}
            step={0.05}
            value={value.demand_scale}
            onChange={(e) => onChange({ ...value, demand_scale: Number(e.target.value) })}
          />
        </div>
      </label>

      <label className={labelCls}>
        <div className="flex items-center justify-between">
          <span>Random Seed</span>
          <button
            type="button"
            onClick={() => onChange({ ...value, seed: Math.floor(Math.random() * 90000) + 10000 })}
            className={dark ? "text-[11px] text-blue-400 hover:text-blue-300" : "text-[11px] text-teal-600 hover:underline"}
          >
            Randomize
          </button>
        </div>
        <input
          className={inputCls}
          type="number"
          min={0}
          value={value.seed}
          onChange={(e) => onChange({ ...value, seed: Number(e.target.value) })}
        />
      </label>
    </div>
  );
}

/** Starts a prediction (live SUMO or clearly-labelled recorded replay) and refreshes the twin views. */
export default function PredictPanel({
  sumoAvailable,
  onDone,
  dark = true,
}: {
  sumoAvailable: boolean;
  onDone: () => void;
  dark?: boolean;
}) {
  const [sc, setSc] = useState<ScenarioIn>({ pattern: "ew_heavy", demand_scale: 1.2, seed: 50001 });
  const { run, error, busy, start } = useRunner();

  const go = async (mode: "sumo" | "dataset_replay") => {
    const r = await start(() => api.runPrediction(sc, mode));
    if (r?.status === "succeeded") onDone();
  };

  if (!dark) {
    return (
      <div className="space-y-3">
        <ScenarioFields value={sc} onChange={setSc} dark={false} />
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => go("sumo")} disabled={busy || !sumoAvailable}>
            Run live SUMO prediction
          </Button>
          <Button variant="ghost" onClick={() => go("dataset_replay")} disabled={busy}>
            Use demo replay (recorded synthetic data)
          </Button>
        </div>
        {!sumoAvailable && (
          <p className="text-xs text-amber-700">
            SUMO is not available, so only the labelled replay mode can run. See the README for setup.
          </p>
        )}
        {busy && <ProgressBar value={run?.progress ?? 0.05} label={run?.message ?? "starting…"} />}
        <ErrorBox error={error} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <ScenarioFields value={sc} onChange={setSc} dark={true} />

      <div className="flex flex-wrap items-center gap-3 pt-1">
        <button
          type="button"
          onClick={() => go("sumo")}
          disabled={busy || !sumoAvailable}
          className="group relative inline-flex items-center gap-2 overflow-hidden rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-5 py-2.5 text-sm font-medium text-white shadow-lg shadow-blue-600/30 transition-all duration-200 hover:from-blue-500 hover:to-indigo-500 hover:shadow-blue-500/40 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span className="flex h-2 w-2 rounded-full bg-cyan-300 group-hover:animate-ping" />
          <svg className="h-4 w-4 fill-current" viewBox="0 0 20 20">
            <path d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" />
          </svg>
          {busy ? "Running Prediction..." : "Run Live SUMO Prediction"}
        </button>

        <button
          type="button"
          onClick={() => go("dataset_replay")}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-700/80 bg-slate-800/80 px-4 py-2.5 text-sm font-medium text-slate-200 transition-all duration-200 hover:border-slate-600 hover:bg-slate-700/80 hover:text-white focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <svg className="h-4 w-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          Run Demo Dataset Replay
        </button>

        {!sumoAvailable && (
          <div className="flex items-center gap-1.5 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-400">
            <svg className="h-4 w-4 shrink-0 text-amber-400" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
            </svg>
            <span>SUMO engine unavailable. Use demo replay to explore features.</span>
          </div>
        )}
      </div>

      {busy && (
        <div className="rounded-xl border border-blue-500/30 bg-blue-950/40 p-3.5 shadow-inner">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="flex items-center gap-2 font-medium text-blue-300">
              <span className="h-2 w-2 animate-ping rounded-full bg-cyan-400" />
              {run?.message ?? "Executing digital twin prediction…"}
            </span>
            <span className="font-mono font-semibold text-cyan-400">
              {Math.round((run?.progress ?? 0.05) * 100)}%
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full rounded-full bg-gradient-to-r from-blue-500 via-cyan-400 to-indigo-500 transition-all duration-300 ease-out"
              style={{ width: `${Math.round((run?.progress ?? 0.05) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {error && <ErrorBox error={error} />}
    </div>
  );
}
