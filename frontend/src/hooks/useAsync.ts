import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, Run, toApiError } from "../api/client";

/** Load data once (and on demand). Exposes loading / error / data for realistic UI states. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    fn().then((d) => { setData(d); setError(null); }).catch((e) => setError(toApiError(e))).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(reload, [reload]);
  return { data, error, loading, reload };
}

/** Start a background run and poll it until it finishes. */
export function useRunner<T = any>() {
  const [run, setRun] = useState<Run<T> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  const start = useCallback(async (submit: () => Promise<{ run_id: string }>): Promise<Run<T> | null> => {
    setBusy(true); setError(null); setRun(null);
    try {
      const { run_id } = await submit();
      return await new Promise<Run<T> | null>((resolve) => {
        const tick = async () => {
          try {
            const r = (await api.run(run_id)) as Run<T>;
            setRun(r);
            if (r.status === "succeeded" || r.status === "failed" || r.status === "cancelled") {
              if (r.status === "failed" && r.error) setError(new ApiError(r.error.message, r.error.code, undefined, r.error.hint));
              setBusy(false); resolve(r);
            } else timer.current = window.setTimeout(tick, 1000);
          } catch (e) { setError(toApiError(e)); setBusy(false); resolve(null); }
        };
        tick();
      });
    } catch (e) { setError(toApiError(e)); setBusy(false); return null; }
  }, []);
  return { run, error, busy, start };
}
