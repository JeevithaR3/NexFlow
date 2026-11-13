import { useState } from "react";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import BenchmarkPanel from "../components/BenchmarkPanel";
import { ErrorBox, num, pct } from "../components/ui";

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
    setBusy(true);
    setErr(null);
    try {
      setRes(
        await api.searchExperiences({
          source,
          experience_id: source === "experience" ? expId || rows[0]?.experience_id : undefined,
          threshold: thr,
          k: 5,
        })
      );
    } catch (e) {
      setErr(e);
      setRes(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-white md:text-3xl">
          Experience Memory Bank
        </h1>
        <p className="mt-1 text-xs font-medium text-slate-400 md:text-sm">
          Case-based traffic policy memory indexed via FAISS vector similarity and guaranteed by SUMO re-verification
        </p>
      </div>

      {/* Real-World Context Callout Banner */}
      <div
        role="note"
        className="rounded-2xl border border-blue-500/20 bg-gradient-to-r from-[#0c1427] to-[#080d1a] p-3.5 text-xs text-slate-300 shadow-md backdrop-blur-md"
      >
        <div className="flex items-center gap-2">
          <span className="flex h-2 w-2 rounded-full bg-cyan-400" />
          <span className="font-semibold text-white">Digital Twin Synthetic Provenance:</span>
        </div>
        <p className="mt-1 text-slate-400 leading-relaxed">
          This memory contains SUMO-tested experiences for the synthetic network. Shared Bengaluru live readings provide city context, but are not used to retrieve or verify these signal timing policies.
        </p>
      </div>

      {/* 5 KPI Stat Cards */}
      {st && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-b from-[#0e1628] to-[#0a1120] p-4 shadow-xl">
            <div className="text-[11px] font-semibold tracking-wider uppercase text-slate-400">Stored Plans</div>
            <div className="mt-2 font-mono text-2xl font-extrabold text-white">{st.experiences}</div>
            <div className="mt-1 text-[11px] text-slate-500">Indexed policy cases</div>
          </div>

          <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-b from-[#0e1628] to-[#0a1120] p-4 shadow-xl">
            <div className="text-[11px] font-semibold tracking-wider uppercase text-slate-400">Improving Plans</div>
            <div className="mt-2 font-mono text-2xl font-extrabold text-emerald-400">{st.improved}</div>
            <div className="mt-1 text-[11px] text-slate-500">Measurable benefit</div>
          </div>

          <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-b from-[#0e1628] to-[#0a1120] p-4 shadow-xl">
            <div className="text-[11px] font-semibold tracking-wider uppercase text-slate-400">FAISS Index</div>
            <div className="mt-2 font-mono text-2xl font-extrabold text-cyan-400">{st.indexed_vectors}</div>
            <div className="mt-1 text-[11px] text-slate-500">
              {st.index_in_sync ? "Vectors synchronized" : "Sync required"}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-b from-[#0e1628] to-[#0a1120] p-4 shadow-xl">
            <div className="text-[11px] font-semibold tracking-wider uppercase text-slate-400">Verified Reuses</div>
            <div className="mt-2 font-mono text-2xl font-extrabold text-white">{st.verified_reuses}</div>
            <div className="mt-1 text-[11px] text-slate-500">Successful SUMO re-checks</div>
          </div>

          <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-b from-[#0e1628] to-[#0a1120] p-4 shadow-xl">
            <div className="text-[11px] font-semibold tracking-wider uppercase text-slate-400">Rejected Checks</div>
            <div className="mt-2 font-mono text-2xl font-extrabold text-rose-400">{st.failed_verifications}</div>
            <div className="mt-1 text-[11px] text-slate-500">Guardrail dropouts</div>
          </div>
        </div>
      )}

      {/* Vector Retrieval Console */}
      <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl">
        <div className="mb-4 flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-600/20 text-cyan-400">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          <h2 className="text-sm font-bold text-white tracking-wide">
            Vector Similarity Query &amp; Re-Verification
          </h2>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className="text-xs font-semibold text-slate-400">Query Source</label>
            <select
              className="mt-1 w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-xs text-white outline-none focus:border-cyan-500"
              value={source}
              onChange={(e) => setSource(e.target.value as any)}
            >
              <option value="current">Current Digital Twin State</option>
              <option value="experience">Historical Experience Case</option>
            </select>
          </div>

          {source === "experience" && (
            <div>
              <label className="text-xs font-semibold text-slate-400">Target Experience Case</label>
              <select
                className="mt-1 w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-xs text-white outline-none focus:border-cyan-500 font-mono"
                value={expId}
                onChange={(e) => setExpId(e.target.value)}
              >
                {rows.map((r: any) => (
                  <option key={r.experience_id} value={r.experience_id}>
                    {r.experience_id} &bull; {r.scenario_id}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="text-xs font-semibold text-slate-400">
              Cosine Similarity Threshold ({thr.toFixed(2)})
            </label>
            <input
              type="range"
              min={0.5}
              max={1.0}
              step={0.01}
              className="mt-2 w-full accent-cyan-400"
              value={thr}
              onChange={(e) => setThr(Number(e.target.value))}
            />
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between border-t border-slate-800 pt-4">
          <p className="text-[11px] text-slate-400">
            Threshold: <b className="text-slate-300 font-mono">{num(exp.data?.config?.similarity_threshold, 2)}</b> &bull; Demand tolerance:{" "}
            <b className="text-slate-300 font-mono">{pct(exp.data?.config?.demand_tolerance, 0)}</b>
          </p>
          <button
            type="button"
            onClick={search}
            disabled={busy || (rows.length === 0 && source === "experience")}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 px-4 py-2 text-xs font-bold text-white shadow-lg shadow-blue-500/25 transition hover:brightness-110 disabled:opacity-50"
          >
            {busy ? "Querying Vector Space..." : "Retrieve Matching Policies"}
          </button>
        </div>

        <ErrorBox error={err} />

        {/* Results Drawer */}
        {res && (
          <div className="mt-4 space-y-3 rounded-xl border border-slate-800 bg-slate-900/80 p-4">
            <div className="flex items-center justify-between text-xs">
              <span className="font-bold text-white">Retrieved Candidates ({res.matches?.length ?? 0})</span>
              <span className="text-[11px] font-mono text-cyan-300">
                Target Junction: {res.query?.junction_id}
              </span>
            </div>
            {res.matches?.length === 0 ? (
              <p className="text-xs text-slate-400">No stored policies matched within the similarity threshold.</p>
            ) : (
              res.matches?.map((m: any) => (
                <div key={m.experience_id} className="rounded-xl border border-slate-800 bg-[#0c1322] p-3 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-cyan-400">{m.experience_id}</span>
                    <span className="font-mono text-slate-400">Similarity: {num(m.similarity, 3)}</span>
                  </div>
                  <div className="mt-1 text-slate-300 font-medium">Policy: {m.intervention?.label}</div>
                  <div className="mt-2 flex items-center gap-3 text-[11px]">
                    <span className={m.accepted ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
                      {m.accepted ? "Passed Similarity & Guardrails" : "Rejected by Compatibility Checks"}
                    </span>
                    <span className="text-slate-500">Stored Improvement: {pct(m.stored_improvement)}</span>
                  </div>
                </div>
              ))
            )}
            <p className="text-[11px] text-slate-500">{res.note}</p>
          </div>
        )}
      </div>

      {/* Stored Experiences Catalog Table */}
      <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <svg className="h-4 w-4 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
            </svg>
            <h2 className="text-sm font-bold text-white tracking-wide">Historical Case Catalog</h2>
          </div>
          <span className="font-mono text-xs text-slate-400">{rows.length} cases</span>
        </div>

        {rows.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-400">
            No experiences recorded yet. Run &ldquo;Find best intervention&rdquo; on the Scenario Studio to populate memory.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-[11px] text-slate-400">
                  <th className="p-2.5">ID</th>
                  <th className="p-2.5">Scenario</th>
                  <th className="p-2.5">Junction</th>
                  <th className="p-2.5">Policy Plan</th>
                  <th className="p-2.5">Improvement</th>
                  <th className="p-2.5">Runs</th>
                  <th className="p-2.5">Reuse Ok/Fail</th>
                  <th className="p-2.5">Provenance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {rows.map((r: any) => (
                  <tr key={r.experience_id} className="hover:bg-slate-800/30">
                    <td className="p-2.5 font-bold text-white">{r.experience_id}</td>
                    <td className="p-2.5 text-slate-400">{r.scenario_id}</td>
                    <td className="p-2.5 text-cyan-400">{r.junction_id}</td>
                    <td className="p-2.5 font-sans font-medium text-slate-300">{r.intervention?.label}</td>
                    <td className="p-2.5">
                      <span className="font-bold text-emerald-400">{pct(r.improvement)}</span>{" "}
                      {r.improved ? (
                        <span className="text-[10px] text-emerald-400/80">&bull; improved</span>
                      ) : (
                        <span className="text-[10px] text-slate-500">&bull; neutral</span>
                      )}
                    </td>
                    <td className="p-2.5 text-slate-400">{r.runs_used}</td>
                    <td className="p-2.5 text-slate-300">
                      {r.verified_count} / {r.failed_verification_count}
                    </td>
                    <td className="p-2.5 text-slate-500 text-[10px]">{r.provenance}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Benchmark Panel Integration */}
      <BenchmarkPanel />
    </div>
  );
}
