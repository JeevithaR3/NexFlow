import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, Level } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import TrafficMap from "../components/TrafficMap";
import { Badge, Button, Card, Empty, ErrorBox, LEVEL_LABEL, Loading, LevelLegend, SourceBadge, num } from "../components/ui";

export default function MapPage() {
  const net = useAsync(() => api.network());
  const pred = useAsync(() => api.trafficPredictions());
  const cur = useAsync(() => api.trafficCurrent());
  const [view, setView] = useState<"current" | "predicted">("current");
  const [base, setBase] = useState(true);
  const [edge, setEdge] = useState<string | null>(null);
  const [junction, setJunction] = useState<string | null>(null);
  const [route, setRoute] = useState<any>(null);
  const [routeErr, setRouteErr] = useState<any>(null);
  const [from, setFrom] = useState("left1A1");
  const [to, setTo] = useState("C1right1");

  const byId = useMemo(() => Object.fromEntries((pred.data?.available ? pred.data.edges : cur.data?.edges ?? []).map((e: any) => [e.id, e])), [pred.data, cur.data]);
  const levels = useMemo(() => {
    const out: Record<string, Level> = {};
    Object.values(byId).forEach((e: any) => { out[e.id] = view === "predicted" ? (e.pred_level ?? "unknown") : e.level; });
    return out;
  }, [byId, view]);
  const hasState = cur.data?.available;
  const iv = pred.data?.intervention;
  const recommended: Record<string, string> = iv?.intervention?.junction_id ? { [iv.intervention.junction_id]: iv.intervention.label } : {};
  const e = edge ? byId[edge] : null;
  const ed = edge && net.data ? net.data.edges.find((x) => x.id === edge) : null;
  const jn = junction && net.data ? net.data.junctions.find((x) => x.id === junction) : null;
  const boundary = net.data?.edges.filter((x) => /^(left|right|top|bottom)/.test(x.from) || /^(left|right|top|bottom)/.test(x.to)) ?? [];

  const findRoute = async () => {
    setRouteErr(null);
    try { setRoute(await api.altRoute(from, to)); } catch (err) { setRouteErr(err); setRoute(null); }
  };
  const routes = route ? [
    { id: "default", shape: route.default_shape, color: "#1e293b", dash: "2 8" },
    ...(route.differs ? [{ id: "alt", shape: route.alternative_shape, color: "#2563eb", dash: "10 6" }] : []),
  ] : [];

  return (
    <>
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Traffic map</h1>
          <p className="text-sm text-slate-600">Click a road or junction for details.</p>
        </div>
        <div className="flex items-center gap-2">
          <div role="group" aria-label="Traffic view" className="inline-flex overflow-hidden rounded-lg border border-slate-300">
            {(["current", "predicted"] as const).map((v) => (
              <button key={v} onClick={() => setView(v)} aria-pressed={view === v} disabled={v === "predicted" && !pred.data?.available}
                className={`px-3 py-1.5 text-sm ${view === v ? "bg-teal-700 text-white" : "bg-white text-slate-700"} disabled:opacity-40`}>
                {v === "current" ? "Current / simulated" : "Predicted"}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1 text-xs text-slate-600"><input type="checkbox" checked={base} onChange={(e) => setBase(e.target.checked)} /> OSM basemap</label>
        </div>
      </header>
      <div role="note" className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
        {net.data?.notice ?? "Synthetic simulation network."} Colours show simulated values, not real-world traffic.
      </div>
      <ErrorBox error={net.error} />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-2 lg:col-span-2">
          {net.loading || !net.data ? <Loading label="Loading network…" /> : (
            <TrafficMap network={net.data} levels={hasState ? levels : {}} selectedEdge={edge} selectedJunction={junction}
              recommended={recommended} routes={routes} showBasemap={base}
              onEdge={(id) => { setEdge(id); setJunction(null); }} onJunction={(id) => { setJunction(id); setEdge(null); }} />
          )}
          <LevelLegend />
          {!hasState && !cur.loading && <Empty title="Roads are gray: no traffic data yet">Run a prediction on the Overview page.</Empty>}
        </div>
        <div className="space-y-4">
          <Card title="Details">
            {e && ed ? (
              <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-sm">
                <dt className="text-slate-500">Road ID</dt><dd className="font-mono">{e.id}</dd>
                <dt className="text-slate-500">Flow</dt><dd>{num(e.flow_vph, 0)} veh/h</dd>
                <dt className="text-slate-500">Speed</dt><dd>{num(e.speed_ms, 1)} m/s (limit {ed.speed_ms})</dd>
                <dt className="text-slate-500">Current</dt><dd>{LEVEL_LABEL[e.level as Level]} · CI {num(e.ci)}</dd>
                <dt className="text-slate-500">Predicted</dt><dd>{e.pred_ci != null ? `${LEVEL_LABEL[e.pred_level as Level]} · CI ${num(e.pred_ci)}` : "–"}</dd>
                <dt className="text-slate-500">Horizon</dt><dd>{pred.data?.prediction?.horizon_s ? `${pred.data.prediction.horizon_s} s` : "–"}</dd>
              </dl>
            ) : jn ? (
              <div className="space-y-2 text-sm">
                <div className="font-mono">{jn.id}</div>
                <div className="text-slate-500">Neighbours: {jn.neighbors.join(", ")}</div>
                {recommended[jn.id] ? <Badge tone="teal">Recommended: {recommended[jn.id]}</Badge> : <span className="text-slate-500">No recommendation for this junction.</span>}
                <div><Link className="text-teal-700 underline" to="/scenario">Simulate an intervention here</Link></div>
              </div>
            ) : <p className="text-sm text-slate-500">Select a road segment or a junction on the map. Uncertainty is not shown because the model does not compute it.</p>}
          </Card>
          <Card title="Forecast">
            {pred.data?.available ? (
              <div className="space-y-1 text-sm">
                <SourceBadge source={pred.data.source} />
                <div>Horizon {pred.data.prediction.horizon_s}s · model {pred.data.prediction.model_version}</div>
                {pred.data.prediction.verification && <div className="text-xs text-slate-500">Check vs. simulation: MAE {num(pred.data.prediction.verification.mae, 3)} (persistence {num(pred.data.prediction.verification.persistence_mae, 3)})</div>}
                {iv && <div className="text-xs">Intervention: {iv.intervention?.label} <Badge>{iv.status}</Badge></div>}
              </div>
            ) : <p className="text-sm text-slate-500">No forecast available.</p>}
          </Card>
          <Card title="Alternative route (estimate)">
            <div className="space-y-2 text-sm">
              <label className="block text-xs text-slate-600">From
                <select className="mt-1 w-full rounded border border-slate-300 p-1" value={from} onChange={(e) => setFrom(e.target.value)}>
                  {boundary.filter((x) => /^(left|right|top|bottom)/.test(x.from)).map((x) => <option key={x.id}>{x.id}</option>)}
                </select></label>
              <label className="block text-xs text-slate-600">To
                <select className="mt-1 w-full rounded border border-slate-300 p-1" value={to} onChange={(e) => setTo(e.target.value)}>
                  {boundary.filter((x) => /^(left|right|top|bottom)/.test(x.to)).map((x) => <option key={x.id}>{x.id}</option>)}
                </select></label>
              <Button onClick={findRoute} variant="ghost">Compute route</Button>
              <ErrorBox error={routeErr} />
              {route && (
                <div className="text-xs text-slate-600">
                  {route.differs ? <>Alternative saves {num(route.default_time_predicted_s - route.alternative_time_predicted_s, 1)} s (predicted). Dotted dark = default, dashed blue = alternative.</> : "The default route is already best under the predicted state."}
                  <div className="mt-1 text-slate-500">{route.basis}</div>
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
