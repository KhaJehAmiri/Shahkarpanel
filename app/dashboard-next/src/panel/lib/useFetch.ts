import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

interface State<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  status: number | null;
  reload: () => void;
}

const RETRYABLE = new Set([0, 502, 503, 504]);

async function withRetry<T>(fn: () => Promise<T>, signal?: AbortSignal): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < 2; attempt++) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    try {
      return await fn();
    } catch (e: any) {
      lastErr = e;
      const status = e instanceof ApiError ? e.status : 0;
      if (attempt === 0 && RETRYABLE.has(status)) {
        await new Promise((r) => setTimeout(r, 400));
        continue;
      }
      throw e;
    }
  }
  throw lastErr;
}

export function useFetch<T>(fn: () => Promise<T>, deps: any[] = []): State<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<number | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const genRef = useRef(0);

  const run = useCallback(async () => {
    const gen = ++genRef.current;
    setLoading(true);
    setError(null);
    try {
      const res = await withRetry(() => fnRef.current());
      if (gen !== genRef.current) return;
      setData(res);
      setStatus(200);
    } catch (e: any) {
      if (gen !== genRef.current) return;
      if (e?.name === "AbortError") return;
      setError(e?.message || "Error");
      setStatus(e instanceof ApiError ? e.status : null);
    } finally {
      if (gen === genRef.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    run();
    return () => {
      genRef.current += 1;
    };
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

/** Re-fetch when the browser tab becomes visible again. */
export function useFocusReload(reload: () => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const onVis = () => {
      if (document.visibilityState === "visible") reload();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [reload, enabled]);
}

/** Polling + focus reload for live dashboard data. */
export function useLiveReload(reload: () => void, intervalMs = 30000, enabled = true) {
  usePolling(reload, intervalMs, enabled);
  useFocusReload(reload, enabled);
}
