# API (`/api/v1`, interactive docs at `/docs`)
Errors always look like `{"error": {"code", "message", "hint", "details?"}}` (never a stack trace). Long operations return `202 {"run_id","status","poll"}`; poll `GET /runs/{id}` (`status`: queued, running, succeeded, failed, cancelled; `progress` 0-1; `result` or `error`).

| Route | Purpose |
|---|---|
| `GET /health` | SUMO status + setup help, network, model, memory stats, twin availability |
| `GET /network` | roads (lat/lon polylines), junctions, signal limits, congestion thresholds; flagged synthetic |
| `GET /traffic/current` · `GET /traffic/predictions` | synthetic SUMO digital-twin state |
| `GET /traffic/bengaluru` | TomTom provider status and latest reading for each configured Bengaluru road point; key is never returned |
| `GET /traffic/bengaluru/predictions` | 15-minute bounded speed-trend forecasts from recent TomTom readings for monitored segments |
| `GET /traffic/bengaluru/history?sensor_id&limit` | locally stored historical TomTom readings (max `limit` 5000) |
| `POST /traffic/bengaluru/poll` | manually poll the configured TomTom points immediately |
| `GET /traffic/bengaluru/routes?origin_id&destination_id` | TomTom current-traffic-aware real-road route and alternatives between monitored Bengaluru locations |
| `POST /predictions/run` `{scenario, mode: sumo\|dataset_replay}` | forecast job. `dataset_replay` is a labelled recorded-data demo |
| `POST /simulations/run` `{scenario, intervention?}` | baseline vs intervention SUMO runs + objective evaluation |
| `GET /simulations/{id}` · `GET /runs` · `GET /runs/{id}` · `POST /runs/{id}/cancel` | run tracking |
| `POST /interventions/evaluate` `{scenario, junction_id?, use_memory, include_rerouting, store_experience}` | full decision (forecast, memory, SUMO) |
| `GET /interventions/candidates?junction_id=` | limits, default plan, candidate plans |
| `GET /routes/alternative?from_edge&to_edge` | estimated alternative route (not a SUMO result) |
| `GET /experiences` · `GET /experiences/{id}` · `GET /experiences/search?source=current\|experience&experience_id&junction_id&k&threshold` | memory contents and retrieval with accept/reject reasons |
| `GET /benchmarks` · `GET /benchmarks/{id}` · `POST /benchmarks/run` | A-vs-B benchmark |
| `GET /models/evaluation` | MAE/RMSE vs baselines and training history |

Scenario: `{pattern: balanced\|ew_heavy\|ns_heavy, demand_scale 0.2-3, seed >= 0}`.
Intervention: `{type: signal_timing, junction_id, green_s: {"0": 25, "2": 55}}` (phase index -> seconds, within 10-60 s) or `{type: reroute, reroute_share, reroute_period_s}`.
`source` in results: `simulated`, `memory_verified`, `sumo_simulation`, `dataset_replay`, `no_change`.

The optional TomTom collector reads `NEXFLOW_TOMTOM_API_KEY` from the backend environment, polls every `NEXFLOW_TRAFFIC_POLL_INTERVAL_S` seconds (default 300), and keeps 30 days of observations by default. `/traffic/bengaluru/predictions` reports a bounded linear trend over up to six recent speed/free-flow ratios, only when at least three readings span two polling intervals and the newest reading is no older than two polling intervals. `/traffic/bengaluru/routes` uses TomTom's current-traffic Routing API for route geometry and baseline ETAs, then applies this estimate only to forecasted sensor geometries within 50 meters of a candidate route. Unmatched portions keep the provider ETA; if no sensor segment matches, no forecast-based recommendation is returned. This is separate from the synthetic SUMO/GNN pipeline and is not a full-trip predictor or traffic-control action.
