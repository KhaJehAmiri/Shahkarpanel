import { FC, useId } from "react";

type Tone = "accent" | "ok" | "warn" | "danger" | "info";

const TONE_COLOR: Record<Tone, string> = {
  accent: "var(--sk-accent)",
  ok: "var(--sk-ok)",
  warn: "var(--sk-warn)",
  danger: "var(--sk-danger)",
  info: "var(--sk-info)",
};

export const GaugeRing: FC<{
  value: number;
  max?: number;
  label: string;
  sub?: string;
  size?: number;
  tone?: Tone;
  animated?: boolean;
}> = ({ value, max = 100, label, sub, size = 120, tone = "accent", animated = true }) => {
  const uid = useId().replace(/:/g, "");
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const r = size / 2 - 12;
  const c = 2 * Math.PI * r;
  const dash = (pct / 100) * c;
  const color = TONE_COLOR[tone];
  const gradId = `gauge-grad-${uid}`;

  return (
    <div className={`sk-gauge ${animated ? "sk-gauge-live" : ""}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="sk-gauge-svg">
        <defs>
          <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={color} />
            <stop offset="100%" stopColor="var(--sk-accent-2)" />
          </linearGradient>
        </defs>
        <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="var(--sk-surface-3)"
            strokeWidth={10}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={`url(#${gradId})`}
            strokeWidth={10}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${c}`}
            className="sk-gauge-arc"
          />
        </g>
        <text x="50%" y={sub ? "43%" : "50%"} textAnchor="middle" className="sk-gauge-value">
          {`${pct.toFixed(1)}%`}
        </text>
        {sub ? (
          <text x="50%" y="62%" textAnchor="middle" className="sk-gauge-sub">
            {sub}
          </text>
        ) : null}
      </svg>
      <div className="sk-gauge-label">{label}</div>
    </div>
  );
};
