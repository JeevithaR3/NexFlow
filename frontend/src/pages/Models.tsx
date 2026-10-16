import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend, Bar, BarChart } from "recharts";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import BenchmarkPanel from "../components/BenchmarkPanel";
import { Badge, Card, Empty, ErrorBox, Loading, num, pct } from "../components/ui";

const MODELS: [string, string][] = [["gnn", "GNN (spatio-temporal)"], ["persistence", "Persistence (last value)"], ["train_mean", "Training mean per road"], ["train_median", "Training median per road"]];

export default function Models() {
  const m = useAsync(() => api.modelEvaluation());
  const d = m.data;
  const rows = d?.available ? MODELS.filter(([k]) => d.test[k]).map(([k, label]) => ({ key: k, label, ...d.test[k] })) : [];
  return (
    <>
      <header>
        <h1 className="text-2xl font-semibold">Model evaluation</h1>
        <p className="text-sm text-slate-600">Trained and evaluated on synthetic SUMO data only. These numbers say nothing about real-world accuracy.</p>
      </header>
      <ErrorBox error={m.error} />
      {m.loading && !d ? <Loading /> : !d?.available ? <Empty title="No trained model">{d?.reason}</Empty> : (
        <>
          <Card title="Setup">
            <dl className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
              <dt className="text-slate-500">Target</dt><dd className="col-span-3">{d.target}</dd>
              <dt className="text-slate-500">Horizon</dt><dd>{d.horizon_s}s ({d.horizon_intervals}×{d.interval_s}s)</dd>
              <dt className="text-slate-500">Input window</dt><dd>{d.window_intervals} intervals</dd>
              <dt className="text-slate-500">Split</dt><dd className="col-span-3">{d.split.type}: {d.split.train_runs} train / {d.split.val_runs} val / {d.split.test_runs} test runs · test samples {d.test.n_samples}</dd>
              <dt className="text-slate-500">Units</dt><dd className="col-span-3">{d.units}</dd>
              <dt className="text-slate-500">Model</dt><dd>{d.model_version} {d.synthetic_data && <Badge tone="amber">synthetic data</Badge>}</dd>
            </dl>
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Test-set error (lower is better)">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-xs text-slate-500"><th>Model</th><th>MAE</th><th>RMSE</th><th>Level accuracy</th></tr></thead>
                <tbody>{rows.map((r: any) => <tr key={r.key} className={`border-t border-slate-100 ${r.key === "gnn" ? "font-semibold" : ""}`}><td className="py-1">{r.label}</td><td>{num(r.mae, 4)}</td><td>{num(r.rmse, 4)}</td><td>{pct(r.level_accuracy)}</td></tr>)}</tbody>
              </table>
              <div style={{ height: 200 }} className="mt-3">
                <ResponsiveContainer><BarChart data={rows}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="key" /><YAxis /><Tooltip />
                  <Bar dataKey="mae" name="MAE" fill="#0f766e" /><Bar dataKey="rmse" name="RMSE" fill="#64748b" /><Legend /></BarChart></ResponsiveContainer>
              </div>
              <p className="mt-2 text-xs text-slate-500">The per-interval congestion index is noisy, so simple per-road baselines are hard to beat; compare the rows honestly.</p>
            </Card>
            <Card title="Training history">
              <div style={{ height: 300 }}>
                <ResponsiveContainer><LineChart data={d.history}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="epoch" /><YAxis /><Tooltip /><Legend />
                  <Line type="monotone" dataKey="train_loss" name="train loss" stroke="#64748b" dot={false} />
                  <Line type="monotone" dataKey="val_mae" name="validation MAE" stroke="#0f766e" dot={false} /></LineChart></ResponsiveContainer>
              </div>
              <p className="text-xs text-slate-500">{d.epochs_run} epochs (early stopping on validation MAE), best {num(d.best_val_mae, 4)}, {d.train_seconds}s.</p>
            </Card>
          </div>
        </>
      )}
      <BenchmarkPanel />
    </>
  );
}
