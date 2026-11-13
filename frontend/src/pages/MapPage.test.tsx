import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import MapPage from "./MapPage";

afterEach(() => vi.restoreAllMocks());

describe("Traffic map data sources", () => {
  it("shows TomTom readings by default and lets the user switch to SUMO", async () => {
    vi.spyOn(api, "network").mockResolvedValue({
      network_id: "synthetic",
      synthetic: true,
      notice: "Synthetic SUMO network.",
      origin: { lat: 12.97, lon: 77.59 },
      congestion: { low_max: 0.3, high_min: 0.6, colors: { low: "#0f0", moderate: "#ff0", high: "#f00", unknown: "#999" } },
      edges: [],
      junctions: [],
      signal_limits: { min_green_s: 10, max_green_s: 60, max_cycle_s: 120 },
    });
    vi.spyOn(api, "trafficPredictions").mockResolvedValue({ available: false });
    vi.spyOn(api, "trafficCurrent").mockResolvedValue({ available: false });
    vi.spyOn(api, "bengaluruPredictions").mockResolvedValue({
      available: true,
      source: "tomtom_history_trend",
      method: "Linear trend",
      horizon_s: 900,
      minimum_samples: 3,
      minimum_history_span_s: 600,
      sensors: [{
        sensor_id: "mg-road",
        road_name: "Mahatma Gandhi Road",
        available: true,
        reason: null,
        sample_count: 6,
        history_span_s: 1500,
        geometry: [[12.9757, 77.6055], [12.9758, 77.6056]],
        predicted_speed_kph: 22,
        predicted_travel_time_s: 49,
        congestion_level: "moderate",
      }],
    });
    vi.spyOn(api, "bengaluruTraffic").mockResolvedValue({
      provider: "TomTom Traffic Flow",
      configured: true,
      polling_enabled: true,
      poll_interval_s: 300,
      status: "ok",
      last_poll_at: "2026-11-13T06:00:00+00:00",
      last_error: null,
      observation_count: 1,
      first_observation_at: "2026-11-13T06:00:00+00:00",
      sensors: [{
        id: "mg-road",
        road_name: "Mahatma Gandhi Road",
        latitude: 12.9757,
        longitude: 77.6055,
        latest: {
          id: 1,
          sensor_id: "mg-road",
          road_name: "Mahatma Gandhi Road",
          observed_at: "2026-11-13T06:00:00+00:00",
          latitude: 12.9757,
          longitude: 77.6055,
          current_speed_kph: 18,
          free_flow_speed_kph: 40,
          current_travel_time_s: 60,
          free_flow_travel_time_s: 30,
          confidence: 0.9,
          road_closure: false,
          geometry: [[12.9757, 77.6055], [12.9758, 77.6056]],
        },
      }, {
        id: "silk-board",
        road_name: "Silk Board Junction",
        latitude: 12.9177,
        longitude: 77.6233,
        latest: null,
      }],
    });
    const liveRoutes = vi.spyOn(api, "bengaluruRoutes").mockResolvedValue({
      provider: "TomTom Routing API",
      source: "live_traffic_routing",
      traffic_aware: true,
      forecast_source: "tomtom_history_trend",
      origin: { id: "mg-road", road_name: "Mahatma Gandhi Road", latitude: 12.9757, longitude: 77.6055 },
      destination: { id: "silk-board", road_name: "Silk Board Junction", latitude: 12.9177, longitude: 77.6233 },
      requested_at: "2026-11-13T06:00:00+00:00",
      routes: [{
        rank: 1,
        label: "Fastest with current traffic",
        distance_m: 7200,
        travel_time_s: 1100,
        traffic_delay_s: 240,
        geometry: [[12.9757, 77.6055], [12.9177, 77.6233]],
        predicted_travel_time_s: 1080,
        forecast_adjustment_s: -20,
        forecast_sensor_ids: ["mg-road"],
        forecast_sensor_count: 1,
        recommendation_rank: 1,
        recommended: true,
      }],
      notice: "TomTom current-traffic route estimate.",
    });

    render(
      <MemoryRouter initialEntries={["/map"]}>
        <Routes><Route path="/map" element={<MapPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/TomTom trend uses recent readings/)).toBeTruthy();
    expect(screen.getByText("18.0 km/h")).toBeTruthy();
    expect(screen.getByRole("button", { name: "TomTom trend" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText(/22.0 km\/h · moderate/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Current TomTom" }));
    expect(screen.getByRole("button", { name: "Current TomTom" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Find live routes" }));
    expect(await screen.findByText("Recommended · Fastest with current traffic")).toBeTruthy();
    expect(screen.getByText(/7.2 km · 18 min predicted/)).toBeTruthy();
    vi.spyOn(api, "runBengaluruSumo").mockRejectedValue(
      new ApiError("The Bengaluru OSM SUMO network is not installed.", "sumo_config_invalid"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Run TomTom-calibrated simulation" }));
    expect(await screen.findByText("The Bengaluru OSM SUMO network is not installed.")).toBeTruthy();
    vi.spyOn(api, "runBengaluruSumo").mockResolvedValue({ run_id: "run-12345678" });
    vi.spyOn(api, "run").mockResolvedValue({
      id: "run-12345678",
      kind: "bengaluru_sumo",
      status: "succeeded",
      progress: 1,
      message: "done",
      result: null,
      error: null,
    });
    fireEvent.click(screen.getByRole("button", { name: "Run TomTom-calibrated simulation" }));
    fireEvent.click(await screen.findByRole("button", { name: "GNN forecast" }));
    fireEvent.click(screen.getByRole("button", { name: "Rank routes with GNN forecast" }));
    expect(await screen.findByText("Recommended · Fastest with current traffic")).toBeTruthy();
    expect(liveRoutes).toHaveBeenLastCalledWith("mg-road", "silk-board", "run-12345678");
    fireEvent.click(screen.getByRole("button", { name: "SUMO simulation" }));
    expect(await screen.findByText(/Road colours, forecasts and routes below use SUMO data/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Predicted" })).toBeTruthy();
  });
});
