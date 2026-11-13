# NexFlow: traffic prediction and digital twin (academic prototype)

GNN forecasting of congestion → Digital Twin state → Experience Memory (FAISS) → SUMO/TraCI verification and search of signal-timing plans → React dashboard.
The dashboard combines two clearly-labelled sources: TomTom live traffic speeds at five Bengaluru road points, and the synthetic SUMO dataset used for GNN forecasts and intervention experiments. The shared city readings appear across the tabs and in the Traffic map, but are not fed into the synthetic GNN or SUMO model. Recommendations are simulated only and never touch real signals.
The Experience-Memory idea is our *proposed efficiency improvement*; it is not claimed to be novel, and its benefit is only what `scripts/run_benchmark.py` measures.

## Status (what is implemented and verified)
| Part | State |
|---|---|
| SUMO network, demand generator, TraCI runner (signals, rerouting, metrics, cleanup) | implemented, run against SUMO 1.28 |
| Digital Twin (validated IDs, observed vs predicted, persisted state) | implemented |
| GNN (GCN + GRU), training, baselines, checkpoint, inference | implemented, trained |
| Experience Memory (SQLite + FAISS, compatibility checks, SUMO re-verification) | implemented |
| Decision engine + A-vs-B benchmark | implemented; benchmark run once (results below) |
| FastAPI (`/api/v1`) | implemented, tested over HTTP with real SUMO |
| TomTom Bengaluru corridor collector | optional; polls five road points and retains 30 days locally when an API key is configured |
| React frontend (6 pages) | shared Bengaluru status appears on every page; Traffic map switches between live TomTom points and the clearly-labelled SUMO simulation |
| Tests | backend 42 pass (pytest); frontend 7 pass (vitest); type-check and build pass |
| Limits | one benchmark run on one machine; no CI; no browser-compat testing beyond headless Chromium; OSM tiles need internet |

### Measured results (synthetic data, one machine; indicative only)
* **GNN** (test split, 270 s horizon): MAE 0.144 vs persistence 0.206 (about 30 % lower), but **no better than a per-road training median (0.144)**. The per-interval congestion target is noisy.
* **Benchmark** (8 warm-up + 12 evaluation scenarios, `data/benchmarks/benchmark_bc3e6bee4a.json`): memory-first used 101 SUMO runs vs 108 (6.5 % fewer) and 360 s vs 384 s (6.2 % less); the memory was reused in only 1 of 12 decisions (8 %), 2 retrieved plans failed SUMO verification, 9 had no acceptable match; it was slower in 5 scenarios and less effective in 1; mean improvement A 6.3 % vs B 6.0 %. Filling the memory cost 72 runs, which would take about 123 decisions to recover at this saving rate. **So the efficiency benefit is real but small here; the idea is not shown to be a large win.** Other apps were running during the benchmark, so timings are noisy.

## Prerequisites
Python 3.11, Node 18+. SUMO is installed by `pip` (`eclipse-sumo`); a system install also works (set `SUMO_HOME` or `NEXFLOW_SUMO_BINARY`).

## Setup
Windows (PowerShell):
```
python -m venv .venv ; .venv\Scripts\activate
pip install -r backend\requirements.txt
cd frontend ; npm install ; cd ..
```
Linux/macOS: `python3.11 -m venv .venv && source .venv/bin/activate && pip install -r backend/requirements.txt && (cd frontend && npm install)`

## Optional Bengaluru live traffic and routes
The live dataset uses TomTom's [Flow Segment Data API](https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-flow/flow-segment-data) to sample the nearest road segment at MG Road, Indiranagar, Whitefield, Koramangala and Silk Board. It polls every five minutes by default, persists observations in the local SQLite database, and removes readings older than 30 days. The API key stays in the backend; it is never sent to the browser or written into the database.

Create a root `.env` file (already gitignored) and add your TomTom key:
```
NEXFLOW_TOMTOM_API_KEY=your_tomtom_api_key
NEXFLOW_TRAFFIC_POLL_INTERVAL_S=300
```
Restart the backend. Collection starts automatically; **Traffic history → Poll now** also requests an immediate sample. Each poll makes one TomTom request per road point. Without a key, the page remains available and explains how to configure the feed.

On **Traffic map → Bengaluru live**, choose an origin and destination (the demo defaults to MG Road → Silk Board) and select **Find live routes**. The backend calls TomTom's [Routing API](https://docs.tomtom.com/routing-api/documentation/tomtom-maps/v1/calculate-route) with traffic-aware routing enabled, then draws the fastest route and any alternatives TomTom returns on the actual Bengaluru basemap. Route distance, ETA and reported traffic delay come from the provider. Availability depends on your TomTom account's Routing API access and quota.

The shared traffic context is visible throughout the dashboard. **Traffic map** defaults to live Bengaluru points and can switch to **SUMO simulation**; **Overview** shows the same latest city readings, and **Traffic history** shows their stored time series. This is still a live feed for five configured sample points, not a citywide traffic feed. Road labels and coordinates are fixed in `backend/app/services/tomtom_traffic.py`.

On the Bengaluru map, **NexFlow forecast** plots a 15-minute speed estimate on each monitored road segment with sufficient readings. This MVP fits a bounded linear trend to up to six recent TomTom speed/free-flow ratios; it requires at least three readings spanning two poll intervals, with the newest no older than two poll intervals. Route alternatives are ranked by TomTom's current ETA adjusted for the forecasted travel-time change on monitored segment geometries that overlap each route. Parts of the route without a monitored match retain TomTom's current ETA. The UI reports the matching segment coverage.

This is a small real-road forecasting baseline, not the existing GNN, not a full-trip forecast, and not a signal-control action. The existing GNN, SUMO scenarios, intervention memory and benchmarks still use the synthetic grid. Five fixed TomTom sample points do not provide citywide coverage or establish model accuracy; the UI labels both sources explicitly.

## Run
```
python scripts/generate_network.py              # SUMO network + routes + config (already included)
python scripts/generate_dataset.py --runs 120   # ~4 min, synthetic data (already included)
python scripts/train_gnn.py                     # trains and prints MAE/RMSE vs baselines (checkpoint included)
cd backend ; uvicorn app.main:app --port 8000   # API docs at http://localhost:8000/docs
cd frontend ; npm run dev                       # dashboard at http://localhost:5173
```
Demo flow: open **Traffic map → Bengaluru live** and explain that the dashed colored road segments show NexFlow's 15-minute trend forecast from collected TomTom history (allow at least three samples over two poll intervals). Request MG Road → Silk Board routes; NexFlow ranks alternatives using forecasts only on matching monitored segments, while TomTom supplies route geometry and current-traffic ETAs. Switch to **SUMO simulation** to compare the separate synthetic GNN/SUMO prototype. Finally run **Scenario simulation → Find best intervention** (a SUMO-only simulation that creates the first stored experience).
Populate/measure memory: `python scripts/run_benchmark.py --warmup 8 --eval 12` (≈15–20 min), or use the Benchmark panel.

## Tests
```
cd backend ; python -m pytest        # tests marked `sumo` are skipped (environment limitation) if SUMO is missing
cd frontend ; npm test ; npm run build
```

## Features needing SUMO
GNN/SUMO prediction, scenario simulation, decisions, benchmark, dataset generation. The separate limited TomTom-history trend forecast does not need SUMO. Without SUMO the API reports a clear `sumo_unavailable` status for simulation features.

## Key definitions
* Congestion index CI = clip(1 − v/v_free, 0, 1) per road segment per 90 s interval; low < 0.30, moderate < 0.60, high ≥ 0.60 (`app/digital_twin/congestion.py`).
* Objective: weighted ratio of wait, travel time, queues and throughput vs baseline, plus guard-rails on neighbouring junction queues (`app/interventions/objective.py`).
* Memory retrieval: FAISS L2 on a fixed-scale 33-D vector → similarity = 1 − RMS distance; then threshold + compatibility checks; a retrieved plan is always verified in SUMO (`app/experience_memory/`).

## Troubleshooting
* `sumo_unavailable`: `pip install eclipse-sumo traci sumolib` or set `NEXFLOW_SUMO_BINARY`.
* `model_not_trained`: run `python scripts/train_gnn.py` (retrain after regenerating the network).
* Frontend "Cannot reach the NexFlow API": start the backend on port 8000.
* Basemap blank offline: untick "OSM basemap"; the synthetic grid is not aligned with real OSM streets.

Before the demo (10 minutes)
Start the backend and the frontend, and open http://localhost:5173. The backend takes about 30 s the first time because PyTorch loads slowly. The shared header shows whether TomTom is configured and how many corridor readings are available.
Do a trial run of the full flow so nothing is cold. Run a prediction on Overview, then “Find best intervention” on the Scenario page once. That also puts one entry in the Experience Memory.
The OSM basemap requires internet. If it is unavailable, the SUMO simulation grid still renders; live TomTom road lines appear only where the provider returned road geometry.
Keep the benchmark result visible on the Memory page. It is already loaded.
Fallback if SUMO misbehaves live: use “Use demo replay”, which is labelled as recorded synthetic data. Say openly that it is a replay.
Demo script (about 10 minutes)

1. The problem and the architecture (1 min). Open the Overview and say: “We forecast congestion with a graph neural network. A SUMO digital twin tests fixes, and a memory of past fixes tries to avoid re-simulating.” Keep the pipeline in docs/ARCHITECTURE.md open as a reference.

2. Forecast (2 min, Overview).

Click “Run live SUMO prediction”. It takes about 5 s.
Show the chart of current against predicted congestion and the “SUMO 1.28 / model loaded” tiles.
Say: “SUMO simulates 9 minutes of traffic, the GNN predicts every road’s congestion 270 seconds ahead.”

3. Live and simulated maps (2 min, Traffic map).

Choose “Bengaluru live,” request the MG Road → Silk Board trip and show the actual route geometry and TomTom's traffic-aware ETA/alternatives. Explain this is a five-location sample. Switch to “SUMO simulation” to show the generated grid and its current/predicted congestion.
Say explicitly: “TomTom computes these live routes. NexFlow's GNN forecast and intervention experiments still run on synthetic SUMO data; connecting the model to enough real road history is future work.”

4. Intervention test (2 min, Scenario simulation).

Pick junction B1 and set one green phase to 25 s and the other to 55 s. Click “Run baseline vs intervention” (about 8 s).
Show the metrics table, then the neighbour-junction table. If a neighbouring queue grows, the plan is rejected by the guard-rails. Earlier, my test run of this same setting was rejected because the queue at junction C1 grew.

5. Best plan (2 min, same page).

Click “Find best intervention”. It takes about 35 s, so talk while it runs.
Explain the candidate table: 8 plans tested and the best valid one picked.
The second time you click it, the memory may be consulted. Open the Experience memory page and click Search to show accepted and rejected matches with reasons.

6. Results honesty slide (1 min, Memory page benchmark panel). Say: “We measured it. Memory saved 6.5% of runs. It was reused in 1 of 12 cases, and two retrieved plans failed verification. The benefit is real but small here.”

What to say about the results
GNN: it beats persistence (MAE 0.144 vs 0.206) but is level with a simple per-road median baseline. It is trained on synthetic data only, so say nothing about real-world accuracy.
Memory: memory is our proposed efficiency idea, not a novel invention. The benchmark gives a modest benefit, and filling the memory costs about 72 runs, which would take about 123 decisions to recover.
Safety: all recommendations are simulated. Nothing controls a real signal.
Likely questions
“Why not just trust the retrieved plan?” Similarity doesn’t prove a plan works. Every retrieved plan passes compatibility checks and is then verified in SUMO.
“Is this a digital twin?” The project shares live Bengaluru context across the dashboard and displays it on the map. Its intervention-testing twin is still the separate synthetic SUMO network.
“Does the model use live Bengaluru traffic?” No. The TomTom collector builds a separate local history; the forecast model remains trained and evaluated on synthetic SUMO data.
“Why is the GNN no better than the median?” The per-interval congestion target is noisy. Name this as the main limitation.