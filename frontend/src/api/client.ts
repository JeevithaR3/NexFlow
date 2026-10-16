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

const get = <T = any>(url: string, params?: object) => http.get<T>(url, { params }).then((r) => r.data);
const post = <T = any>(url: string, body?: object) => http.post<T>(url, body).then((r) => r.data);

export const api = {
  health: () => get("/api/v1/health"),
  network: () => get<NetworkData>("/api/v1/network"),
  trafficCurrent: () => get("/api/v1/traffic/current"),
  trafficPredictions: () => get("/api/v1/traffic/predictions"),
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
