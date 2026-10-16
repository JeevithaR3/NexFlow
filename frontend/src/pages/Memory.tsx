import { useState } from "react";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import BenchmarkPanel from "../components/BenchmarkPanel";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Stat, num, pct } from "../components/ui";

export default function Memory() {
  const exp = useAsync(() => api.experiences());
  const [source, setSource] = useState<"current" | "experience">("current");
  const [expId, setExpId] = useState("");
  const [thr, setThr] = useState(0.9);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const rows = exp.data?.experiences ?? [];
  const st = exp.data?.stats;

  const search = async () => {
    setBusy(true); setErr(null);
    try { setRes(await api.searchExperiences({ source, experience_id: source === "experience" ? expId || rows[0]?.experience_id : undefined, threshold: thr, k: 5 })); }
    catch (e) { setErr(e); setRes(null); } finally { setBusy(false); }
  };

  return (
    <>
      <header>
        <h1 className="text-2xl font-semibold">Experience memory</h1>
        <p className="text-sm text-slate-600">Past decisions are retrieved by FAISS similarity, filtered by compatibility checks, and always re-verified in SUMO before use. Similarity alone never proves that a plan will work.</p>
      </header>
      {st && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Stat label="Stored" value={st.experiences} /><Stat label="Improving" value={st.improved} />
          <Stat label="Indexed vectors" value={st.indexed_vectors} hint={st.index_in_sync ? "index in sync" : "OUT OF SYNC"} />
          <Stat label="Verified reuses" value={st.verified_reuses} /><Stat label="Failed verifications" value={st.failed_verifications} />
        </div>
      )}
      <Card title="Search similar experiences">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-slate-600">Query state
            <select className="mt-1 block rounded border border-slate-300 p-1.5 text-sm" value={source} onChange={(e) => setSource(e.target.value as any)}>
              <option value="current">Current digital-twin state</option><option value="experience">A stored experience</option></select></label>
          {source === "experience" && (
            <label className="text-xs text-slate-600">Experience
              <select className="mt-1 block rounded border border-slate-300 p-1.5 text-sm" value={expId} onChange={(e) => setExpId(e.target.value)}>
                {rows.map((r: any) => <option key={r.experience_id} value={r.experience_id}>{r.experience_id} · {r.scenario_id}</option>)}</select></label>)}
          <label className="text-xs text-slate-600">Similarity threshold ({thr.toFixed(2)})
            <input type="range" className="mt-2 block" min={0.5} max={1} step={0.01} value={thr} onChange={(e) => setThr(Number(e.target.value))} /></label>
          <Button onClick={search} disabled={busy || rows.length === 0 && source === "experience"}>Search</Button>
        </div>
        <div className="mt-3"><ErrorBox error={err} /></div>
        {res && (
          <div className="mt-3 space-y-2">
            <div className="text-xs text-slate-500">Target junction {res.query.junction_id} · threshold {res.query.threshold}</div>
            {res.matches.length === 0 ? <Empty title="No similar experiences found">The memory is empty or nothing is close enough.</Empty> : res.matches.map((m: any) => (
              <div key={m.experience_id} className="rounded-lg border border-slate-200 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs">{m.experience_id}</span>
                  <Badge tone={m.accepted ? "green" : "red"}>{m.accepted ? "accepted" : "rejected"}</Badge>
                  <span>similarity <b>{m.similarity}</b></span><span className="text-xs text-slate-500">{m.scenario_id}</span>
                </div>
                <div className="mt-1 text-xs text-slate-700">Plan: {m.intervention.label} (stored improvement {pct(m.stored_improvement)})</div>
                {m.reasons.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs text-red-700">{m.reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>}
                {m.accepted && <div className="mt-1 text-xs text-teal-800">Passed similarity and all compatibility checks → would be verified in SUMO before being recommended.</div>}
              </div>))}
            <p className="text-xs text-slate-500">{res.note}</p>
          </div>)}
      </Card>
      <Card title="Stored experiences">
        {exp.loading && !exp.data ? <Loading /> : <ErrorBox error={exp.error} />}
        {exp.data && rows.length === 0 ? <Empty title="The memory is empty">Run “Find best intervention” on the Scenario page, or run the benchmark script, to create experiences.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-left text-slate-500"><th>ID</th><th>Scenario</th><th>Junction</th><th>Plan</th><th>Improvement</th><th>Runs</th><th>Reuse ok/fail</th><th>Provenance</th></tr></thead>
              <tbody>{rows.map((r: any) => (
                <tr key={r.experience_id} className="border-t border-slate-100">
                  <td className="py-1 font-mono">{r.experience_id}</td><td>{r.scenario_id}</td><td>{r.junction_id}</td><td>{r.intervention.label}</td>
                  <td>{pct(r.improvement)} {r.improved ? <Badge tone="green">improved</Badge> : <Badge>no gain</Badge>}</td><td>{r.runs_used}</td>
                  <td>{r.verified_count}/{r.failed_verification_count}</td><td>{r.provenance}</td></tr>))}</tbody>
            </table>
          </div>)}
        <p className="mt-2 text-xs text-slate-500">Threshold {num(exp.data?.config.similarity_threshold, 2)} · demand tolerance {pct(exp.data?.config.demand_tolerance, 0)} · feature schema {exp.data?.config.feature_schema}</p>
      </Card>
      <BenchmarkPanel />
    </>
  );
}
