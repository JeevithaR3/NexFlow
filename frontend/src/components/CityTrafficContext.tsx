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
  const readings = status?.sensors.flatMap((sensor) => (sensor.latest ? [sensor.latest] : [])) ?? [];
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
    <section
      aria-label="Shared Bengaluru traffic context"
      className="rounded-2xl border border-blue-500/20 bg-gradient-to-r from-[#0c1427] via-[#091122] to-[#080d1a] px-4 py-2.5 text-xs shadow-lg backdrop-blur-md"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="flex items-center gap-1.5 font-semibold text-slate-200">
            <span className="flex h-2 w-2 rounded-full bg-cyan-400 animate-pulse" />
            <span>Bengaluru Context:</span>
          </div>
          <Badge tone={tone}>{label}</Badge>
          <span className="text-slate-400">
            {readings.length
              ? `Latest update: ${formatTime(status?.last_poll_at ?? null)}`
              : "Live readings & SUMO simulation run independently"}
          </span>
          <span className="hidden text-slate-500 xl:inline">&bull; Simulation &amp; memory run on SUMO digital twin</span>
        </div>
        <div className="flex items-center gap-3">
          <Link
            className="flex items-center gap-1 font-semibold text-cyan-400 transition hover:text-cyan-300 hover:underline"
            to="/map?source=bengaluru"
          >
            <span>Live Map</span>
            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
          <Link
            className="flex items-center gap-1 font-semibold text-cyan-400 transition hover:text-cyan-300 hover:underline"
            to="/bengaluru"
          >
            <span>Corridor History</span>
            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        </div>
      </div>
      {traffic.error && (
        <div role="status" className="mt-1 text-[11px] text-amber-400">
          Could not refresh live data telemetry.
        </div>
      )}
    </section>
  );
}
