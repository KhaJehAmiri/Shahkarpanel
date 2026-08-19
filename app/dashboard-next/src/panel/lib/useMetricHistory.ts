import { useEffect, useRef, useState } from "react";

/** Rolling buffer for live sparkline charts (CPU, RAM, bandwidth). */
export function useMetricHistory(value: number | undefined, capacity = 32, pollMs = 250) {
  const [history, setHistory] = useState<number[]>([]);
  const latest = useRef<number | undefined>(value);
  latest.current = value;

  useEffect(() => {
    const id = setInterval(() => {
      const v = latest.current;
      if (v === undefined || Number.isNaN(v)) return;
      setHistory((h) => [...h.slice(-(capacity - 1)), v]);
    }, pollMs);
    return () => clearInterval(id);
  }, [pollMs, capacity]);

  return history;
}
