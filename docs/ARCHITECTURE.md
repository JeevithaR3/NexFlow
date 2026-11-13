# Architecture

```
TomTom Traffic Flow (five Bengaluru road points, polled every 5 min)
   -> SQLite live_traffic_readings
   -> shared city context on every dashboard page
   -> Bengaluru live layer on Traffic map + observed-speed history
   (real measurements; not used as SUMO demand or GNN training data)

TomTom readings (up to six recent samples per monitored road)
   -> bounded 15-minute speed/free-flow trend (minimum 3 samples over 2 poll intervals; latest <= 2 poll intervals old)
   -> forecast overlay on the matching TomTom road geometry
   -> adjust TomTom route ETAs for matching monitored segments and rank alternatives
   (limited real-road baseline; unmonitored route portions keep current provider ETA)

TomTom Routing API (selected monitored origin/destination, traffic=true)
   -> current-traffic route geometry + provider alternatives and baseline ETA
   -> real Bengaluru geometry on the live map
   (provider geometry/ETA; adjusted only where NexFlow has a matched history forecast)

SUMO baseline run (TraCI, 90 s interval observations)
   -> Digital Twin sync (ID validation, observed state, TLS programs)
   -> GNN forecast (CI of every road 270 s ahead)  -> twin.prediction
   -> state vector (fv1, 33-D) -> Experience-Memory lookup (FAISS + compatibility checks)
        accepted match  -> verify the retrieved plan in SUMO -> reuse if valid and >= 2 % better
        otherwise       -> simulate all candidate plans -> best VALID plan under the objective
   -> twin.intervention (status "recommended_simulated") -> API -> dashboard
   -> store experience (SQLite) + FAISS index update
```
Responsibilities: **GNN** only predicts. **Digital Twin** (`app/digital_twin`) holds validated network state; it is not SUMO.
**SUMO** (`app/sumo`) simulates; **TraCI** is the control connection (one label + port + temp dir per run, bounded by `NEXFLOW_MAX_CONCURRENT_SUMO`).
**Experience Memory** (`app/experience_memory`) retrieves; FAISS only does similarity search, SQLite is the source of truth.
**Decision engine** (`app/services/decision.py`) orchestrates; **API** (`app/api/v1/routes.py`) exposes it; long work runs as background jobs (`app/services/jobs.py`).
The dashboard presents the independent real-road trend forecast and synthetic GNN/SUMO pipeline separately. Five TomTom points do not provide network-wide demand, signal phases, or sufficient coverage to forecast an entire trip or validate citywide accuracy. The SUMO intervention and GNN evaluation results remain explicitly synthetic/simulated.

Scenario timing: 1260 s simulated; the forecast is made at t = 540 s from 5 intervals of 90 s; the intervention is active from t = 540 s and metrics are measured over [540, 1260] s. Candidate runs replay the same demand from t = 0 (deterministic, so the first 540 s are identical to the baseline).

Objective and guard-rails: see `app/interventions/objective.py`. Network-wide metrics are always included, and the queue at every neighbouring junction is checked (a plan that pushes congestion downstream is rejected).
