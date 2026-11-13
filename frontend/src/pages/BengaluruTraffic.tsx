import { Fragment, useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from "react-leaflet";
import { Link } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from "recharts";
import { ApiError, LiveTrafficReading, api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Stat, num } from "../components/ui";

const COLORS = ["#0f766e", "#2563eb", "#9333ea", "#d97706", "#dc2626"];

function roadColor(reading: LiveTrafficReading | null) {
  if (!reading) return "#94a3b8";
  const ratio = reading.current_speed_kph / reading.free_flow_speed_kph;
  return ratio >= 0.8 ? "#16a34a" : ratio >= 0.5 ? "#eab308" : "#dc2626";
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
    <>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Bengaluru traffic history</h1>
          <p className="text-sm text-slate-600">History for the same live TomTom dataset shown on the Traffic map.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            to="/map?source=bengaluru">Open live map</Link>
          <Button onClick={refresh} disabled={polling || !status.data?.configured}>
            {polling ? "Polling…" : "Poll now"}
          </Button>
        </div>
      </header>
      <div role="note" className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs leading-relaxed text-blue-900">
        Live TomTom observations are collected independently of the synthetic SUMO/GNN demo. This page shows the monitored road points only; it is not a citywide feed, and no live reading controls a signal.
      </div>
      <ErrorBox error={status.error} />
      <ErrorBox error={history.error} />
      <ErrorBox error={pollError} />
      {status.loading && !status.data ? <Loading /> : status.data && (
        <>
          {!status.data.configured && (
            <div role="note" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              TomTom is not configured. Set <code>NEXFLOW_TOMTOM_API_KEY</code> in the backend environment and restart it. The API key stays on the server and is never sent to this page.
            </div>
          )}
          {status.data.last_error && <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{status.data.last_error}</div>}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Provider" value={<Badge tone={status.data.configured ? "green" : "amber"}>{status.data.provider}</Badge>} hint={status.data.polling_enabled ? `Auto-poll every ${status.data.poll_interval_s / 60} min` : "Automatic polling is off"} />
            <Stat label="Monitored roads" value={sensors.length} />
            <Stat label="Stored readings" value={status.data.observation_count} hint={status.data.first_observation_at ? `Since ${localTime(status.data.first_observation_at)}` : "No readings stored"} />
            <Stat label="Last collection" value={status.data.last_poll_at ? localTime(status.data.last_poll_at) : "—"} />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="Same Bengaluru live map layer" className="lg:col-span-2">
              <MapContainer center={[12.95, 77.65]} zoom={11.5} scrollWheelZoom style={{ height: 500, width: "100%" }}>
                <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
                {sensors.map((sensor) => {
                  const reading = sensor.latest;
                  const color = roadColor(reading);
                  return (
                    <Fragment key={sensor.id}>
                      {reading?.geometry && <Polyline positions={reading.geometry} pathOptions={{ color, weight: 7, opacity: 0.9 }} eventHandlers={{ click: () => setSelected(sensor.id) }}>
                        <Tooltip sticky>{sensor.road_name} · {reading.current_speed_kph.toFixed(1)} km/h</Tooltip>
                      </Polyline>}
                      <CircleMarker center={[sensor.latitude, sensor.longitude]} radius={selectedSensor?.id === sensor.id ? 10 : 7}
                        pathOptions={{ color, fillColor: color, fillOpacity: 0.9 }}
                        eventHandlers={{ click: () => setSelected(sensor.id) }}>
                        <Tooltip direction="top">{sensor.road_name}{reading ? ` · ${reading.current_speed_kph.toFixed(1)} km/h` : " · waiting for data"}</Tooltip>
                      </CircleMarker>
                    </Fragment>
                  );
                })}
              </MapContainer>
              <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-600">
                <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-green-600" />Clearer (≥80% of free-flow)</span>
                <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-yellow-500" />Slower (50–80%)</span>
                <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-red-600" />Heavily slowed (&lt;50%)</span>
              </div>
            </Card>
            <Card title="Selected corridor">
              {selectedSensor ? (
                <div className="space-y-3">
                  <label className="block text-xs text-slate-600">Road
                    <select className="mt-1 w-full rounded border border-slate-300 p-2 text-sm" value={selectedSensor.id} onChange={(event) => setSelected(event.target.value)}>
                      {sensors.map((sensor) => <option key={sensor.id} value={sensor.id}>{sensor.road_name}</option>)}
                    </select>
                  </label>
                  {selectedReading ? (
                    <>
                      <div className="text-lg font-semibold">{selectedSensor.road_name}</div>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div className="rounded bg-slate-50 p-2"><div className="text-xs text-slate-500">Current speed</div><strong>{num(selectedReading.current_speed_kph, 1)} km/h</strong></div>
                        <div className="rounded bg-slate-50 p-2"><div className="text-xs text-slate-500">Free-flow speed</div><strong>{num(selectedReading.free_flow_speed_kph, 1)} km/h</strong></div>
                        <div className="rounded bg-slate-50 p-2"><div className="text-xs text-slate-500">Travel time</div><strong>{num(selectedReading.current_travel_time_s, 0)} s</strong></div>
                        <div className="rounded bg-slate-50 p-2"><div className="text-xs text-slate-500">Confidence</div><strong>{num(selectedReading.confidence * 100, 0)}%</strong></div>
                      </div>
                      {selectedReading.road_closure && <Badge tone="red">Road closure reported</Badge>}
                      <p className="text-xs text-slate-500">Observed {localTime(selectedReading.observed_at)}</p>
                    </>
                  ) : <Empty title="No reading for this corridor yet">Wait for the next poll or request one now.</Empty>}
                </div>
              ) : <Empty title="Waiting for live readings">Configure the TomTom key, then poll the selected corridors.</Empty>}
            </Card>
          </div>
          <Card title="Observed speed history">
            {history.loading && !history.data ? <Loading /> : trend.length ? (
              <div style={{ height: 320 }}>
                <ResponsiveContainer>
                  <LineChart data={trend}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="observed_at" tickFormatter={(value: string) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} />
                    <YAxis unit=" km/h" />
                    <ChartTooltip labelFormatter={(value) => localTime(String(value))} />
                    <Legend />
                    {sensors.map((sensor, index) => <Line key={sensor.id} type="monotone" dataKey={sensor.id} name={sensor.road_name} stroke={COLORS[index % COLORS.length]} dot={false} connectNulls />)}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : <Empty title="No traffic history yet">Readings appear after the first successful collection.</Empty>}
          </Card>
        </>
      )}
    </>
  );
}
