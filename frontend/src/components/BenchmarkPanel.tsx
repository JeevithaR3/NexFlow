import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { useAsync, useRunner } from "../hooks/useAsync";
import { Badge, Button, Card, Empty, ErrorBox, Loading, ProgressBar, Stat, num, pct } from "./ui";

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
  const bars = s ? [
    { metric: "SUMO runs", "A: simulate all": s.A.sumo_runs, "B: memory first": s.B.sumo_runs },
    { metric: "Decision time (s)", "A: simulate all": s.A.decision_seconds, "B: memory first": s.B.decision_seconds },
  ] : [];
  return (
    <Card title="Benchmark: simulate everything (A) vs memory first (B)"
      right={latest && <span className="text-xs text-slate-500">{new Date(latest.created_at).toLocaleString()} · {latest.config.n_eval} scenarios · {latest.config.n_warmup} warm-up</span>}>
      {list.loading && !list.data ? <Loading /> : !s ? (
        <Empty title="No benchmark has been run yet">Run one below, or use <code>python scripts/run_benchmark.py</code>. No efficiency claim is made until one exists.</Empty>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="SUMO runs saved" value={`${s.runs_saved} (${s.runs_saved_pct}%)`} hint={`A ${s.A.sumo_runs} → B ${s.B.sumo_runs}`} />
            <Stat label="Time saved" value={`${s.time_saved_pct}%`} hint={`${s.A.decision_seconds}s → ${s.B.decision_seconds}s`} />
            <Stat label="Memory reuse rate" value={pct(s.reuse_rate, 0)} hint={`lookups ${num(s.B.lookup_seconds, 3)}s total`} />
            <Stat label="Failed verifications" value={s.verification_failures} />
          </div>
          <div style={{ height: 220 }}>
            <ResponsiveContainer>
              <BarChart data={bars}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="metric" /><YAxis /><Tooltip /><Legend />
                <Bar dataKey="A: simulate all" fill="#64748b" /><Bar dataKey="B: memory first" fill="#0f766e" /></BarChart>
            </ResponsiveContainer>
          </div>
          <div className="text-sm">Mean objective improvement: A {pct(s.A.mean_improvement)} · B {pct(s.B.mean_improvement)}</div>
          <div className="flex flex-wrap gap-1 text-xs">
            {Object.entries(s.memory_outcomes).map(([k, v]) => <Badge key={k} tone={k === "reused" ? "teal" : k === "failed_verification" ? "red" : "slate"}>{k}: {String(v)}</Badge>)}
          </div>
          {s.cases_B_less_effective.length > 0 && <p className="text-xs text-amber-800">Memory-first was less effective in: {s.cases_B_less_effective.join(", ")}</p>}
          {s.cases_B_slower.length > 0 && <p className="text-xs text-amber-800">Memory-first was slower in {s.cases_B_slower.length} scenario(s).</p>}
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">{s.notes.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-slate-200 pt-3">
        <label className="text-xs text-slate-600">Warm-up scenarios
          <input type="number" min={0} max={30} className="ml-2 w-16 rounded border border-slate-300 p-1" value={size.n_warmup} onChange={(e) => setSize({ ...size, n_warmup: Number(e.target.value) })} /></label>
        <label className="text-xs text-slate-600">Evaluation scenarios
          <input type="number" min={1} max={30} className="ml-2 w-16 rounded border border-slate-300 p-1" value={size.n_eval} onChange={(e) => setSize({ ...size, n_eval: Number(e.target.value) })} /></label>
        <Button onClick={go} disabled={busy}>Run benchmark (needs SUMO)</Button>
        <span className="text-xs text-slate-500">≈ {Math.round((size.n_warmup + 2 * size.n_eval) * 0.5)} min</span>
      </div>
      {busy && <div className="mt-2"><ProgressBar value={run?.progress ?? 0.02} label={run?.message} /></div>}
      <div className="mt-2"><ErrorBox error={error} /></div>
    </Card>
  );
}
