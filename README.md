# NexFlow: traffic prediction and digital twin (academic prototype)

GNN forecasting of congestion → Digital Twin state → Experience Memory (FAISS) → SUMO/TraCI verification and search of signal-timing plans → React dashboard.
**All data is synthetic**, produced by SUMO on a generated 3×3 signalised grid. Recommendations are simulated only and never touch real signals.
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
| React frontend (5 pages) | implemented; all pages screenshotted against the live API |
| Tests | backend 38 pass (pytest); frontend 6 pass (vitest); type-check and build pass |
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

## Run
```
python scripts/generate_network.py              # SUMO network + routes + config (already included)
python scripts/generate_dataset.py --runs 120   # ~4 min, synthetic data (already included)
python scripts/train_gnn.py                     # trains and prints MAE/RMSE vs baselines (checkpoint included)
cd backend ; uvicorn app.main:app --port 8000   # API docs at http://localhost:8000/docs
cd frontend ; npm run dev                       # dashboard at http://localhost:5173
```
First simulation: open **Overview → Run live SUMO prediction**, then **Traffic map**; then **Scenario simulation → Find best intervention** (creates the first stored experience).
Populate/measure memory: `python scripts/run_benchmark.py --warmup 8 --eval 12` (≈15–20 min), or use the Benchmark panel.

## Tests
```
cd backend ; python -m pytest        # tests marked `sumo` are skipped (environment limitation) if SUMO is missing
cd frontend ; npm test ; npm run build
```

## Features needing SUMO
Live prediction, scenario simulation, decisions, benchmark, dataset generation. Without SUMO the API reports a clear `sumo_unavailable` status; only the *labelled* recorded-data replay of the forecast works.

## Key definitions
* Congestion index CI = clip(1 − v/v_free, 0, 1) per road segment per 90 s interval; low < 0.30, moderate < 0.60, high ≥ 0.60 (`app/digital_twin/congestion.py`).
* Objective: weighted ratio of wait, travel time, queues and throughput vs baseline, plus guard-rails on neighbouring junction queues (`app/interventions/objective.py`).
* Memory retrieval: FAISS L2 on a fixed-scale 33-D vector → similarity = 1 − RMS distance; then threshold + compatibility checks; a retrieved plan is always verified in SUMO (`app/experience_memory/`).

## Troubleshooting
* `sumo_unavailable`: `pip install eclipse-sumo traci sumolib` or set `NEXFLOW_SUMO_BINARY`.
* `model_not_trained`: run `python scripts/train_gnn.py` (retrain after regenerating the network).
* Frontend "Cannot reach the NexFlow API": start the backend on port 8000.
* Basemap blank offline: untick "OSM basemap"; the synthetic grid is not aligned with real OSM streets.
