import { FC, useEffect, useRef, useState } from "react";

/** Smoothly animates numeric values so live dashboards feel alive. */
export const LiveValue: FC<{
  value: number | null | undefined;
  fallback?: string;
  duration?: number;
  format?: (n: number) => string;
  className?: string;
}> = ({ value, fallback = "—", duration = 650, format, className }) => {
  const target = typeof value === "number" && Number.isFinite(value) ? value : null;
  const [display, setDisplay] = useState(target ?? 0);
  const prev = useRef(target ?? 0);
  const raf = useRef(0);

  useEffect(() => {
    if (target == null) return;
    const from = prev.current;
    const to = target;
    prev.current = to;
    if (from === to) {
      setDisplay(to);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(from + (to - from) * eased);
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, duration]);

  if (target == null) return <span className={className}>{fallback}</span>;
  const shown = format ? format(display) : String(Math.round(display));
  return <span className={className}>{shown}</span>;
};
