import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from "react-leaflet";
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
}

export default function TrafficMap({ network, levels, selectedEdge, selectedJunction, recommended = {}, routes = [], showBasemap = true, onEdge, onJunction, height = 560 }: MapProps) {
  const c: [number, number] = [network.origin.lat + 400 / 111320, network.origin.lon + 400 / (111320 * Math.cos((network.origin.lat * Math.PI) / 180))];
  return (
    <div data-testid="traffic-map" style={{ height }} className="overflow-hidden rounded-xl border border-slate-200">
      <MapContainer center={c} zoom={16} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
        {showBasemap && <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />}
        {network.edges.map((e) => {
          const lv = levels[e.id] ?? "unknown";
          const sel = selectedEdge === e.id;
          return (
            <Polyline key={e.id} positions={e.shape} pathOptions={{ color: LEVEL_COLOR[lv], weight: sel ? 9 : 5, opacity: 0.95 }}
              eventHandlers={{ click: () => onEdge?.(e.id) }}>
              <Tooltip sticky>{e.id} · {lv}</Tooltip>
            </Polyline>
          );
        })}
        {routes.map((r) => r.shape.map((seg, i) => (
          <Polyline key={`${r.id}-${i}`} positions={seg} pathOptions={{ color: r.color, weight: 3, dashArray: r.dash ?? "8 6", opacity: 1 }} />
        )))}
        {network.junctions.filter((j) => j.has_tls).map((j) => {
          const rec = recommended[j.id];
          return (
            <CircleMarker key={j.id} center={[j.lat, j.lon]} radius={rec ? 11 : selectedJunction === j.id ? 9 : 7}
              pathOptions={{ color: rec ? "#0f766e" : "#0f172a", fillColor: rec ? "#5eead4" : "#fff", fillOpacity: 1, weight: 3 }}
              eventHandlers={{ click: () => onJunction?.(j.id) }}>
              <Tooltip direction="top">{j.id}{rec ? ` · recommended: ${rec}` : ""}</Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}
