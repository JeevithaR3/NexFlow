import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TrafficMap from "./TrafficMap";
import { NetworkData } from "../api/client";

const net: NetworkData = {
  network_id: "t", synthetic: true, notice: "synthetic", origin: { lat: 12.97, lon: 77.59 },
  congestion: { low_max: 0.3, high_min: 0.6, colors: { low: "#16a34a", moderate: "#eab308", high: "#dc2626", unknown: "#9ca3af" } },
  edges: [
    { id: "A", from: "n1", to: "n2", length_m: 100, speed_ms: 13.9, lanes: 1, shape: [[12.97, 77.59], [12.971, 77.591]] },
    { id: "B", from: "n2", to: "n1", length_m: 100, speed_ms: 13.9, lanes: 1, shape: [[12.971, 77.5911], [12.9701, 77.5901]] },
  ],
  junctions: [{ id: "n1", lat: 12.97, lon: 77.59, type: "traffic_light", has_tls: true, neighbors: [], tls: null }],
  signal_limits: { min_green_s: 10, max_green_s: 60, max_cycle_s: 120 },
};

describe("TrafficMap", () => {
  it("renders the container and one path per road plus junction markers", () => {
    const { getByTestId, container } = render(<TrafficMap network={net} levels={{ A: "high", B: "low" }} showBasemap={false} />);
    expect(getByTestId("traffic-map")).toBeTruthy();
    const paths = Array.from(container.querySelectorAll("path.leaflet-interactive"));
    expect(paths.length).toBe(3); // 2 roads + 1 junction
    const strokes = paths.map((p) => p.getAttribute("stroke"));
    expect(strokes).toContain("#dc2626");
    expect(strokes).toContain("#16a34a");
  });
  it("draws unknown roads gray when no data exists", () => {
    const { container } = render(<TrafficMap network={net} levels={{}} showBasemap={false} />);
    const strokes = Array.from(container.querySelectorAll("path.leaflet-interactive")).map((p) => p.getAttribute("stroke"));
    expect(strokes.filter((s) => s === "#9ca3af").length).toBe(2);
  });
});
