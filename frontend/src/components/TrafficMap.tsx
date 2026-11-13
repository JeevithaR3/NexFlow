import { useEffect } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import { Level, NetworkData } from "../api/client";
import { LEVEL_COLOR } from "./ui";

export interface MapProps {
  network: NetworkData;
  levels: Record<string, Level>;
  selectedEdge?: string | null;
  selectedJunction?: string | null;
  recommended?: Record<string, string>; // junction id -> short label
  routes?: { id: string; shape: [number, number][][]; color: string; dash?: string }[];
  showBasemap?: boolean;
  onEdge?: (id: string) => void;
  onJunction?: (id: string) => void;
  height?: number | string;
  dark?: boolean;
}

function MapResizer() {
  const map = useMap();
  useEffect(() => {
    const timer = setTimeout(() => {
      map.invalidateSize();
    }, 200);
    return () => clearTimeout(timer);
  }, [map]);
  return null;
}

export default function TrafficMap({
  network,
  levels,
  selectedEdge,
  selectedJunction,
  recommended = {},
  routes = [],
  showBasemap = true,
  onEdge,
  onJunction,
  height = 560,
  dark = false,
}: MapProps) {
  const c: [number, number] = [
    network.origin.lat + 400 / 111320,
    network.origin.lon + 400 / (111320 * Math.cos((network.origin.lat * Math.PI) / 180)),
  ];

  const tileUrl = dark
    ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
    : "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

  const attribution = dark
    ? '&copy; <a href="https://carto.com/">CARTO</a>'
    : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

  return (
    <div
      data-testid="traffic-map"
      style={{ height }}
      className={`overflow-hidden rounded-xl border transition-all ${
        dark ? "border-slate-800 bg-[#070b16]" : "border-slate-200 bg-white"
      }`}
    >
      <MapContainer center={c} zoom={16} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
        <MapResizer />
        {showBasemap && <TileLayer attribution={attribution} url={tileUrl} />}
        {network.edges.map((e) => {
          const lv = levels[e.id] ?? "unknown";
          const sel = selectedEdge === e.id;
          return (
            <Polyline
              key={e.id}
              positions={e.shape}
              pathOptions={{
                color: LEVEL_COLOR[lv],
                weight: sel ? 8 : 4.5,
                opacity: 0.95,
              }}
              eventHandlers={{ click: () => onEdge?.(e.id) }}
            >
              <Tooltip sticky>
                {e.id} &bull; {lv}
              </Tooltip>
            </Polyline>
          );
        })}
        {routes.map((r) =>
          r.shape.map((seg, i) => (
            <Polyline
              key={`${r.id}-${i}`}
              positions={seg}
              pathOptions={{ color: r.color, weight: 4, dashArray: r.dash ?? "8 6", opacity: 1 }}
            />
          ))
        )}
        {network.junctions
          .filter((j) => j.has_tls)
          .map((j) => {
            const rec = recommended[j.id];
            return (
              <CircleMarker
                key={j.id}
                center={[j.lat, j.lon]}
                radius={rec ? 11 : selectedJunction === j.id ? 9 : 7}
                pathOptions={{
                  color: rec ? "#00f0ff" : dark ? "#38bdf8" : "#0f172a",
                  fillColor: rec ? "#5eead4" : dark ? "#ffffff" : "#fff",
                  fillOpacity: 1,
                  weight: 3,
                }}
                eventHandlers={{ click: () => onJunction?.(j.id) }}
              >
                <Tooltip direction="top">
                  {j.id}
                  {rec ? ` &bull; recommended: ${rec}` : ""}
                </Tooltip>
              </CircleMarker>
            );
          })}
      </MapContainer>
    </div>
  );
}
