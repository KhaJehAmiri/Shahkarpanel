import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

interface State<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  status: number | null;
  reload: () => void;
}

export function useFetch<T>(fn: () => Promise<T>, deps: any[] = []): State<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<number | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fnRef.current();
      setData(res);
      setStatus(200);
    } catch (e: any) {
      setError(e?.message || "Error");
      setStatus(e instanceof ApiError ? e.status : null);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    run();
  }, [run]);

  return { data, loading, error, status, reload: run };
}

export function usePolling(fn: () => void, intervalMs: number, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(fn, intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, enabled]);
}
