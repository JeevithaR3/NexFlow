import { NavLink, Route, Routes } from "react-router-dom";
import Overview from "./pages/Overview";
import MapPage from "./pages/MapPage";
import BengaluruTraffic from "./pages/BengaluruTraffic";
import Scenario from "./pages/Scenario";
import Memory from "./pages/Memory";
import Models from "./pages/Models";
import CityTrafficContext from "./components/CityTrafficContext";

const NAV = [
  {
    to: "/",
    label: "Overview",
    end: true,
    icon: (
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
      </svg>
    ),
  },
  {
    to: "/map",
    label: "Traffic Map",
    end: false,
    icon: (
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
      </svg>
    ),
  },
  {
    to: "/bengaluru",
    label: "Traffic History",
    end: false,
    icon: (
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    to: "/scenario",
    label: "Scenario Simulation",
    end: false,
    icon: (
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
      </svg>
    ),
  },
  {
    to: "/memory",
    label: "Experience Memory",
    end: false,
    icon: (
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
      </svg>
    ),
  },
  {
    to: "/models",
    label: "Model Evaluation",
    end: false,
    icon: (
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
      </svg>
    ),
  },
];

export default function App() {
  return (
    <div className="min-h-screen bg-[#070b16] font-sans text-slate-100 md:flex">
      {/* Sidebar Navigation */}
      <aside className="flex flex-col justify-between border-b border-slate-800/80 bg-[#080d1a] p-4 text-slate-100 md:min-h-screen md:w-64 md:border-b-0 md:border-r">
        <div>
          {/* NexFlow Brand & Logo */}
          <div className="mb-7 flex items-center gap-3 px-1 pt-2">
            {/* Stylized Neon Ribbon "N" Logo */}
            <div className="relative flex h-10 w-10 shrink-0 items-center justify-center">
              <svg className="h-10 w-10" viewBox="0 0 40 40" fill="none">
                <defs>
                  <linearGradient id="logo-neon-blue" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#00f0ff" />
                    <stop offset="100%" stopColor="#0066ff" />
                  </linearGradient>
                  <linearGradient id="logo-neon-purple" x1="0%" y1="100%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#8b5cf6" />
                    <stop offset="100%" stopColor="#ec4899" />
                  </linearGradient>
                  <filter id="neon-glow" x="-20%" y="-20%" width="140%" height="140%">
                    <feGaussianBlur stdDeviation="2" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>
                </defs>
                {/* Background soft circle */}
                <circle cx="20" cy="20" r="18" fill="#0b1730" stroke="#1d4ed8" strokeWidth="1" />
                {/* Stylized ribbon N */}
                <path
                  d="M12 28 V12 L20 22 V28 Z"
                  fill="url(#logo-neon-blue)"
                  filter="url(#neon-glow)"
                />
                <path
                  d="M20 12 L28 22 V12 H26 V20 L20 12 Z"
                  fill="url(#logo-neon-purple)"
                />
                <circle cx="20" cy="20" r="2.5" fill="#ffffff" />
              </svg>
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="text-xl font-black tracking-tight text-white">NexFlow</span>
                <span className="rounded-full bg-cyan-500/20 px-2 py-0.5 text-[10px] font-bold text-cyan-400 border border-cyan-500/30">
                  AI 2.0
                </span>
              </div>
              <div className="text-[11px] font-medium tracking-wide text-slate-400">
                Traffic Intelligence Center
              </div>
            </div>
          </div>

          {/* Navigation Links */}
          <nav aria-label="Main" className="flex gap-1.5 overflow-x-auto pb-2 md:flex-col md:pb-0">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `group flex items-center gap-3.5 whitespace-nowrap rounded-xl px-3.5 py-2.5 text-sm font-medium transition-all duration-200 ${
                    isActive
                      ? "bg-gradient-to-r from-blue-600 to-blue-500 text-white shadow-lg shadow-blue-500/25 border border-blue-400/30"
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent"
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <span className={isActive ? "text-white" : "text-slate-400 group-hover:text-slate-300"}>
                      {n.icon}
                    </span>
                    <span className="tracking-wide">{n.label}</span>
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </div>

        {/* Sidebar Bottom: Smart City Futuristic Art & Slogan */}
        <div className="mt-8 hidden flex-col md:flex">
          {/* Futuristic skyline & highway light trails graphic */}
          <div className="relative h-32 w-full overflow-hidden rounded-xl border border-blue-500/20 bg-gradient-to-t from-[#060a14] via-[#091224] to-[#0c1830] shadow-inner">
            <svg className="absolute inset-0 h-full w-full" viewBox="0 0 220 120" fill="none">
              <defs>
                <linearGradient id="skyline-glow" x1="110" y1="0" x2="110" y2="120" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#0284c7" stopOpacity="0.3" />
                  <stop offset="1" stopColor="#070b16" stopOpacity="0.9" />
                </linearGradient>
                <linearGradient id="neon-stream-1" x1="0" y1="120" x2="220" y2="60" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#00f0ff" stopOpacity="0.8" />
                  <stop offset="1" stopColor="#3b82f6" stopOpacity="0.1" />
                </linearGradient>
                <linearGradient id="neon-stream-2" x1="0" y1="110" x2="220" y2="70" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#ec4899" stopOpacity="0.8" />
                  <stop offset="1" stopColor="#8b5cf6" stopOpacity="0.1" />
                </linearGradient>
              </defs>

              {/* Distant city towers */}
              <rect x="25" y="30" width="16" height="70" rx="1" fill="#0f2244" opacity="0.6" />
              <rect x="45" y="15" width="22" height="85" rx="1" fill="#132c57" opacity="0.8" />
              <rect x="71" y="40" width="18" height="60" rx="1" fill="#0f2244" opacity="0.6" />
              <rect x="93" y="10" width="28" height="90" rx="1" fill="#1e3a6d" opacity="0.9" />
              <rect x="125" y="25" width="20" height="75" rx="1" fill="#132c57" opacity="0.8" />
              <rect x="149" y="35" width="16" height="65" rx="1" fill="#0f2244" opacity="0.6" />
              <rect x="169" y="20" width="24" height="80" rx="1" fill="#132c57" opacity="0.7" />

              {/* Tower lights dots */}
              <circle cx="56" cy="18" r="1" fill="#38bdf8" />
              <circle cx="107" cy="13" r="1.5" fill="#00f0ff" />
              <circle cx="135" cy="28" r="1" fill="#38bdf8" />

              {/* Curved cyber highway light trails */}
              <path d="M-10 120 C 40 100, 90 75, 230 65" stroke="url(#neon-stream-1)" strokeWidth="3.5" fill="none" />
              <path d="M-10 112 C 50 95, 100 80, 230 72" stroke="url(#neon-stream-2)" strokeWidth="2.5" fill="none" />
              <path d="M-10 125 C 30 105, 80 82, 230 70" stroke="#00f0ff" strokeWidth="1" strokeDasharray="3 4" fill="none" opacity="0.9" />
            </svg>
            <div className="absolute inset-0 bg-gradient-to-t from-[#080d1a] via-transparent to-transparent" />
          </div>

          {/* Caption exactly matching design reference */}
          <div className="mt-3 px-1">
            <div className="text-xs font-semibold leading-snug text-slate-300">
              Smart City
            </div>
            <div className="text-xs font-medium leading-snug text-slate-400">
              Traffic Management
            </div>
            <div className="text-[11px] font-normal leading-snug text-cyan-400">
              with AI &amp; Digital Twin
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="mx-auto w-full max-w-[1500px] flex-1 space-y-5 p-4 md:p-6 lg:p-7">
        <CityTrafficContext />
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/map" element={<MapPage />} />
          <Route path="/bengaluru" element={<BengaluruTraffic />} />
          <Route path="/scenario" element={<Scenario />} />
          <Route path="/memory" element={<Memory />} />
          <Route path="/models" element={<Models />} />
        </Routes>
      </main>
    </div>
  );
}
