import axios, { AxiosError } from "axios";

export class ApiError extends Error {
  code: string;
  hint?: string | null;
  status?: number;
  details?: { field: string; message: string }[];
  constructor(message: string, code: string, status?: number, hint?: string | null, details?: ApiError["details"]) {
    super(message);
    this.code = code;
    this.status = status;
    this.hint = hint;
    this.details = details;
  }
}

/** Turns any axios failure into an ApiError with a message that is safe to show users. */
export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  const e = err as AxiosError<{ error?: { code: string; message: string; hint?: string; details?: ApiError["details"] } }>;
  const body = e.response?.data?.error;
  if (body) return new ApiError(body.message, body.code, e.response?.status, body.hint, body.details);
  if (e.response) return new ApiError(`The server answered with status ${e.response.status}.`, "http_error", e.response.status);
  return new ApiError("Cannot reach the NexFlow API. Is the backend running on port 8000?", "network_error");
}

export const http = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? "", timeout: 30000 });
http.interceptors.response.use((r) => r, (err) => Promise.reject(toApiError(err)));

export type Level = "low" | "moderate" | "high" | "unknown";
export interface ScenarioIn { pattern: "balanced" | "ew_heavy" | "ns_heavy"; demand_scale: number; seed: number }
export interface Run<T = any> {
  id: string; kind: string; status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number; message: string; result: T | null; error: { code: string; message: string; hint?: string } | null;
}
export interface NetworkData {
  network_id: string; synthetic: boolean; notice: string; origin: { lat: number; lon: number };
  congestion: { low_max: number; high_min: number; colors: Record<Level, string> };
  edges: { id: string; from: string; to: string; length_m: number; speed_ms: number; lanes: number; shape: [number, number][] }[];
  junctions: { id: string; lat: number; lon: number; type: string; has_tls: boolean; neighbors: string[]; tls: any }[];
  signal_limits: { min_green_s: number; max_green_s: number; max_cycle_s: number };
}

export interface LiveTrafficReading {
  id: number;
  sensor_id: string;
  road_name: string;
  observed_at: string;
  latitude: number;
  longitude: number;
  current_speed_kph: number;
  free_flow_speed_kph: number;
  current_travel_time_s: number;
  free_flow_travel_time_s: number;
  confidence: number;
  road_closure: boolean;
  geometry: [number, number][] | null;
}

export interface LiveTrafficSensor {
  id: string;
  road_name: string;
  latitude: number;
  longitude: number;
  latest: LiveTrafficReading | null;
}

export interface LiveTrafficStatus {
  provider: string;
  configured: boolean;
  polling_enabled: boolean;
  poll_interval_s: number;
  status: string;
  last_poll_at: string | null;
  last_error: string | null;
  observation_count: number;
  first_observation_at: string | null;
  sensors: LiveTrafficSensor[];
}

export interface LiveTrafficPrediction {
  sensor_id: string;
  road_name: string;
  available: boolean;
  reason: string | null;
  sample_count: number;
  history_span_s: number;
  geometry: [number, number][] | null;
  predicted_speed_kph: number | null;
  predicted_travel_time_s: number | null;
  congestion_level: Level | null;
}

export interface LiveTrafficPredictions {
  available: boolean;
  source: "tomtom_history_trend";
  method: string;
  horizon_s: number;
  minimum_samples: number;
  minimum_history_span_s: number;
  sensors: LiveTrafficPrediction[];
}

export interface BengaluruSumoResult {
  source: "bengaluru_osm_sumo_gnn";
  network_id: string;
  map_is_openstreetmap: boolean;
  traffic_is_simulated: boolean;
  tomtom_speed_constraints_applied: {
    sensor_id: string;
    road_name: string;
    edge_id: string;
    distance_m: number;
    observed_speed_kph: number;
    applied_speed_kph: number;
    observed_at: string;
  }[];
  model_version: string;
  horizon_s: number;
  scenario: ScenarioIn;
  simulation: Record<string, unknown>;
  edges: {
    id: string;
    ci: number;
    level: Level;
    pred_ci: number;
    pred_level: Level;
    shape: [number, number][];
  }[];
  notice: string;
}

export interface LiveRouteOption {
  rank: number;
  label: string;
  distance_m: number;
  travel_time_s: number;
  traffic_delay_s: number | null;
  geometry: [number, number][];
  predicted_travel_time_s: number | null;
  forecast_adjustment_s: number | null;
  forecast_sensor_ids: string[];
  forecast_sensor_count: number;
  recommendation_rank: number | null;
  recommended: boolean;
  simulation_forecast_edge_ids?: string[];
  simulation_forecast_edge_count?: number;
  simulation_forecast_coverage_pct?: number;
  simulation_forecast_adjustment_s?: number;
}

export interface LiveTrafficRoutes {
  provider: string;
  source: "live_traffic_routing";
  traffic_aware: boolean;
  forecast_source: "tomtom_history_trend" | "bengaluru_sumo_gnn" | null;
  simulation_run_id?: string;
  forecast_horizon_s?: number;
  origin: { id: string; road_name: string; latitude: number; longitude: number };
  destination: { id: string; road_name: string; latitude: number; longitude: number };
  requested_at: string;
  routes: LiveRouteOption[];
  notice: string;
}

const get = <T = any>(url: string, params?: object) => http.get<T>(url, { params }).then((r) => r.data);
const post = <T = any>(url: string, body?: object) => http.post<T>(url, body).then((r) => r.data);

export const api = {
  health: () => get("/api/v1/health"),
  network: () => get<NetworkData>("/api/v1/network"),
  trafficCurrent: () => get("/api/v1/traffic/current"),
  trafficPredictions: () => get("/api/v1/traffic/predictions"),
  bengaluruTraffic: () => get<LiveTrafficStatus>("/api/v1/traffic/bengaluru"),
  bengaluruPredictions: () => get<LiveTrafficPredictions>("/api/v1/traffic/bengaluru/predictions"),
  runBengaluruSumo: (scenario: ScenarioIn) =>
    post<{ run_id: string }>("/api/v1/traffic/bengaluru/sumo/run", { scenario }),
  bengaluruTrafficHistory: (limit = 1000) => get<{ readings: LiveTrafficReading[] }>("/api/v1/traffic/bengaluru/history", { limit }),
  pollBengaluruTraffic: () => post<{ status: string; observed_at: string; saved_readings: number; failures: { sensor_id: string; message: string }[] }>("/api/v1/traffic/bengaluru/poll"),
  bengaluruRoutes: (origin_id: string, destination_id: string, simulation_run_id?: string) =>
    get<LiveTrafficRoutes>("/api/v1/traffic/bengaluru/routes", { origin_id, destination_id, simulation_run_id }),
  runPrediction: (scenario: ScenarioIn, mode: "sumo" | "dataset_replay") => post<{ run_id: string }>("/api/v1/predictions/run", { scenario, mode }),
  runSimulation: (scenario: ScenarioIn, intervention: object | null) => post<{ run_id: string }>("/api/v1/simulations/run", { scenario, intervention }),
  evaluate: (body: object) => post<{ run_id: string }>("/api/v1/interventions/evaluate", body),
  run: (id: string) => get<Run>(`/api/v1/runs/${id}`),
  cancelRun: (id: string) => post(`/api/v1/runs/${id}/cancel`),
  candidates: (junction_id: string) => get("/api/v1/interventions/candidates", { junction_id }),
  altRoute: (from_edge: string, to_edge: string) => get("/api/v1/routes/alternative", { from_edge, to_edge }),
  experiences: () => get("/api/v1/experiences"),
  searchExperiences: (params: object) => get("/api/v1/experiences/search", params),
  benchmarks: () => get("/api/v1/benchmarks"),
  benchmark: (id: string) => get(`/api/v1/benchmarks/${id}`),
  runBenchmark: (body: object) => post<{ run_id: string }>("/api/v1/benchmarks/run", body),
  modelEvaluation: () => get("/api/v1/models/evaluation"),
};
