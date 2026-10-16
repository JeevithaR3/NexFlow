import { ReactNode } from "react";
import { ApiError, Level } from "../api/client";

export const LEVEL_COLOR: Record<Level, string> = { low: "#16a34a", moderate: "#eab308", high: "#dc2626", unknown: "#9ca3af" };
export const LEVEL_LABEL: Record<Level, string> = { low: "Low", moderate: "Moderate", high: "High", unknown: "Unknown" };

export function Card({ title, children, right, className = "" }: { title?: string; children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
      {(title || right) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold tracking-wide text-slate-700">{title}</h2>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 p-3">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "green" | "amber" | "red" | "teal" | "blue" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700", green: "bg-green-100 text-green-800", amber: "bg-amber-100 text-amber-800",
    red: "bg-red-100 text-red-800", teal: "bg-teal-100 text-teal-800", blue: "bg-blue-100 text-blue-800",
  };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>;
}

export function LevelLegend() {
  return (
    <ul className="flex flex-wrap gap-3 text-xs text-slate-600" aria-label="Congestion legend">
      {(["low", "moderate", "high", "unknown"] as Level[]).map((l) => (
        <li key={l} className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-5 rounded-sm" style={{ background: LEVEL_COLOR[l] }} />
          {LEVEL_LABEL[l]} {l === "low" ? "(CI < 0.30)" : l === "moderate" ? "(0.30–0.60)" : l === "high" ? "(≥ 0.60)" : "(no data)"}
        </li>
      ))}
    </ul>
  );
}

export function Button({ children, onClick, disabled, variant = "primary", type = "button" }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; variant?: "primary" | "ghost"; type?: "button" | "submit";
}) {
  const cls = variant === "primary" ? "bg-teal-700 text-white hover:bg-teal-800" : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50";
  return (
    <button type={type} onClick={onClick} disabled={disabled}
      className={`rounded-lg px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${cls}`}>
      {children}
    </button>
  );
}

export function ErrorBox({ error }: { error: ApiError | null }) {
  if (!error) return null;
  return (
    <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <div className="font-medium">{error.message}</div>
      {error.hint && <div className="mt-1 text-red-700">{error.hint}</div>}
      {error.details?.map((d, i) => <div key={i} className="mt-1 text-xs">{d.field}: {d.message}</div>)}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div role="status" className="animate-pulse text-sm text-slate-500">{label}</div>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center">
      <div className="font-medium text-slate-700">{title}</div>
      {children && <div className="mt-1 text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  return (
    <div>
      <div className="h-2 w-full overflow-hidden rounded bg-slate-200" role="progressbar" aria-valuenow={Math.round(value * 100)}>
        <div className="h-full bg-teal-600 transition-all" style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      {label && <div className="mt-1 text-xs text-slate-500">{label}</div>}
    </div>
  );
}

export const pct = (x: number | null | undefined, d = 1) => (x == null ? "–" : `${(x * 100).toFixed(d)}%`);
export const num = (x: number | null | undefined, d = 2) => (x == null ? "–" : x.toFixed(d));

export function SourceBadge({ source }: { source?: string }) {
  if (source === "memory_verified") return <Badge tone="teal">Retrieved from memory, verified in SUMO</Badge>;
  if (source === "simulated") return <Badge tone="blue">Simulated in SUMO</Badge>;
  if (source === "dataset_replay") return <Badge tone="amber">Demo data: recorded synthetic replay</Badge>;
  if (source === "sumo_simulation") return <Badge tone="blue">Live SUMO simulation</Badge>;
  if (source === "no_change") return <Badge tone="slate">No beneficial change found</Badge>;
  return <Badge>{source ?? "unknown"}</Badge>;
}
