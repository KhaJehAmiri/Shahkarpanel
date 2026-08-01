import { FC, useId } from "react";

const ACCENT = "var(--sk-accent)";

/* Lightweight inline SVG charts — no external dependency. */

export const Sparkline: FC<{ data: number[]; height?: number; color?: string; filled?: boolean }> = ({
  data,
  height = 48,
  color = ACCENT,
  filled = true,
}) => {
  const uid = useId().replace(/:/g, "");
  if (!data.length) return <div style={{ height }} />;
  const w = 240;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const step = w / Math.max(1, data.length - 1);
  const coords = data.map((d, i) => {
    const x = i * step;
    const y = height - ((d - min) / range) * (height - 8) - 4;
    return [x, y] as const;
  });
  const line = coords.map(([x, y]) => `${x},${y}`).join(" ");
  const area = `0,${height} ${line} ${w},${height}`;
  const gradId = `nxSparkFill-${uid}`;
  return (
    <svg className="sk-spark" width="100%" height={height} viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {filled && <polygon className="sk-spark-fill" points={area} fill={`url(#${gradId})`} />}
      <polyline className="sk-spark-line" points={line} fill="none" stroke={color} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
};

export const BarChart: FC<{ data: { label: string; value: number }[]; height?: number; format?: (n: number) => string }> = ({ data, height = 180, format }) => {
  if (!data.length) return null;
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 10, height, paddingTop: 10 }}>
      {data.map((d, i) => (
        <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: "var(--sk-text-faint)" }}>{format ? format(d.value) : d.value}</div>
          <div
            title={`${d.label}: ${d.value}`}
            style={{
              width: "100%", maxWidth: 46,
              height: `${(d.value / max) * (height - 50)}px`,
              minHeight: 3,
              background: `linear-gradient(180deg, ${ACCENT}, var(--sk-accent-2))`,
              borderRadius: "6px 6px 0 0",
            }}
          />
          <div style={{ fontSize: 11, color: "var(--sk-text-dim)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>{d.label}</div>
        </div>
      ))}
    </div>
  );
};

/** Ranked horizontal bars (leaderboard style) — dense leaderboard for usage boards. */
export const RankBars: FC<{
  data: { label: string; value: number; sub?: string }[];
  format?: (n: number) => string;
  compact?: boolean;
}> = ({ data, format, compact }) => {
  if (!data.length) return null;
  const sorted = [...data].sort((a, b) => b.value - a.value);
  const max = Math.max(...sorted.map((d) => d.value), 1);
  const total = sorted.reduce((sum, d) => sum + d.value, 0) || 1;
  return (
    <div className={`sk-rankbars${compact ? " is-compact" : ""}`}>
      {sorted.map((d, i) => {
        const share = Math.round((d.value / total) * 100);
        const width = Math.max((d.value / max) * 100, 2);
        return (
          <div key={`${d.label}-${i}`} className={`sk-rankrow${i === 0 ? " is-top" : ""}`}>
            <span className={`sk-rank-idx${i < 3 ? ` r${i + 1}` : ""}`} aria-hidden>
              {String(i + 1).padStart(2, "0")}
            </span>
            <div className="sk-rank-body">
              <div className="sk-rank-meta">
                <div className="sk-rank-identity">
                  <span className="sk-rank-label" title={d.label}>{d.label}</span>
                  {d.sub ? <span className="sk-rank-sub">{d.sub}</span> : null}
                </div>
                <div className="sk-rank-metrics">
                  <span className="sk-rank-value">{format ? format(d.value) : d.value}</span>
                  <span className="sk-rank-share">{share}%</span>
                </div>
              </div>
              <div className="sk-rank-track" aria-hidden>
                <div
                  className="sk-rank-fill"
                  style={{ width: `${width}%`, animationDelay: `${i * 60}ms` }}
                />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export const Donut: FC<{
  segments: { label: string; value: number; color: string }[];
  size?: number;
  format?: (n: number) => string;
}> = ({ segments, size = 150, format }) => {
  const total = segments.reduce((a, s) => a + s.value, 0) || 1;
  const r = size / 2 - 14;
  const c = 2 * Math.PI * r;
  let offset = 0;
  const fmt = (n: number) => (format ? format(n) : String(n));
  return (
    <div style={{ display: "flex", gap: 20, alignItems: "center", flexWrap: "wrap" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--sk-surface-3)" strokeWidth={14} />
          {segments.map((s, i) => {
            const len = (s.value / total) * c;
            const el = (
              <circle
                key={i}
                cx={size / 2} cy={size / 2} r={r}
                fill="none" stroke={s.color} strokeWidth={14}
                strokeDasharray={`${len} ${c - len}`}
                strokeDashoffset={-offset}
              />
            );
            offset += len;
            return el;
          })}
        </g>
        <text x="50%" y="50%" textAnchor="middle" dy="0.35em" fontSize={format ? 16 : 22} fontWeight="700" fill="var(--sk-text)">{fmt(total)}</text>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {segments.map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5 }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: s.color }} />
            <span className="sk-muted">{s.label}</span>
            <span style={{ fontWeight: 600 }}>{fmt(s.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
