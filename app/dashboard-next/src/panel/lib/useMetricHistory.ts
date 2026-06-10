import { useEffect, useRef, useState } from "react";

/** Rolling buffer for live sparkline charts (CPU, RAM, bandwidth). */
export function useMetricHistory(value: number | undefined, capacity = 24, pollMs = 5000) {
  const [history, setHistory] = useState<number[]>([]);
  const last = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (value === undefined || Number.isNaN(value)) return;
    if (last.current === value) return;
    last.current = value;
    setHistory((h) => [...h.slice(-(capacity - 1)), value]);
  }, [value, capacity]);

  useEffect(() => {
    const id = setInterval(() => {
      if (last.current !== undefined) {
        setHistory((h) => (h.length ? h : [last.current!]));
      }
    }, pollMs);
    return () => clearInterval(id);
  }, [pollMs]);

  return history;
}
