import { FC, useId } from "react";

type Tone = "accent" | "ok" | "warn" | "danger" | "info";

const TONE_COLOR: Record<Tone, string> = {
  accent: "var(--nx-accent)",
  ok: "var(--nx-ok)",
  warn: "var(--nx-warn)",
  danger: "var(--nx-danger)",
  info: "var(--nx-info)",
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
    <div className={`nx-gauge ${animated ? "nx-gauge-live" : ""}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="nx-gauge-svg">
        <defs>
          <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={color} />
            <stop offset="100%" stopColor="var(--nx-accent-2)" />
          </linearGradient>
        </defs>
        <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="var(--nx-surface-3)"
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
            className="nx-gauge-arc"
          />
        </g>
        <text x="50%" y="46%" textAnchor="middle" className="nx-gauge-value">
          {Math.round(pct)}%
        </text>
        <text x="50%" y="58%" textAnchor="middle" className="nx-gauge-sub">
          {sub || ""}
        </text>
      </svg>
      <div className="nx-gauge-label">{label}</div>
    </div>
  );
};
