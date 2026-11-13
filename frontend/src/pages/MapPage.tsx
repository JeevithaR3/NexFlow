import { Fragment, useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from "react-leaflet";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError, BengaluruSumoResult, Level, LiveRouteOption, LiveTrafficReading, LiveTrafficRoutes, ScenarioIn, toApiError } from "../api/client";
import { useAsync, useRunner } from "../hooks/useAsync";
import TrafficMap from "../components/TrafficMap";
import { Badge, Button, Card, Empty, ErrorBox, LEVEL_LABEL, Loading, LevelLegend, SourceBadge, num } from "../components/ui";

function flowColor(reading: LiveTrafficReading | null) {
  if (!reading) return "#94a3b8";
  return speedColor(reading.current_speed_kph, reading.free_flow_speed_kph);
}

function speedColor(speed: number | null, freeFlow: number) {
  if (speed == null) return "#94a3b8";
  const speedRatio = speed / freeFlow;
  return speedRatio >= 0.8 ? "#16a34a" : speedRatio >= 0.5 ? "#eab308" : "#dc2626";
}

function congestionColor(ci: number) {
  return ci < 0.3 ? "#16a34a" : ci < 0.6 ? "#eab308" : "#dc2626";
}

export default function MapPage() {
  const net = useAsync(() => api.network());
  const pred = useAsync(() => api.trafficPredictions());
  const cur = useAsync(() => api.trafficCurrent());
  const live = useAsync(() => api.bengaluruTraffic());
  const liveForecast = useAsync(() => api.bengaluruPredictions());
  const bengaluruRun = useRunner<BengaluruSumoResult>();
  const [searchParams, setSearchParams] = useSearchParams();
  const source = searchParams.get("source") === "simulation" ? "simulation" : "bengaluru";
  const setSource = (next: "bengaluru" | "simulation") => {
    const params = new URLSearchParams(searchParams);
    params.set("source", next);
    setSearchParams(params);
  };
  const [view, setView] = useState<"current" | "predicted">("current");
  const [liveView, setLiveView] = useState<"current" | "predicted">("predicted");
  const [sumoView, setSumoView] = useState<"current" | "predicted">("predicted");
  const [base, setBase] = useState(true);
  const [edge, setEdge] = useState<string | null>(null);
  const [junction, setJunction] = useState<string | null>(null);
  const [liveSensorId, setLiveSensorId] = useState<string | null>(null);
  const [route, setRoute] = useState<any>(null);
  const [routeErr, setRouteErr] = useState<any>(null);
  const [liveRouteOptions, setLiveRouteOptions] = useState<LiveTrafficRoutes | null>(null);
  const [liveRouteErr, setLiveRouteErr] = useState<ApiError | null>(null);
  const [liveRouteBusy, setLiveRouteBusy] = useState(false);
  const [liveOrigin, setLiveOrigin] = useState("mg-road");
  const [liveDestination, setLiveDestination] = useState("silk-board");
  const [selectedLiveRoute, setSelectedLiveRoute] = useState(1);
  const [from, setFrom] = useState("left1A1");
  const [to, setTo] = useState("C1right1");

  useEffect(() => {
    const timer = window.setInterval(() => {
      live.reload();
      liveForecast.reload();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [live.reload, liveForecast.reload]);

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
  const liveSensors = live.data?.sensors ?? [];
  const selectedSensor = liveSensors.find((sensor) => sensor.id === liveSensorId) ?? liveSensors[0];
  const selectedReading = selectedSensor?.latest;
  const livePredictions = liveForecast.data?.sensors ?? [];
  const forecastBySensor = useMemo(
    () => new Map(livePredictions.map((forecast) => [forecast.sensor_id, forecast])),
    [livePredictions],
  );
  const selectedForecast = selectedSensor ? forecastBySensor.get(selectedSensor.id) : undefined;

  const findRoute = async () => {
    setRouteErr(null);
    try { setRoute(await api.altRoute(from, to)); } catch (err) { setRouteErr(err); setRoute(null); }
  };
  const findLiveRoutes = async () => {
    setLiveRouteBusy(true);
    setLiveRouteErr(null);
    setLiveRouteOptions(null);
    try {
      const simulationRunId = bengaluruRun.run?.status === "succeeded" ? bengaluruRun.run.id : undefined;
      const options = await api.bengaluruRoutes(liveOrigin, liveDestination, simulationRunId);
      setLiveRouteOptions(options);
      setSelectedLiveRoute(options.routes.find((option) => option.recommended)?.rank ?? options.routes[0]?.rank ?? 1);
    } catch (error) {
      setLiveRouteErr(toApiError(error));
    } finally {
      setLiveRouteBusy(false);
    }
  };
  const runBengaluruSumo = () => {
    const scenario: ScenarioIn = { pattern: "balanced", demand_scale: 1.0, seed: Math.floor(Date.now() / 1000) % 1_000_000 };
    void bengaluruRun.start(() => api.runBengaluruSumo(scenario));
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
          <p className="text-sm text-slate-600">Switch between live Bengaluru observations and SUMO simulation results.</p>
        </div>
        <div className="flex items-center gap-2">
          <div role="group" aria-label="Traffic data source" className="inline-flex overflow-hidden rounded-lg border border-slate-300">
            {(["bengaluru", "simulation"] as const).map((v) => (
              <button key={v} onClick={() => setSource(v)} aria-pressed={source === v}
                className={`px-3 py-1.5 text-sm ${source === v ? "bg-teal-700 text-white" : "bg-white text-slate-700"}`}>
                {v === "bengaluru" ? "Bengaluru live" : "SUMO simulation"}
              </button>
            ))}
          </div>
          {source === "simulation" && <div role="group" aria-label="Simulation layer" className="inline-flex overflow-hidden rounded-lg border border-slate-300">
            {(["current", "predicted"] as const).map((v) => (
              <button key={v} onClick={() => setView(v)} aria-pressed={view === v} disabled={v === "predicted" && !pred.data?.available}
                className={`px-3 py-1.5 text-sm ${view === v ? "bg-slate-700 text-white" : "bg-white text-slate-700"} disabled:opacity-40`}>
                {v === "current" ? "Current" : "Predicted"}
              </button>
            ))}
          </div>}
          {source === "bengaluru" && <div role="group" aria-label="Bengaluru traffic layer" className="inline-flex overflow-hidden rounded-lg border border-slate-300">
            {(["current", "predicted"] as const).map((v) => (
              <button key={v} onClick={() => setLiveView(v)} aria-pressed={liveView === v}
                className={`px-3 py-1.5 text-sm ${liveView === v ? "bg-teal-700 text-white" : "bg-white text-slate-700"}`}>
                {v === "current" ? "Current TomTom" : "TomTom trend"}
              </button>
            ))}
          </div>}
          {source === "bengaluru" && bengaluruRun.run?.status === "succeeded" && <div role="group" aria-label="Bengaluru SUMO result layer" className="inline-flex overflow-hidden rounded-lg border border-slate-300">
            {(["current", "predicted"] as const).map((v) => (
              <button key={v} onClick={() => setSumoView(v)} aria-pressed={sumoView === v}
                className={`px-3 py-1.5 text-sm ${sumoView === v ? "bg-slate-700 text-white" : "bg-white text-slate-700"}`}>
                {v === "current" ? "SUMO current" : "GNN forecast"}
              </button>
            ))}
          </div>}
          <label className="flex items-center gap-1 text-xs text-slate-600"><input type="checkbox" checked={base} onChange={(e) => setBase(e.target.checked)} /> OSM basemap</label>
        </div>
      </header>
      {source === "bengaluru" ? (
        <>
          <div role="note" className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs text-blue-900">
            The TomTom trend uses recent readings to estimate speeds on monitored roads. After running Bengaluru SUMO/GNN, click “Rank routes with GNN forecast” to rank TomTom route options by predicted congestion on matching OSM roads; uncovered route portions keep TomTom's ETA.
          </div>
          <ErrorBox error={live.error} />
          <ErrorBox error={liveForecast.error} />
          {liveView === "predicted" && !liveForecast.data?.available && (
            <div role="note" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              Real-road forecasts are not ready yet. Each road needs at least three TomTom readings spanning two poll intervals; the collector runs every {live.data?.poll_interval_s ?? 300} seconds.
            </div>
          )}
          {!live.data?.configured && (
            <div role="note" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              TomTom is not configured, so no live readings are available yet. Set <code>NEXFLOW_TOMTOM_API_KEY</code> in the backend environment, restart it, then use <Link className="underline" to="/bengaluru">traffic history</Link>.
            </div>
          )}
          {live.data?.last_error && <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{live.data.last_error}</div>}
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="space-y-2 lg:col-span-2">
              {live.loading && !live.data ? <Loading label="Loading Bengaluru traffic…" /> : (
                <MapContainer center={[12.95, 77.65]} zoom={11.5} scrollWheelZoom style={{ height: 560, width: "100%" }} className="overflow-hidden rounded-xl border border-slate-200">
                  {base && <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />}
                  {bengaluruRun.run?.status === "succeeded" && bengaluruRun.run.result?.edges.map((predictedEdge) => {
                    const ci = sumoView === "predicted" ? predictedEdge.pred_ci : predictedEdge.ci;
                    return (
                      <Polyline key={`bengaluru-sumo-${predictedEdge.id}`} positions={predictedEdge.shape}
                        pathOptions={{ color: congestionColor(ci), weight: 3, opacity: 0.75 }}>
                        <Tooltip sticky>{predictedEdge.id} · {sumoView === "predicted" ? "SUMO/GNN forecast" : "SUMO current"}
                          · congestion {ci.toFixed(2)}</Tooltip>
                      </Polyline>
                    );
                  })}
                  {liveSensors.map((sensor) => {
                    const reading = sensor.latest;
                    const forecast = forecastBySensor.get(sensor.id);
                    const predictedView = liveView === "predicted";
                    const color = predictedView
                      ? speedColor(forecast?.predicted_speed_kph ?? null, reading?.free_flow_speed_kph ?? 1)
                      : flowColor(reading);
                    return (
                      <Fragment key={sensor.id}>
                        {!predictedView && reading?.geometry && <Polyline positions={reading.geometry} pathOptions={{ color, weight: 7, opacity: 0.9 }}
                          eventHandlers={{ click: () => setLiveSensorId(sensor.id) }}>
                          <Tooltip sticky>{sensor.road_name} · {reading.current_speed_kph.toFixed(1)} km/h</Tooltip>
                        </Polyline>}
                        {predictedView && forecast?.available && forecast.geometry && <Polyline
                          positions={forecast.geometry}
                          pathOptions={{ color, weight: 8, opacity: 0.9, dashArray: "10 8" }}
                          eventHandlers={{ click: () => setLiveSensorId(sensor.id) }}>
                          <Tooltip sticky>{sensor.road_name} · forecast {forecast.predicted_speed_kph?.toFixed(1)} km/h in 15 min</Tooltip>
                        </Polyline>}
                        <CircleMarker center={[sensor.latitude, sensor.longitude]} radius={selectedSensor?.id === sensor.id ? 10 : 7}
                          pathOptions={{ color, fillColor: color, fillOpacity: 0.9 }}
                          eventHandlers={{ click: () => setLiveSensorId(sensor.id) }}>
                          <Tooltip direction="top">{sensor.road_name}{predictedView
                            ? forecast?.available ? ` · forecast ${forecast.predicted_speed_kph?.toFixed(1)} km/h in 15 min` : " · forecast needs more readings"
                            : reading ? ` · ${reading.current_speed_kph.toFixed(1)} km/h` : " · waiting for data"}</Tooltip>
                        </CircleMarker>
                      </Fragment>
                    );
                  })}
                  {liveRouteOptions?.routes.map((option: LiveRouteOption) => (
                    <Polyline key={`live-route-${option.rank}`} positions={option.geometry}
                      pathOptions={{
                        color: option.rank === selectedLiveRoute ? "#7c3aed" : "#2563eb",
                        weight: option.rank === selectedLiveRoute ? 7 : 4,
                        opacity: option.rank === selectedLiveRoute ? 0.95 : 0.65,
                        dashArray: option.rank === selectedLiveRoute ? undefined : "8 8",
                      }}>
                      <Tooltip sticky>{option.label} · {((option.predicted_travel_time_s ?? option.travel_time_s) / 60).toFixed(0)} min estimated</Tooltip>
                    </Polyline>
                  ))}
                </MapContainer>
              )}
              <div className="flex flex-wrap gap-3 text-xs text-slate-600">
                <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-green-600" />≥80% of free-flow speed</span>
                <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-yellow-500" />50–80%</span>
                <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-red-600" />&lt;50%</span>
                <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-slate-400" />No reading</span>
                {liveView === "predicted" && <span><span className="mr-1 inline-block h-1 w-5 border-t-2 border-dashed border-slate-700 align-middle" />TomTom-history trend forecast</span>}
                {bengaluruRun.run?.status === "succeeded" && <span><span className="mr-1 inline-block h-1 w-5 border-t-2 border-slate-700 align-middle" />OSM road state: {sumoView === "predicted" ? "GNN forecast" : "SUMO simulated current"}</span>}
                {liveRouteOptions && <span><span className="mr-1 inline-block h-1 w-5 bg-violet-700 align-middle" />Selected live route · dashed blue alternatives</span>}
              </div>
            </div>
            <div className="space-y-4">
              <Card title="Live road details">
                {selectedSensor ? (
                  <div className="space-y-3">
                    <label className="block text-xs text-slate-600">Monitored road
                      <select className="mt-1 w-full rounded border border-slate-300 p-2 text-sm" value={selectedSensor.id}
                        onChange={(event) => setLiveSensorId(event.target.value)}>
                        {liveSensors.map((sensor) => <option key={sensor.id} value={sensor.id}>{sensor.road_name}</option>)}
                      </select>
                    </label>
                    {selectedReading ? (
                      <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-sm">
                        <dt className="text-slate-500">Current speed</dt><dd>{num(selectedReading.current_speed_kph, 1)} km/h</dd>
                        {selectedForecast?.available && <>
                          <dt className="text-slate-500">Forecast (+15 min)</dt><dd>{num(selectedForecast.predicted_speed_kph, 1)} km/h · {selectedForecast.congestion_level}</dd>
                          <dt className="text-slate-500">Forecast samples</dt><dd>{selectedForecast.sample_count} readings</dd>
                        </>}
                        <dt className="text-slate-500">Free-flow speed</dt><dd>{num(selectedReading.free_flow_speed_kph, 1)} km/h</dd>
                        <dt className="text-slate-500">Travel time</dt><dd>{num(selectedReading.current_travel_time_s, 0)} s</dd>
                        <dt className="text-slate-500">Confidence</dt><dd>{num(selectedReading.confidence * 100, 0)}%</dd>
                        <dt className="text-slate-500">Observed</dt><dd>{new Date(selectedReading.observed_at).toLocaleTimeString()}</dd>
                        {selectedReading.road_closure && <><dt className="col-span-2"><Badge tone="red">Road closure reported</Badge></dt></>}
                      </dl>
                    ) : <Empty title="No reading for this road yet">A point is shown, but TomTom has not returned a reading for it.</Empty>}
                  </div>
                ) : <Empty title="No monitored roads configured">Check the backend traffic collector configuration.</Empty>}
              </Card>
              <Card title="Traffic history">
                <p className="text-sm text-slate-600">See collected speeds over time for all five corridors.</p>
                <Link className="mt-2 inline-block text-sm font-medium text-teal-800 underline" to="/bengaluru">Open Bengaluru traffic history</Link>
                <p className="mt-2 text-xs text-slate-500">Last collection: {live.data?.last_poll_at ? new Date(live.data.last_poll_at).toLocaleString() : "none yet"} · {live.data?.observation_count ?? 0} stored readings</p>
              </Card>
              <Card title="Simulate with TomTom data (SUMO + GNN)">
                <div className="space-y-3">
                  <p className="text-xs text-slate-600">
                    Runs SUMO on OpenStreetMap roads around the five monitored areas. Current TomTom speeds cap the matched SUMO road edges; the Bengaluru-specific GNN forecasts the resulting simulated traffic. Road data © OpenStreetMap contributors (ODbL).
                  </p>
                  <Button onClick={runBengaluruSumo} disabled={bengaluruRun.busy || !live.data?.configured}>
                    {bengaluruRun.busy ? "Running SUMO…" : "Run TomTom-calibrated simulation"}
                  </Button>
                  <ErrorBox error={bengaluruRun.error} />
                  {bengaluruRun.run?.status === "succeeded" && bengaluruRun.run.result && (
                    <div className="space-y-2 text-xs text-slate-700">
                      <p>GNN forecast: {bengaluruRun.run.result.horizon_s / 60} min ahead · model {bengaluruRun.run.result.model_version}</p>
                      <p>TomTom speeds applied to {bengaluruRun.run.result.tomtom_speed_constraints_applied.length} matched OSM road(s).</p>
                      <p>{bengaluruRun.run.result.notice}</p>
                    </div>
                  )}
                  {!live.data?.configured && <p className="text-xs text-amber-700">Configure TomTom to provide live speed inputs.</p>}
                </div>
              </Card>
              <Card title="Find a live traffic-aware route">
                <div className="space-y-3">
                  <p className="text-xs text-slate-600">
                    TomTom supplies route options and current ETAs. {bengaluruRun.run?.status === "succeeded"
                      ? "NexFlow ranks them using the SUMO/GNN forecast on matching OSM roads."
                      : "Run the Bengaluru SUMO/GNN simulation first to rank options using its forecast; otherwise the TomTom-history trend is used when available."}
                    {" "}Start with MG Road → Silk Board.
                  </p>
                  <label className="block text-xs text-slate-600">Origin
                    <select className="mt-1 w-full rounded border border-slate-300 p-2 text-sm" value={liveOrigin} onChange={(event) => {
                      setLiveOrigin(event.target.value);
                      setLiveRouteOptions(null);
                      setLiveRouteErr(null);
                    }}>
                      {liveSensors.map((sensor) => <option key={sensor.id} value={sensor.id}>{sensor.road_name}</option>)}
                    </select>
                  </label>
                  <label className="block text-xs text-slate-600">Destination
                    <select className="mt-1 w-full rounded border border-slate-300 p-2 text-sm" value={liveDestination} onChange={(event) => {
                      setLiveDestination(event.target.value);
                      setLiveRouteOptions(null);
                      setLiveRouteErr(null);
                    }}>
                      {liveSensors.map((sensor) => <option key={sensor.id} value={sensor.id}>{sensor.road_name}</option>)}
                    </select>
                  </label>
                  <Button onClick={findLiveRoutes} disabled={liveRouteBusy || !live.data?.configured || liveSensors.length < 2 || liveOrigin === liveDestination}>
                    {liveRouteBusy ? "Finding routes…" : bengaluruRun.run?.status === "succeeded" ? "Rank routes with GNN forecast" : "Find live routes"}
                  </Button>
                  {liveOrigin === liveDestination && <p className="text-xs text-amber-700">Choose different origin and destination roads.</p>}
                  <ErrorBox error={liveRouteErr} />
                  {liveRouteOptions && (
                    <div className="space-y-2">
                      <p className="text-xs text-slate-600">{liveRouteOptions.origin.road_name} → {liveRouteOptions.destination.road_name}</p>
                      {liveRouteOptions.routes.map((option) => (
                        <button key={option.rank} type="button" onClick={() => setSelectedLiveRoute(option.rank)}
                          aria-pressed={selectedLiveRoute === option.rank}
                          className={`block w-full rounded-lg border p-2 text-left text-sm ${selectedLiveRoute === option.rank ? "border-violet-500 bg-violet-50" : "border-slate-200 bg-white"}`}>
                          <span className="font-medium">{option.recommended ? `Recommended · ${option.label}` : option.label}</span>
                          <span className="block text-xs text-slate-600">
                            {(option.distance_m / 1000).toFixed(1)} km · {option.predicted_travel_time_s != null
                              ? `${(option.predicted_travel_time_s / 60).toFixed(0)} min predicted`
                              : `${(option.travel_time_s / 60).toFixed(0)} min current`}
                            {option.traffic_delay_s != null ? ` · ${Math.round(option.traffic_delay_s / 60)} min traffic delay` : ""}
                          </span>
                          {option.predicted_travel_time_s != null && <span className="block text-xs text-slate-500">
                          TomTom current ETA: {(option.travel_time_s / 60).toFixed(0)} min · {liveRouteOptions.forecast_source === "bengaluru_sumo_gnn"
                            ? `${option.simulation_forecast_coverage_pct ?? 0}% of route matched to ${option.simulation_forecast_edge_count ?? 0} predicted OSM road(s)`
                            : `${option.forecast_sensor_count} TomTom trend segment(s) matched`}
                          </span>}
                        </button>
                      ))}
                      <p className="text-xs text-slate-500">{liveRouteOptions.notice}</p>
                    </div>
                  )}
                  {!live.data?.configured && <p className="text-xs text-amber-700">Configure the TomTom key to request live routes.</p>}
                </div>
              </Card>
            </div>
          </div>
        </>
      ) : (
        <>
          <div role="note" className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
            {net.data?.notice ?? "Synthetic simulation network."} Road colours, forecasts and routes below use SUMO data; they are not TomTom observations.
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
              {!hasState && !cur.loading && <Empty title="No simulation state yet">Run a prediction from the Overview page.</Empty>}
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
      )}
    </>
  );
}
