import { useEffect } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { Badge } from "./ui";

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleTimeString() : "No readings yet";
}

export default function CityTrafficContext() {
  const traffic = useAsync(() => api.bengaluruTraffic());

  useEffect(() => {
    const timer = window.setInterval(traffic.reload, 60_000);
    return () => window.clearInterval(timer);
  }, [traffic.reload]);

  const status = traffic.data;
  const readings = status?.sensors.flatMap((sensor) => sensor.latest ? [sensor.latest] : []) ?? [];
  const tone = !status?.configured ? "amber" : readings.length ? "green" : "slate";
  const label = traffic.loading && !status
    ? "Loading traffic status"
    : traffic.error && !status
      ? "Traffic status unavailable"
      : !status?.configured
        ? "TomTom not configured"
        : readings.length
          ? `${readings.length}/${status.sensors.length} roads reporting`
          : "Waiting for readings";

  return (
    <section aria-label="Shared Bengaluru traffic context" className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <strong className="text-slate-800">Bengaluru data context</strong>
          <Badge tone={tone}>{label}</Badge>
          <span className="text-slate-600">
            {readings.length
              ? `Latest collection ${formatTime(status?.last_poll_at ?? null)}`
              : "Live readings and the SUMO simulation are shown separately"}
          </span>
          <span className="text-slate-500">Simulation and memory results remain SUMO-based.</span>
        </div>
        <div className="flex gap-3">
          <Link className="font-medium text-teal-800 underline" to="/map?source=bengaluru">Open live map</Link>
          <Link className="font-medium text-teal-800 underline" to="/bengaluru">View history</Link>
        </div>
      </div>
      {traffic.error && <div role="status" className="mt-1 text-amber-800">Could not refresh the shared live-data status.</div>}
    </section>
  );
}
