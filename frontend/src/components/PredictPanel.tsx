import { useState } from "react";
import { api, ScenarioIn } from "../api/client";
import { useRunner } from "../hooks/useAsync";
import { Button, ErrorBox, ProgressBar } from "./ui";

export function ScenarioFields({ value, onChange }: { value: ScenarioIn; onChange: (s: ScenarioIn) => void }) {
  const f = "mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm";
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <label className="text-xs font-medium text-slate-600">Demand pattern
        <select className={f} value={value.pattern} onChange={(e) => onChange({ ...value, pattern: e.target.value as ScenarioIn["pattern"] })}>
          <option value="ew_heavy">East–west heavy</option><option value="ns_heavy">North–south heavy</option><option value="balanced">Balanced</option>
        </select>
      </label>
      <label className="text-xs font-medium text-slate-600">Demand scale ({value.demand_scale.toFixed(2)}×)
        <input className={f} type="range" min={0.6} max={1.6} step={0.05} value={value.demand_scale}
          onChange={(e) => onChange({ ...value, demand_scale: Number(e.target.value) })} />
      </label>
      <label className="text-xs font-medium text-slate-600">Random seed
        <input className={f} type="number" min={0} value={value.seed} onChange={(e) => onChange({ ...value, seed: Number(e.target.value) })} />
      </label>
    </div>
  );
}

/** Starts a prediction (live SUMO or clearly-labelled recorded replay) and refreshes the twin views. */
export default function PredictPanel({ sumoAvailable, onDone }: { sumoAvailable: boolean; onDone: () => void }) {
  const [sc, setSc] = useState<ScenarioIn>({ pattern: "ew_heavy", demand_scale: 1.2, seed: 50001 });
  const { run, error, busy, start } = useRunner();
  const go = async (mode: "sumo" | "dataset_replay") => {
    const r = await start(() => api.runPrediction(sc, mode));
    if (r?.status === "succeeded") onDone();
  };
  return (
    <div className="space-y-3">
      <ScenarioFields value={sc} onChange={setSc} />
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => go("sumo")} disabled={busy || !sumoAvailable}>Run live SUMO prediction</Button>
        <Button variant="ghost" onClick={() => go("dataset_replay")} disabled={busy}>Use demo replay (recorded synthetic data)</Button>
      </div>
      {!sumoAvailable && <p className="text-xs text-amber-700">SUMO is not available, so only the labelled replay mode can run. See the README for setup.</p>}
      {busy && <ProgressBar value={run?.progress ?? 0.05} label={run?.message ?? "starting…"} />}
      <ErrorBox error={error} />
    </div>
  );
}
