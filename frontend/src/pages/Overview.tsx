import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Level } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import PredictPanel from "../components/PredictPanel";
import { Badge, Card, Empty, ErrorBox, LEVEL_COLOR, Loading, SourceBadge, Stat, num } from "../components/ui";

export default function Overview() {
  const health = useAsync(() => api.health());
  const cur = useAsync(() => api.trafficCurrent());
  const evalm = useAsync(() => api.modelEvaluation());
  const reloadAll = () => { health.reload(); cur.reload(); };
  const h = health.data;
  const t = cur.data;
  const dist = (["low", "moderate", "high", "unknown"] as Level[]).map((l) => ({
    level: l, current: t?.distribution?.current?.[l] ?? 0, predicted: t?.distribution?.predicted?.[l] ?? 0,
  }));
  const pred = t?.prediction;
  return (
    <>
      <header>
        <h1 className="text-2xl font-semibold">Overview</h1>
        <p className="text-sm text-slate-600">Current and forecast congestion on the synthetic SUMO network.</p>
      </header>
      <ErrorBox error={health.error} />
      {health.loading && !h ? <Loading /> : h && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Road segments" value={h.network.edges} hint="monitored (GNN nodes)" />
          <Stat label="Signalised junctions" value={h.network.signalised_junctions} />
          <Stat label="Simulation" value={<Badge tone={h.sumo.available ? "green" : "red"}>{h.sumo.available ? `SUMO ${h.sumo.version}` : "SUMO missing"}</Badge>}
            hint={h.sumo.available ? "TraCI connected on demand" : h.sumo.problems?.[0]} />
          <Stat label="Forecast model" value={<Badge tone={h.model.loaded ? "green" : "amber"}>{h.model.loaded ? "loaded" : "not trained"}</Badge>} hint={h.model.version ?? h.model.hint} />
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Congestion distribution (road segments)" className="lg:col-span-2">
          {cur.loading && !t ? <Loading /> : !t?.available ? (
            <Empty title="No traffic state yet">Run a prediction below. Nothing is shown until real simulation output exists.</Empty>
          ) : (
            <>
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                <SourceBadge source={t.source} /> <span>sim time {t.sim_time_s}s</span>
                {pred && <span>· forecast {pred.horizon_s}s ahead · made {new Date(pred.created_at).toLocaleString()}</span>}
              </div>
              <div style={{ height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={dist}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="level" /><YAxis allowDecimals={false} /><Tooltip />
                    <Bar dataKey="current" name="Current">{dist.map((d) => <Cell key={d.level} fill={LEVEL_COLOR[d.level]} />)}</Bar>
                    <Bar dataKey="predicted" name="Predicted" fillOpacity={0.45}>{dist.map((d) => <Cell key={d.level} fill={LEVEL_COLOR[d.level]} />)}</Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="text-xs text-slate-500">Solid bars: current. Faded bars: predicted {pred?.horizon_s ?? ""}s ahead.{!pred && " No forecast yet for this state."}</p>
            </>
          )}
        </Card>
        <div className="space-y-4">
          <Card title="Experience memory">
            {h?.memory ? (
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <dt className="text-slate-500">Stored</dt><dd>{h.memory.experiences}</dd>
                <dt className="text-slate-500">Improving</dt><dd>{h.memory.improved}</dd>
                <dt className="text-slate-500">Reuse attempts</dt><dd>{h.memory.reuse_attempts}</dd>
                <dt className="text-slate-500">Verified reuses</dt><dd>{h.memory.verified_reuses}</dd>
                <dt className="text-slate-500">Failed checks</dt><dd>{h.memory.failed_verifications}</dd>
              </dl>
            ) : <Loading />}
          </Card>
          <Card title="Forecast quality (test split)">
            {evalm.data?.available ? (
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <dt className="text-slate-500">GNN MAE</dt><dd>{num(evalm.data.test.gnn.mae, 3)}</dd>
                <dt className="text-slate-500">Persistence MAE</dt><dd>{num(evalm.data.test.persistence.mae, 3)}</dd>
                <dt className="text-slate-500">GNN RMSE</dt><dd>{num(evalm.data.test.gnn.rmse, 3)}</dd>
                <dt className="text-slate-500">Horizon</dt><dd>{evalm.data.horizon_s}s</dd>
              </dl>
            ) : <p className="text-sm text-slate-500">{evalm.data?.reason ?? "Loading…"}</p>}
          </Card>
        </div>
      </div>
      <Card title="Run a prediction">
        <PredictPanel sumoAvailable={!!h?.sumo.available && !!h?.model.loaded} onDone={reloadAll} />
      </Card>
    </>
  );
}
