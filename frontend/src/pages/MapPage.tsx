import { Fragment, useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip as LeafletTooltip } from "react-leaflet";
import { Link, useSearchParams } from "react-router-dom";
import {
  api,
  ApiError,
  BengaluruSumoResult,
  Level,
  LiveRouteOption,
  LiveTrafficReading,
  LiveTrafficRoutes,
  NetworkData,
  ScenarioIn,
  toApiError,
} from "../api/client";
import { useAsync, useRunner } from "../hooks/useAsync";
import TrafficMap from "../components/TrafficMap";
import { ErrorBox, LEVEL_COLOR, LEVEL_LABEL, SourceBadge, num } from "../components/ui";
import defaultNetworkJson from "../api/defaultNetwork.json";

const defaultNetwork = defaultNetworkJson as unknown as NetworkData;

function flowColor(reading: LiveTrafficReading | null) {
  if (!reading) return "#94a3b8";
  return speedColor(reading.current_speed_kph, reading.free_flow_speed_kph);
}

function speedColor(speed: number | null, freeFlow: number) {
  if (speed == null) return "#94a3b8";
  const speedRatio = speed / freeFlow;
  return speedRatio >= 0.8 ? "#22c55e" : speedRatio >= 0.5 ? "#f59e0b" : "#ef4444";
}

function congestionColor(ci: number) {
  return ci < 0.3 ? "#22c55e" : ci < 0.6 ? "#f59e0b" : "#ef4444";
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
  const [computingRoute, setComputingRoute] = useState(false);

  useEffect(() => {
    const timer = window.setInterval(() => {
      live.reload();
      liveForecast.reload();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [live.reload, liveForecast.reload]);

  const networkData: NetworkData = net.data ?? defaultNetwork;

  const byId = useMemo(
    () => Object.fromEntries((pred.data?.available ? pred.data.edges : cur.data?.edges ?? []).map((e: any) => [e.id, e])),
    [pred.data, cur.data]
  );

  const hasState = cur.data?.available || pred.data?.available;

  const levels = useMemo(() => {
    const out: Record<string, Level> = {};
    const hasData = Object.keys(byId).length > 0;
    networkData.edges.forEach((ed) => {
      if (hasData && byId[ed.id]) {
        out[ed.id] = view === "predicted" ? (byId[ed.id].pred_level ?? "unknown") : byId[ed.id].level;
      } else {
        out[ed.id] = "low";
      }
    });
    return out;
  }, [byId, view, networkData]);

  const iv = pred.data?.intervention;
  const recommended: Record<string, string> = iv?.intervention?.junction_id
    ? { [iv.intervention.junction_id]: iv.intervention.label }
    : {};

  const e = edge ? byId[edge] : null;
  const ed = edge ? networkData.edges.find((x) => x.id === edge) : null;
  const jn = junction ? networkData.junctions.find((x) => x.id === junction) : null;
  const boundary = networkData.edges.filter((x) => /^(left|right|top|bottom)/.test(x.from) || /^(left|right|top|bottom)/.test(x.to));

  const routes = useMemo(() => {
    if (!route) return [];
    return [
      { id: "default", shape: route.default_shape, color: "#64748b", dash: "2 8" },
      ...(route.differs ? [{ id: "alt", shape: route.alternative_shape, color: "#00f0ff", dash: "10 6" }] : []),
    ];
  }, [route]);

  const liveSensors = live.data?.sensors ?? [];
  const selectedSensor = liveSensors.find((sensor) => sensor.id === liveSensorId) ?? liveSensors[0];
  const selectedReading = selectedSensor?.latest;
  const livePredictions = liveForecast.data?.sensors ?? [];
  const forecastBySensor = useMemo(
    () => new Map(livePredictions.map((forecast) => [forecast.sensor_id, forecast])),
    [livePredictions]
  );
  const selectedForecast = selectedSensor ? forecastBySensor.get(selectedSensor.id) : undefined;

  const findRoute = async () => {
    setComputingRoute(true);
    setRouteErr(null);
    try {
      setRoute(await api.altRoute(from, to));
    } catch (err) {
      setRouteErr(err);
      setRoute(null);
    } finally {
      setComputingRoute(false);
    }
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
    } catch (err) {
      setLiveRouteErr(toApiError(err));
    } finally {
      setLiveRouteBusy(false);
    }
  };

  const runBengaluruSumo = () => {
    const scenario: ScenarioIn = { pattern: "balanced", demand_scale: 1.0, seed: Math.floor(Date.now() / 1000) % 1_000_000 };
    void bengaluruRun.start(() => api.runBengaluruSumo(scenario));
  };

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-white md:text-3xl">
            Traffic Network Spatial Inspector
          </h1>
          <p className="mt-1 text-xs font-medium text-slate-400 md:text-sm">
            Interactive multi-layered GIS digital twin &amp; live arterial corridor telemetry
          </p>
        </div>

        {/* Source Switcher & Mode Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Main Source toggle */}
          <div role="group" aria-label="Traffic data source" className="flex items-center rounded-2xl border border-slate-700/80 bg-[#080d1a] p-1.5 shadow-xl">
            <button
              type="button"
              onClick={() => setSource("bengaluru")}
              aria-pressed={source === "bengaluru"}
              className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition ${
                source === "bengaluru"
                  ? "bg-gradient-to-r from-blue-600 to-cyan-500 text-white shadow-lg shadow-blue-500/25"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span className="flex h-2 w-2 rounded-full bg-cyan-400 animate-pulse" />
              <span>Bengaluru live</span>
            </button>
            <button
              type="button"
              onClick={() => setSource("simulation")}
              aria-pressed={source === "simulation"}
              className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition ${
                source === "simulation"
                  ? "bg-gradient-to-r from-blue-600 to-cyan-500 text-white shadow-lg shadow-blue-500/25"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
              <span>SUMO simulation</span>
            </button>
          </div>

          {/* Sub layer buttons */}
          {source === "simulation" && (
            <div role="group" aria-label="Simulation layer" className="flex items-center rounded-xl bg-slate-900 p-1 border border-slate-800">
              <button
                type="button"
                onClick={() => setView("current")}
                aria-pressed={view === "current"}
                className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                  view === "current" ? "bg-blue-600 text-white shadow" : "text-slate-400 hover:text-white"
                }`}
              >
                Current
              </button>
              <button
                type="button"
                onClick={() => setView("predicted")}
                aria-pressed={view === "predicted"}
                disabled={!pred.data?.available}
                className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                  view === "predicted"
                    ? "bg-gradient-to-r from-blue-600 to-cyan-500 text-white shadow"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                Predicted
              </button>
            </div>
          )}

          {source === "bengaluru" && (
            <div role="group" aria-label="Bengaluru traffic layer" className="flex items-center rounded-xl bg-slate-900 p-1 border border-slate-800">
              <button
                type="button"
                onClick={() => setLiveView("current")}
                aria-pressed={liveView === "current"}
                className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                  liveView === "current" ? "bg-blue-600 text-white shadow" : "text-slate-400 hover:text-white"
                }`}
              >
                Current TomTom
              </button>
              <button
                type="button"
                onClick={() => setLiveView("predicted")}
                aria-pressed={liveView === "predicted"}
                className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                  liveView === "predicted"
                    ? "bg-gradient-to-r from-blue-600 to-cyan-500 text-white shadow"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                TomTom trend
              </button>
            </div>
          )}

          {source === "bengaluru" && bengaluruRun.run?.status === "succeeded" && (
            <div role="group" aria-label="Bengaluru SUMO result layer" className="flex items-center rounded-xl bg-slate-900 p-1 border border-slate-800">
              <button
                type="button"
                onClick={() => setSumoView("current")}
                aria-pressed={sumoView === "current"}
                className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                  sumoView === "current" ? "bg-blue-600 text-white shadow" : "text-slate-400 hover:text-white"
                }`}
              >
                SUMO current
              </button>
              <button
                type="button"
                onClick={() => setSumoView("predicted")}
                aria-pressed={sumoView === "predicted"}
                className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                  sumoView === "predicted"
                    ? "bg-gradient-to-r from-blue-600 to-cyan-500 text-white shadow"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                GNN forecast
              </button>
            </div>
          )}
        </div>
      </div>

      {source === "bengaluru" ? (
        /* ==================== BENGALURU LIVE FEED VIEW ==================== */
        <div className="space-y-6">
          <div role="note" className="rounded-2xl border border-blue-500/20 bg-gradient-to-r from-[#0c1427] to-[#080d1a] p-3.5 text-xs text-slate-300 shadow-md backdrop-blur-md">
            The TomTom trend uses recent readings to estimate speeds on monitored roads. After running Bengaluru SUMO/GNN, click “Rank routes with GNN forecast” to rank TomTom route options by predicted congestion on matching OSM roads; uncovered route portions keep TomTom's ETA.
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            {/* Bengaluru Map (8 cols) */}
            <div className="flex flex-col justify-between overflow-hidden rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-2xl lg:col-span-8">
              <div>
                <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                  <div className="flex items-center gap-2">
                    <h2 className="text-base font-bold text-white tracking-wide">
                      Bengaluru Monitored Corridors Map
                    </h2>
                    <span className="rounded-full bg-cyan-500/20 px-2 py-0.5 text-[10px] font-bold text-cyan-300">
                      TomTom Live
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setBase(!base)}
                    className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition ${
                      base ? "border-cyan-500/40 bg-cyan-500/20 text-cyan-300" : "border-slate-700 bg-slate-800 text-slate-400"
                    }`}
                  >
                    OSM Basemap
                  </button>
                </div>

                <div className="relative mt-4 h-[500px] w-full overflow-hidden rounded-xl border border-slate-800/80 bg-[#070b16]">
                  <MapContainer center={[12.95, 77.65]} zoom={11.5} zoomControl={false} className="h-full w-full">
                    {base && <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" maxZoom={19} />}

                    {bengaluruRun.run?.status === "succeeded" &&
                      bengaluruRun.run.result?.edges.map((predictedEdge) => {
                        const ci = sumoView === "predicted" ? predictedEdge.pred_ci : predictedEdge.ci;
                        return (
                          <Polyline
                            key={`bengaluru-sumo-${predictedEdge.id}`}
                            positions={predictedEdge.shape}
                            pathOptions={{ color: congestionColor(ci), weight: 3, opacity: 0.75 }}
                          >
                            <LeafletTooltip sticky>
                              {predictedEdge.id} &bull; {sumoView === "predicted" ? "SUMO/GNN forecast" : "SUMO current"} &bull; congestion {ci.toFixed(2)}
                            </LeafletTooltip>
                          </Polyline>
                        );
                      })}

                    {liveSensors.map((sensor) => {
                      const reading = sensor.latest;
                      const forecast = forecastBySensor.get(sensor.id);
                      const predictedView = liveView === "predicted";
                      const isSelected = selectedSensor?.id === sensor.id;
                      const freeFlow = reading?.free_flow_speed_kph ?? 40;
                      const color = predictedView
                        ? speedColor(forecast?.predicted_speed_kph ?? null, freeFlow)
                        : flowColor(reading);

                      return (
                        <Fragment key={sensor.id}>
                          {!predictedView && reading?.geometry && (
                            <Polyline
                              positions={reading.geometry}
                              pathOptions={{ color, weight: 7, opacity: 0.9 }}
                              eventHandlers={{ click: () => setLiveSensorId(sensor.id) }}
                            >
                              <LeafletTooltip sticky>
                                {sensor.road_name} &bull; {reading.current_speed_kph.toFixed(1)} km/h
                              </LeafletTooltip>
                            </Polyline>
                          )}
                          {predictedView && forecast?.available && forecast.geometry && (
                            <Polyline
                              positions={forecast.geometry}
                              pathOptions={{ color, weight: 8, opacity: 0.9, dashArray: "10 8" }}
                              eventHandlers={{ click: () => setLiveSensorId(sensor.id) }}
                            >
                              <LeafletTooltip sticky>
                                {sensor.road_name} &bull; forecast {forecast.predicted_speed_kph?.toFixed(1)} km/h in 15 min
                              </LeafletTooltip>
                            </Polyline>
                          )}
                          <CircleMarker
                            center={[sensor.latitude, sensor.longitude]}
                            radius={isSelected ? 10 : 7}
                            pathOptions={{ color: isSelected ? "#00f0ff" : color, fillColor: color, fillOpacity: 0.9 }}
                            eventHandlers={{ click: () => setLiveSensorId(sensor.id) }}
                          >
                            <LeafletTooltip direction="top">
                              {sensor.road_name}
                              {predictedView
                                ? forecast?.available
                                  ? ` · forecast ${forecast.predicted_speed_kph?.toFixed(1)} km/h in 15 min`
                                  : " · forecast needs more readings"
                                : reading
                                ? ` · ${reading.current_speed_kph.toFixed(1)} km/h`
                                : " · waiting for data"}
                            </LeafletTooltip>
                          </CircleMarker>
                        </Fragment>
                      );
                    })}

                    {liveRouteOptions?.routes.map((option: LiveRouteOption) => (
                      <Polyline
                        key={`live-route-${option.rank}`}
                        positions={option.geometry}
                        pathOptions={{
                          color: option.rank === selectedLiveRoute ? "#00f0ff" : "#2563eb",
                          weight: option.rank === selectedLiveRoute ? 7 : 4,
                          opacity: option.rank === selectedLiveRoute ? 0.95 : 0.65,
                          dashArray: option.rank === selectedLiveRoute ? undefined : "8 8",
                        }}
                      >
                        <LeafletTooltip sticky>
                          {option.label} &bull; {((option.predicted_travel_time_s ?? option.travel_time_s) / 60).toFixed(0)} min estimated
                        </LeafletTooltip>
                      </Polyline>
                    ))}
                  </MapContainer>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-between border-t border-slate-800 pt-3 text-xs text-slate-400">
                <span>Green: Flowing (&gt;80% free flow) &bull; Amber: Sluggish &bull; Red: Congested</span>
                <Link to="/bengaluru" className="font-semibold text-cyan-400 hover:underline">
                  Full Corridor History &rarr;
                </Link>
              </div>
            </div>

            {/* Right Bengaluru Sensor Details & Controls (4 cols) */}
            <div className="space-y-6 lg:col-span-4">
              {/* Selected Sensor Card */}
              <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl text-xs">
                <div className="border-b border-slate-800 pb-3">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-cyan-400">
                    Live Road Details
                  </span>
                  <h3 className="text-base font-bold text-white">
                    {selectedSensor?.road_name ?? "Select a road"}
                  </h3>
                </div>

                <div className="mt-4 space-y-3">
                  <div>
                    <label className="text-[11px] font-semibold text-slate-400">Monitored road</label>
                    <select
                      className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white outline-none focus:border-cyan-500"
                      value={selectedSensor?.id}
                      onChange={(e) => setLiveSensorId(e.target.value)}
                    >
                      {liveSensors.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.road_name}
                        </option>
                      ))}
                    </select>
                  </div>

                  {selectedReading ? (
                    <div className="space-y-2 mt-2">
                      <div className="flex items-center justify-between rounded-xl bg-slate-900/60 p-2.5">
                        <span className="text-slate-400">Current speed</span>
                        <span className="font-mono font-bold text-white">
                          {num(selectedReading.current_speed_kph, 1)} km/h
                        </span>
                      </div>
                      {selectedForecast?.available && (
                        <div className="flex items-center justify-between rounded-xl bg-slate-900/60 p-2.5">
                          <span className="text-slate-400">Forecast (+15 min)</span>
                          <span className="font-mono font-bold text-cyan-400">
                            {`${num(selectedForecast.predicted_speed_kph, 1)} km/h · ${selectedForecast.congestion_level}`}
                          </span>
                        </div>
                      )}
                      <div className="flex items-center justify-between rounded-xl bg-slate-900/60 p-2.5">
                        <span className="text-slate-400">Free-flow speed</span>
                        <span className="font-mono font-bold text-slate-300">
                          {num(selectedReading.free_flow_speed_kph, 1)} km/h
                        </span>
                      </div>
                      <div className="flex items-center justify-between rounded-xl bg-slate-900/60 p-2.5">
                        <span className="text-slate-400">Travel time</span>
                        <span className="font-mono font-bold text-amber-400">
                          {num(selectedReading.current_travel_time_s, 0)} s
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-xl border border-dashed border-slate-800 p-4 text-center text-slate-400">
                      A point is shown, but TomTom has not returned a reading for it.
                    </div>
                  )}
                </div>
              </div>

              {/* Simulation with TomTom data (SUMO + GNN) */}
              <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl text-xs">
                <div className="border-b border-slate-800 pb-3">
                  <h3 className="text-sm font-bold text-white tracking-wide">
                    Simulate with TomTom data (SUMO + GNN)
                  </h3>
                </div>
                <div className="mt-3 space-y-3">
                  <p className="text-[11px] text-slate-400 leading-relaxed">
                    Runs SUMO on OpenStreetMap roads around the five monitored areas. Current TomTom speeds cap the matched SUMO road edges; the Bengaluru-specific GNN forecasts the resulting simulated traffic.
                  </p>
                  <button
                    type="button"
                    onClick={runBengaluruSumo}
                    disabled={bengaluruRun.busy || !live.data?.configured}
                    className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 py-2.5 font-bold text-white shadow-md shadow-blue-500/20 transition hover:brightness-110 disabled:opacity-50"
                  >
                    {bengaluruRun.busy ? "Running SUMO..." : "Run TomTom-calibrated simulation"}
                  </button>
                  <ErrorBox error={bengaluruRun.error} />
                  {bengaluruRun.run?.status === "succeeded" && bengaluruRun.run.result && (
                    <div className="space-y-1.5 rounded-xl border border-slate-800 bg-slate-900/80 p-3 text-slate-300 text-[11px]">
                      <div>GNN forecast: {bengaluruRun.run.result.horizon_s / 60} min ahead &bull; model {bengaluruRun.run.result.model_version}</div>
                      <div>TomTom speeds applied to {bengaluruRun.run.result.tomtom_speed_constraints_applied.length} matched OSM road(s).</div>
                    </div>
                  )}
                </div>
              </div>

              {/* Route Planner */}
              <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl text-xs">
                <div className="border-b border-slate-800 pb-3">
                  <h3 className="text-sm font-bold text-white tracking-wide">Find a live traffic-aware route</h3>
                </div>

                <div className="mt-4 space-y-3">
                  <div>
                    <label className="text-[11px] font-semibold text-slate-400">Origin</label>
                    <select
                      className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white outline-none focus:border-cyan-500"
                      value={liveOrigin}
                      onChange={(e) => {
                        setLiveOrigin(e.target.value);
                        setLiveRouteOptions(null);
                        setLiveRouteErr(null);
                      }}
                    >
                      {liveSensors.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.road_name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-[11px] font-semibold text-slate-400">Destination</label>
                    <select
                      className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white outline-none focus:border-cyan-500"
                      value={liveDestination}
                      onChange={(e) => {
                        setLiveDestination(e.target.value);
                        setLiveRouteOptions(null);
                        setLiveRouteErr(null);
                      }}
                    >
                      {liveSensors.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.road_name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <button
                    type="button"
                    onClick={findLiveRoutes}
                    disabled={liveRouteBusy || !live.data?.configured || liveSensors.length < 2 || liveOrigin === liveDestination}
                    className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 py-2.5 font-bold text-white transition hover:brightness-110 disabled:opacity-50"
                  >
                    {liveRouteBusy
                      ? "Finding routes..."
                      : bengaluruRun.run?.status === "succeeded"
                      ? "Rank routes with GNN forecast"
                      : "Find live routes"}
                  </button>
                  <ErrorBox error={liveRouteErr} />

                  {liveRouteOptions && (
                    <div className="space-y-2 mt-3">
                      <div className="text-[11px] text-slate-400">
                        {liveRouteOptions.origin.road_name} &rarr; {liveRouteOptions.destination.road_name}
                      </div>
                      {liveRouteOptions.routes.map((option) => (
                        <div
                          key={option.rank}
                          onClick={() => setSelectedLiveRoute(option.rank)}
                          className={`cursor-pointer rounded-xl border p-2.5 transition ${
                            selectedLiveRoute === option.rank
                              ? "border-cyan-500 bg-cyan-500/10 text-white"
                              : "border-slate-800 bg-slate-900/60 text-slate-400"
                          }`}
                        >
                          <div className="font-semibold text-white">
                            {option.recommended ? `Recommended · ${option.label}` : option.label}
                          </div>
                          <div className="flex justify-between mt-1 text-[11px]">
                            <span>
                              {`${(option.distance_m / 1000).toFixed(1)} km · ${
                                option.predicted_travel_time_s != null
                                  ? `${(option.predicted_travel_time_s / 60).toFixed(0)} min predicted`
                                  : `${(option.travel_time_s / 60).toFixed(0)} min current`
                              }`}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* ==================== SIMULATION DIGITAL TWIN VIEW ==================== */
        <div className="space-y-6">
          <div role="note" className="rounded-2xl border border-amber-500/20 bg-gradient-to-r from-[#17120a] to-[#080d1a] p-3 text-xs text-amber-300">
            {net.data?.notice ?? "Synthetic simulation network."} Road colours, forecasts and routes below use SUMO data; they are not TomTom observations.
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            {/* Main Map Box (8 Cols) */}
            <div className="flex flex-col justify-between overflow-hidden rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-2xl lg:col-span-8">
              <div>
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-bold text-white tracking-wide">
                      Microscopic Graph Canvas
                    </span>
                    <span className="rounded-full bg-blue-500/20 px-2 py-0.5 text-[10px] font-bold text-cyan-400">
                      48 Segments
                    </span>
                  </div>

                  <button
                    type="button"
                    onClick={() => setBase(!base)}
                    className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition ${
                      base ? "border-cyan-500/40 bg-cyan-500/20 text-cyan-300" : "border-slate-700 bg-slate-800 text-slate-400"
                    }`}
                  >
                    Dark Basemap
                  </button>
                </div>

                <div className="relative mt-4 h-[520px] w-full overflow-hidden rounded-xl border border-slate-800/80 bg-[#070b16]">
                  <TrafficMap
                    network={networkData}
                    levels={levels}
                    selectedEdge={edge}
                    selectedJunction={junction}
                    recommended={recommended}
                    routes={routes}
                    showBasemap={base}
                    onEdge={(id) => {
                      setEdge(id);
                      setJunction(null);
                    }}
                    onJunction={(id) => {
                      setJunction(id);
                      setEdge(null);
                    }}
                  />
                </div>
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800/80 pt-4 text-xs">
                <div className="flex items-center gap-4">
                  <span className="font-semibold text-slate-300">Congestion Level:</span>
                  <div className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-full bg-[#22c55e]" />
                    <span className="text-slate-400">Low (CI &lt; 0.3)</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-full bg-[#f59e0b]" />
                    <span className="text-slate-400">Moderate (0.3 - 0.6)</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-full bg-[#ef4444]" />
                    <span className="text-slate-400">High (CI &gt; 0.6)</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Right Sidebar: Segment Inspector & Dynamic Routing (4 Cols) */}
            <div className="space-y-6 lg:col-span-4">
              <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl text-xs">
                <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                  <h3 className="text-sm font-bold text-white tracking-wide">Segment Telemetry</h3>
                  {(edge || junction) && (
                    <button
                      type="button"
                      onClick={() => {
                        setEdge(null);
                        setJunction(null);
                      }}
                      className="text-[11px] text-slate-400 hover:text-white"
                    >
                      Reset
                    </button>
                  )}
                </div>

                <div className="mt-4 space-y-3">
                  {e && ed ? (
                    <div className="space-y-2.5">
                      <div className="flex items-center justify-between rounded-xl bg-slate-900/60 p-2.5">
                        <span className="text-slate-400">Segment ID</span>
                        <span className="font-mono font-bold text-white">{e.id}</span>
                      </div>
                      <div className="flex items-center justify-between rounded-xl bg-slate-900/60 p-2.5">
                        <span className="text-slate-400">Traffic Flow</span>
                        <span className="font-mono font-bold text-cyan-400">{num(e.flow_vph, 0)} veh/h</span>
                      </div>
                      <div className="flex items-center justify-between rounded-xl bg-slate-900/60 p-2.5">
                        <span className="text-slate-400">Vehicle Speed</span>
                        <span className="font-mono font-bold text-white">
                          {num(e.speed_ms * 3.6, 1)} km/h
                        </span>
                      </div>
                      <div className="flex items-center justify-between rounded-xl bg-slate-900/60 p-2.5">
                        <span className="text-slate-400">Congestion Index</span>
                        <span className="font-mono font-bold text-amber-400">{num(e.ci, 2)} ({e.level})</span>
                      </div>
                    </div>
                  ) : jn ? (
                    <div className="space-y-3">
                      <div className="rounded-xl bg-slate-900/60 p-3">
                        <div className="text-slate-400">Signalized Intersection</div>
                        <div className="mt-1 font-mono text-base font-bold text-cyan-400">{jn.id}</div>
                      </div>
                      <Link
                        to="/scenario"
                        className="block text-center rounded-xl bg-blue-600/20 py-2 font-bold text-cyan-400 border border-blue-500/30 hover:bg-blue-600/30 transition"
                      >
                        Simulate Timing Intervention &rarr;
                      </Link>
                    </div>
                  ) : (
                    <div className="rounded-xl border border-dashed border-slate-800 p-4 text-center text-slate-400">
                      Click any road polyline or junction marker on the map to inspect live parameters.
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl text-xs">
                <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
                  <h3 className="text-sm font-bold text-white tracking-wide">Dynamic Route Engine</h3>
                </div>

                <div className="mt-4 space-y-3">
                  <div>
                    <label className="text-[11px] font-semibold text-slate-400">From</label>
                    <select
                      className="mt-1 w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-xs text-slate-200 outline-none focus:border-cyan-500"
                      value={from}
                      onChange={(e) => setFrom(e.target.value)}
                    >
                      {boundary
                        .filter((x) => /^(left|right|top|bottom)/.test(x.from))
                        .map((x) => (
                          <option key={x.id} value={x.id}>
                            {x.id}
                          </option>
                        ))}
                    </select>
                  </div>

                  <div>
                    <label className="text-[11px] font-semibold text-slate-400">To</label>
                    <select
                      className="mt-1 w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-xs text-slate-200 outline-none focus:border-cyan-500"
                      value={to}
                      onChange={(e) => setTo(e.target.value)}
                    >
                      {boundary
                        .filter((x) => /^(left|right|top|bottom)/.test(x.to))
                        .map((x) => (
                          <option key={x.id} value={x.id}>
                            {x.id}
                          </option>
                        ))}
                    </select>
                  </div>

                  <button
                    type="button"
                    onClick={findRoute}
                    disabled={computingRoute}
                    className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 py-2.5 font-bold text-white shadow-md shadow-blue-500/20 transition hover:brightness-110 disabled:opacity-50"
                  >
                    {computingRoute ? "Computing Route..." : "Compute Optimal Route"}
                  </button>

                  {route && (
                    <div className="rounded-xl border border-slate-700/80 bg-slate-900/80 p-3">
                      {route.differs ? (
                        <div className="space-y-1 text-cyan-300">
                          <div className="font-semibold">
                            Alternative route saves{" "}
                            <span className="font-bold text-white">
                              {num(route.default_time_predicted_s - route.alternative_time_predicted_s, 1)}s
                            </span>
                          </div>
                        </div>
                      ) : (
                        <div className="text-slate-300">
                          The default route is already optimal under current forecast conditions.
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
