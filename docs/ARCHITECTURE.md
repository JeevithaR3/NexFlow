# Architecture

```
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

Scenario timing: 1260 s simulated; the forecast is made at t = 540 s from 5 intervals of 90 s; the intervention is active from t = 540 s and metrics are measured over [540, 1260] s. Candidate runs replay the same demand from t = 0 (deterministic, so the first 540 s are identical to the baseline).

Objective and guard-rails: see `app/interventions/objective.py`. Network-wide metrics are always included, and the queue at every neighbouring junction is checked (a plan that pushes congestion downstream is rejected).
