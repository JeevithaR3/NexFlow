import { Fragment, useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from "react-leaflet";
import { Link } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from "recharts";
import { ApiError, LiveTrafficReading, api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { ErrorBox, Loading, num } from "../components/ui";

const COLORS = ["#00f0ff", "#3b82f6", "#a855f7", "#f59e0b", "#ef4444", "#10b981", "#ec4899"];

function roadColor(reading: LiveTrafficReading | null) {
  if (!reading) return "#64748b";
  const ratio = reading.current_speed_kph / reading.free_flow_speed_kph;
  return ratio >= 0.8 ? "#22c55e" : ratio >= 0.5 ? "#f59e0b" : "#ef4444";
}

function localTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : "No readings yet";
}

export default function BengaluruTraffic() {
  const status = useAsync(() => api.bengaluruTraffic());
  const history = useAsync(() => api.bengaluruTrafficHistory());
  const [polling, setPolling] = useState(false);
  const [pollError, setPollError] = useState<ApiError | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setInterval(() => {
      status.reload();
      history.reload();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [status.reload, history.reload]);

  const trend = useMemo(() => {
    const grouped = new Map<string, Record<string, string | number>>();
    for (const reading of history.data?.readings ?? []) {
      const point = grouped.get(reading.observed_at) ?? { observed_at: reading.observed_at };
      point[reading.sensor_id] = reading.current_speed_kph;
      grouped.set(reading.observed_at, point);
    }
    return [...grouped.values()];
  }, [history.data]);

  const refresh = async () => {
    setPolling(true);
    setPollError(null);
    try {
      await api.pollBengaluruTraffic();
      status.reload();
      history.reload();
    } catch (error) {
      setPollError(error instanceof ApiError ? error : new ApiError("Unable to poll TomTom traffic.", "poll_failed"));
    } finally {
      setPolling(false);
    }
  };

  const sensors = status.data?.sensors ?? [];
  const selectedSensor = sensors.find((sensor) => sensor.id === selected) ?? sensors[0];
  const selectedReading = selectedSensor?.latest;

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-extrabold tracking-tight text-white md:text-3xl">
              Bengaluru Arterial Traffic History
            </h1>
            <span className="flex items-center gap-1.5 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2.5 py-0.5 text-xs font-semibold text-cyan-300">
              <span className="h-2 w-2 rounded-full bg-cyan-400 animate-pulse" />
              TomTom Live Feed
            </span>
          </div>
          <p className="mt-1 text-xs font-medium text-slate-400 md:text-sm">
            Continuous real-world traffic telemetry and velocity trajectories for Bengaluru corridors
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <Link
            to="/map?source=bengaluru"
            className="flex items-center gap-2 rounded-xl border border-slate-700/80 bg-slate-800/80 px-4 py-2 text-xs font-bold text-slate-200 transition hover:bg-slate-700 hover:text-white"
          >
            <svg className="h-4 w-4 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
            </svg>
            <span>Open Live Map</span>
          </Link>
          <button
            type="button"
            onClick={refresh}
            disabled={polling || !status.data?.configured}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 px-4 py-2 text-xs font-bold text-white shadow-lg shadow-blue-500/25 transition hover:brightness-110 disabled:opacity-50"
          >
            {polling ? (
              <>
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                <span>Polling API...</span>
              </>
            ) : (
              <>
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                <span>Poll Now</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Note banner */}
      <div
        role="note"
        className="rounded-2xl border border-blue-500/20 bg-gradient-to-r from-[#0c1427] to-[#080d1a] p-3.5 text-xs text-slate-300 shadow-md backdrop-blur-md"
      >
        <div className="flex items-center gap-2">
          <span className="flex h-2 w-2 rounded-full bg-cyan-400" />
          <span className="font-semibold text-white">Real-World City Context:</span>
        </div>
        <p className="mt-1 text-slate-400 leading-relaxed">
          Live TomTom observations are collected independently of the synthetic SUMO / GNN demo. This page monitors key arterial corridors to provide real-world context; no live reading controls real signals.
        </p>
      </div>

      <ErrorBox error={status.error} />
      <ErrorBox error={history.error} />
      <ErrorBox error={pollError} />

      {status.loading && !status.data ? (
        <Loading />
      ) : status.data && (
        <>
          {!status.data.configured && (
            <div role="note" className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3.5 text-xs text-amber-300">
              TomTom is not configured. Set <code className="font-mono text-white">NEXFLOW_TOMTOM_API_KEY</code> in the backend environment. The key remains on the server and is never exposed to the frontend.
            </div>
          )}

          {status.data.last_error && (
            <div role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3.5 text-xs text-rose-300">
              {status.data.last_error}
            </div>
          )}

          {/* 4 Stat Cards */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-b from-[#0e1628] to-[#0a1120] p-4 shadow-xl">
              <div className="text-[11px] font-semibold tracking-wider uppercase text-slate-400">Provider</div>
              <div className="mt-2 font-mono text-2xl font-extrabold text-white">{status.data.provider}</div>
              <div className="mt-1 text-[11px] text-cyan-400">
                {status.data.polling_enabled ? `Auto-poll every ${status.data.poll_interval_s / 60}m` : "Manual Polling"}
              </div>
            </div>

            <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-b from-[#0e1628] to-[#0a1120] p-4 shadow-xl">
              <div className="text-[11px] font-semibold tracking-wider uppercase text-slate-400">Monitored Roads</div>
              <div className="mt-2 font-mono text-2xl font-extrabold text-cyan-400">{sensors.length}</div>
              <div className="mt-1 text-[11px] text-slate-500">Major arterials</div>
            </div>

            <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-b from-[#0e1628] to-[#0a1120] p-4 shadow-xl">
              <div className="text-[11px] font-semibold tracking-wider uppercase text-slate-400">Stored Readings</div>
              <div className="mt-2 font-mono text-2xl font-extrabold text-emerald-400">
                {status.data.observation_count}
              </div>
              <div className="mt-1 text-[11px] text-slate-500">Since tracking started</div>
            </div>

            <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-b from-[#0e1628] to-[#0a1120] p-4 shadow-xl">
              <div className="text-[11px] font-semibold tracking-wider uppercase text-slate-400">Last Collected</div>
              <div className="mt-2 font-mono text-sm font-bold text-slate-200 truncate">
                {status.data.last_poll_at ? new Date(status.data.last_poll_at).toLocaleTimeString() : "No polls yet"}
              </div>
              <div className="mt-1 text-[11px] text-slate-500 truncate">
                {status.data.last_poll_at ? new Date(status.data.last_poll_at).toLocaleDateString() : "Waiting"}
              </div>
            </div>
          </div>

          {/* Map & Corridor Selector Grid */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            {/* Map (8 cols) */}
            <div className="overflow-hidden rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-2xl lg:col-span-8">
              <div className="border-b border-slate-800 pb-3">
                <h2 className="text-sm font-bold text-white tracking-wide">
                  Monitored Corridors &bull; Live Velocities
                </h2>
              </div>

              <div className="relative mt-4 h-[400px] w-full overflow-hidden rounded-xl border border-slate-800/80 bg-[#070b16]">
                <MapContainer center={[12.9716, 77.5946]} zoom={12} zoomControl={false} className="h-full w-full">
                  <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" maxZoom={19} />
                  {sensors.map((sensor) => {
                    const reading = sensor.latest;
                    const color = roadColor(reading);
                    return (
                      <Fragment key={sensor.id}>
                        {reading?.geometry && (
                          <Polyline
                            positions={reading.geometry}
                            pathOptions={{ color, weight: 6, opacity: 0.85 }}
                            eventHandlers={{ click: () => setSelected(sensor.id) }}
                          >
                            <Tooltip sticky>
                              {sensor.road_name} &bull; {reading.current_speed_kph.toFixed(1)} km/h
                            </Tooltip>
                          </Polyline>
                        )}
                        <CircleMarker
                          center={[sensor.latitude, sensor.longitude]}
                          radius={selectedSensor?.id === sensor.id ? 10 : 7}
                          pathOptions={{ color, fillColor: color, fillOpacity: 0.9 }}
                          eventHandlers={{ click: () => setSelected(sensor.id) }}
                        >
                          <Tooltip direction="top">
                            {sensor.road_name}
                            {reading ? ` &bull; ${reading.current_speed_kph.toFixed(1)} km/h` : " &bull; waiting"}
                          </Tooltip>
                        </CircleMarker>
                      </Fragment>
                    );
                  })}
                </MapContainer>
              </div>

              <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-400">
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                  <span>Flowing (&gt;80% free flow)</span>
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-amber-500" />
                  <span>Sluggish (50&ndash;80%)</span>
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-rose-500" />
                  <span>Congested (&lt;50%)</span>
                </span>
              </div>
            </div>

            {/* Selected Corridor Details (4 cols) */}
            <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-xl text-xs lg:col-span-4">
              <div className="border-b border-slate-800 pb-3">
                <h2 className="text-sm font-bold text-white tracking-wide">Selected Corridor Details</h2>
              </div>

              <div className="mt-4 space-y-3">
                <div>
                  <label className="text-[11px] font-semibold text-slate-400">Switch Corridor</label>
                  <select
                    className="mt-1 w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-xs text-white outline-none focus:border-cyan-500"
                    value={selectedSensor?.id}
                    onChange={(event) => setSelected(event.target.value)}
                  >
                    {sensors.map((sensor) => (
                      <option key={sensor.id} value={sensor.id}>
                        {sensor.road_name}
                      </option>
                    ))}
                  </select>
                </div>

                {selectedSensor && (
                  <div className="space-y-2.5 mt-3">
                    <div className="text-base font-bold text-white">{selectedSensor.road_name}</div>
                    {selectedReading ? (
                      <>
                        <div className="grid grid-cols-2 gap-2 text-xs">
                          <div className="rounded-xl bg-slate-900/60 p-2.5 border border-slate-800">
                            <span className="text-slate-400">Observed Speed</span>
                            <div className="mt-1 font-mono text-base font-bold text-cyan-400">
                              {num(selectedReading.current_speed_kph, 1)} km/h
                            </div>
                          </div>
                          <div className="rounded-xl bg-slate-900/60 p-2.5 border border-slate-800">
                            <span className="text-slate-400">Free-Flow Speed</span>
                            <div className="mt-1 font-mono text-base font-bold text-slate-300">
                              {num(selectedReading.free_flow_speed_kph, 1)} km/h
                            </div>
                          </div>
                          <div className="rounded-xl bg-slate-900/60 p-2.5 border border-slate-800">
                            <span className="text-slate-400">Travel Time</span>
                            <div className="mt-1 font-mono text-base font-bold text-amber-400">
                              {num(selectedReading.current_travel_time_s, 0)}s
                            </div>
                          </div>
                          <div className="rounded-xl bg-slate-900/60 p-2.5 border border-slate-800">
                            <span className="text-slate-400">API Confidence</span>
                            <div className="mt-1 font-mono text-base font-bold text-emerald-400">
                              {num(selectedReading.confidence * 100, 0)}%
                            </div>
                          </div>
                        </div>

                        {selectedReading.road_closure && (
                          <div className="rounded-xl bg-rose-500/20 border border-rose-500/30 p-2 text-rose-300 font-semibold text-center">
                            Road Closure Alert
                          </div>
                        )}
                        <p className="text-[11px] text-slate-500">
                          Observed at {localTime(selectedReading.observed_at)}
                        </p>
                      </>
                    ) : (
                      <div className="rounded-xl border border-dashed border-slate-800 p-4 text-center text-slate-400">
                        No reading captured for this corridor yet.
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Speed History Trend Line Chart */}
          <div className="rounded-2xl border border-slate-800/80 bg-[#0c1322] p-5 shadow-2xl">
            <div className="border-b border-slate-800 pb-3">
              <h2 className="text-sm font-bold text-white tracking-wide">Observed Speed History Trends</h2>
              <p className="mt-0.5 text-xs text-slate-400">Velocity traces across monitored corridors over time</p>
            </div>

            <div className="mt-4 h-80 w-full">
              {history.loading && !history.data ? (
                <Loading />
              ) : trend.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={trend} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#1e293b" />
                    <XAxis
                      dataKey="observed_at"
                      stroke="#64748b"
                      tick={{ fill: "#94a3b8", fontSize: 10 }}
                      tickLine={false}
                      tickFormatter={(value: string) =>
                        new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                      }
                    />
                    <YAxis unit=" km/h" stroke="#64748b" tick={{ fill: "#94a3b8", fontSize: 10 }} tickLine={false} />
                    <ChartTooltip
                      labelFormatter={(value) => localTime(String(value))}
                      contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155", borderRadius: "0.75rem", fontSize: "12px" }}
                    />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    {sensors.map((sensor, index) => (
                      <Line
                        key={sensor.id}
                        type="monotone"
                        dataKey={sensor.id}
                        name={sensor.road_name}
                        stroke={COLORS[index % COLORS.length]}
                        strokeWidth={2}
                        dot={false}
                        connectNulls
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full items-center justify-center text-xs text-slate-500">
                  Readings will appear after the first successful collection poll.
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
