# GNN forecasting and Experience Memory

## GNN
Nodes = 48 road segments; edges = SUMO connections (symmetrised, normalised). Input: last 5 intervals x 5 features (flow veh/h, mean speed m/s, occupancy %, vehicle count, halted vehicles) + static length/limit.
Model: 2 graph-convolution layers per interval -> GRU per road -> MLP predicting the change of the congestion index (CI). Target: CI of each road 3 intervals (270 s) ahead. CI = clip(1 - v/v_free, 0, 1); levels low < 0.30, moderate < 0.60, high >= 0.60.
Data: 120 SUMO runs (seeds 1000-1119), split chronologically by run order 70/15/15; scaler fitted on training runs only; windows never cross runs; missing values forward-filled within a run (none occur in SUMO output); L1 loss, early stopping on validation MAE.
Result on the test split: GNN MAE 0.144 / RMSE 0.202 / level accuracy 59.7 %; persistence 0.206 / 0.285 / 52.9 %; training mean 0.146; training median 0.144. **Conclusion: clearly better than persistence, no better than a per-road median.** Real-world performance is unknown. PyTorch Geometric is not used (dense GCN is equivalent at this size and avoids install problems).
Real data: `app/ml/real_data.py` documents the CSV schema (observations, sensors, links).

## Experience Memory
Record fields: id, network hash, traffic-light hash, scenario id, feature schema (fv1), objective version, model version, horizon, interval, step length, duration, decision time, demand pattern/scale, junction, 33-D vector, intervention, baseline and result metrics, improvement, improved flag, search runtime, runs used, provenance, config, reuse counters, timestamp.
Retrieval: FAISS `IndexIDMap2(IndexFlatL2)` on the fixed-scale vector; similarity = 1 - RMS distance; threshold default 0.90. Every candidate then passes compatibility checks (network, signal config, schema, objective, model version, horizon/units, simulation settings, target junction, demand within 25 %, intervention legal under current limits, stored outcome improved). An approximate match can never bypass these checks, and an accepted match is only a *proposal*: it is verified in SUMO and kept only if valid and at least 2 % better. The index is written atomically and rebuilt from SQLite if missing or out of sync.
