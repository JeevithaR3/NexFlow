import { NavLink, Route, Routes } from "react-router-dom";
import Overview from "./pages/Overview";
import MapPage from "./pages/MapPage";
import Scenario from "./pages/Scenario";
import Memory from "./pages/Memory";
import Models from "./pages/Models";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/map", label: "Traffic map" },
  { to: "/scenario", label: "Scenario simulation" },
  { to: "/memory", label: "Experience memory" },
  { to: "/models", label: "Model evaluation" },
];

export default function App() {
  return (
    <div className="min-h-screen md:flex">
      <aside className="border-b border-slate-200 bg-slate-900 p-4 text-slate-100 md:min-h-screen md:w-60 md:border-b-0">
        <div className="mb-1 text-lg font-semibold tracking-tight">NexFlow</div>
        <div className="mb-4 text-xs text-slate-400">Traffic prediction &amp; digital twin</div>
        <nav aria-label="Main" className="flex gap-1 overflow-x-auto md:flex-col">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}
              className={({ isActive }) => `whitespace-nowrap rounded-md px-3 py-2 text-sm ${isActive ? "bg-teal-700 text-white" : "text-slate-300 hover:bg-slate-800"}`}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <p className="mt-6 hidden text-xs leading-relaxed text-slate-400 md:block">
          All data comes from a synthetic SUMO network. Recommendations are simulated only and never control real signals.
        </p>
      </aside>
      <main className="mx-auto w-full max-w-7xl flex-1 space-y-4 p-4 md:p-6">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/map" element={<MapPage />} />
          <Route path="/scenario" element={<Scenario />} />
          <Route path="/memory" element={<Memory />} />
          <Route path="/models" element={<Models />} />
        </Routes>
      </main>
    </div>
  );
}
