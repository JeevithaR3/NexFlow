import { useEffect, useState } from "react";
import { api, ScenarioIn } from "../api/client";
import { useAsync, useRunner } from "../hooks/useAsync";
import { ScenarioFields } from "../components/PredictPanel";
import { Badge, Button, Card, Empty, ErrorBox, Loading, ProgressBar, SourceBadge, num, pct } from "../components/ui";

const ROWS: [string, string, number][] = [
  ["avg_wait_s", "Mean waiting time (s)", 1], ["avg_travel_time_s", "Mean travel time (s)", 1],
  ["queue_proxy_veh", "Queue proxy: halted vehicles (avg)", 1], ["throughput_veh", "Throughput (vehicles arrived)", 0],
  ["vehicles_in_network_end", "Vehicles still in network", 0],
];

function MetricsTable({ base, iv }: { base: any; iv?: any }) {
  return (
    <table className="w-full text-sm">
      <thead><tr className="text-left text-xs text-slate-500"><th className="py-1">Metric (evaluation window)</th><th>Baseline</th>{iv && <th>Intervention</th>}</tr></thead>
      <tbody>
        {ROWS.map(([k, label, d]) => (
          <tr key={k} className="border-t border-slate-100"><td className="py-1">{label}</td><td>{num(base.metrics[k], d)}</td>{iv && <td>{num(iv.metrics[k], d)}</td>}</tr>
        ))}
        <tr className="border-t border-slate-100"><td className="py-1">Simulation runtime (s)</td><td>{num(base.runtime_s, 1)}</td>{iv && <td>{num(iv.runtime_s, 1)}</td>}</tr>
      </tbody>
    </table>
  );
}

function NeighborTable({ eff }: { eff: Record<string, any> }) {
  return (
    <table className="mt-2 w-full text-xs">
      <thead><tr className="text-left text-slate-500"><th>Neighbouring junction</th><th>Queue before</th><th>after</th><th>Δ</th></tr></thead>
      <tbody>{Object.entries(eff).map(([j, v]) => (
        <tr key={j} className="border-t border-slate-100"><td className="py-0.5 font-mono">{j}</td><td>{v.baseline_queue}</td><td>{v.candidate_queue}</td>
          <td className={v.delta > 1.5 ? "text-red-700" : v.delta < -1.5 ? "text-green-700" : ""}>{v.delta > 0 ? "+" : ""}{v.delta}</td></tr>))}</tbody>
    </table>
  );
}

function Evaluation({ ev }: { ev: any }) {
  return (
    <div className="space-y-1 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={ev.valid ? "green" : "red"}>{ev.valid ? "valid" : "rejected by guard-rails"}</Badge>
        <span>Objective improvement: <b>{pct(ev.improvement)}</b></span>
      </div>
      {ev.violations.map((v: string) => <div key={v} className="text-xs text-red-700">• {v}</div>)}
      <NeighborTable eff={ev.neighbor_effects} />
    </div>
  );
}

export default function Scenario() {
  const net = useAsync(() => api.network());
  const tls = net.data?.junctions.filter((j) => j.has_tls).map((j) => j.id) ?? [];
  const [sc, setSc] = useState<ScenarioIn>({ pattern: "ew_heavy", demand_scale: 1.3, seed: 50001 });
  const [junction, setJunction] = useState("B1");
  const cand = useAsync(() => (tls.includes(junction) ? api.candidates(junction) : Promise.resolve(null)), [junction, tls.length]);
  const [greens, setGreens] = useState<Record<string, number>>({});
  const sim = useRunner();
  const dec = useRunner();
  const [useMem, setUseMem] = useState(true);
  const lim = net.data?.signal_limits;

  useEffect(() => {
    if (cand.data) setGreens(Object.fromEntries(cand.data.green_phases.map((g: any) => [String(g.index), g.duration])));
  }, [cand.data]);

  const runSim = () => sim.start(() => api.runSimulation(sc, { type: "signal_timing", junction_id: junction, green_s: greens }));
  const runDecision = () => dec.start(() => api.evaluate({ scenario: sc, junction_id: null, use_memory: useMem, include_rerouting: false, store_experience: true }));
  const sres = sim.run?.status === "succeeded" ? sim.run.result : null;
  const dres = dec.run?.status === "succeeded" ? dec.run.result : null;

  return (
    <>
      <header>
        <h1 className="text-2xl font-semibold">Scenario simulation</h1>
        <p className="text-sm text-slate-600">Every run below is a real SUMO simulation of the same demand, with and without the change. Nothing is applied to real signals.</p>
      </header>
      <Card title="Scenario"><ScenarioFields value={sc} onChange={setSc} /></Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="1. Test a signal-timing change">
          {net.loading ? <Loading /> : (
            <div className="space-y-3">
              <label className="block text-xs font-medium text-slate-600">Junction
                <select className="mt-1 w-full rounded-md border border-slate-300 p-1.5 text-sm" value={junction} onChange={(e) => setJunction(e.target.value)}>
                  {tls.map((j) => <option key={j}>{j}</option>)}</select></label>
              {cand.data?.green_phases.map((g: any) => (
                <label key={g.index} className="block text-xs font-medium text-slate-600">
                  Phase {g.index} green · serves {g.axis} approaches: <b>{greens[String(g.index)] ?? g.duration}s</b> (default {g.duration}s)
                  <input type="range" className="w-full" min={lim?.min_green_s ?? 10} max={lim?.max_green_s ?? 60} step={1}
                    value={greens[String(g.index)] ?? g.duration} onChange={(e) => setGreens({ ...greens, [String(g.index)]: Number(e.target.value) })} />
                </label>
              ))}
              <p className="text-xs text-slate-500">Permitted range {lim?.min_green_s}–{lim?.max_green_s}s per green; cycle ≤ {lim?.max_cycle_s}s. Yellow time is fixed.</p>
              <Button onClick={runSim} disabled={sim.busy || !cand.data}>Run baseline vs intervention</Button>
              {sim.busy && <ProgressBar value={sim.run?.progress ?? 0.05} label={sim.run?.message ?? "starting SUMO…"} />}
              <ErrorBox error={sim.error} />
            </div>
          )}
        </Card>
        <Card title="Result" right={sres && <SourceBadge source="simulated" />}>
          {!sres ? <Empty title="No simulation yet">Choose a junction and green times, then run.</Empty> : (
            <div className="space-y-3">
              <MetricsTable base={sres.baseline} iv={sres.intervention} />
              {sres.evaluation && <Evaluation ev={sres.evaluation} />}
              <p className="text-xs text-slate-500">{sres.disclaimer}</p>
            </div>
          )}
        </Card>
      </div>
      <Card title="2. Let the system find the best plan (forecast → memory → SUMO)">
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={useMem} onChange={(e) => setUseMem(e.target.checked)} /> Search Experience Memory first (verified in SUMO before use)</label>
          <Button onClick={runDecision} disabled={dec.busy}>Find best intervention</Button>
          {dec.busy && <ProgressBar value={dec.run?.progress ?? 0.03} label={dec.run?.message ?? "starting…"} />}
          <ErrorBox error={dec.error} />
          {dres && (
            <div className="space-y-3 border-t border-slate-200 pt-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <SourceBadge source={dres.source} />
                <span>Target junction <b>{dres.target_junction}</b> <span className="text-xs text-slate-500">({dres.target_rule})</span></span>
              </div>
              <div>{dres.selected
                ? <>Recommendation: <b>{dres.selected.intervention.label}</b>, improvement <b>{pct(dres.selected.improvement)}</b></>
                : "No candidate beat the current plan under the guard-rails: keep the current plan."}</div>
              <div className="text-xs text-slate-600">Memory: <b>{dres.memory.outcome}</b> · SUMO runs {dres.cost.sumo_runs} · decision {dres.cost.decision_seconds}s · lookup {dres.cost.lookup_seconds}s</div>
              {dres.memory.matches?.length > 0 && <ul className="text-xs text-slate-600">{dres.memory.matches.map((m: any) => <li key={m.experience_id}>{m.experience_id} · similarity {m.similarity} · {m.accepted ? "accepted" : `rejected: ${m.reasons.join("; ")}`}</li>)}</ul>}
              <table className="w-full text-xs">
                <thead><tr className="text-left text-slate-500"><th>Candidate</th><th>Origin</th><th>Improvement</th><th>Valid</th></tr></thead>
                <tbody>{dres.candidates.map((c: any, i: number) => (
                  <tr key={i} className="border-t border-slate-100"><td className="py-0.5">{c.intervention.label}</td><td>{c.origin}</td><td>{pct(c.improvement)}</td>
                    <td>{c.valid ? "yes" : <span title={c.violations.join("; ")} className="text-red-700">no</span>}</td></tr>))}</tbody>
              </table>
              <p className="text-xs text-slate-500">{dres.disclaimer}</p>
            </div>
          )}
        </div>
      </Card>
    </>
  );
}
