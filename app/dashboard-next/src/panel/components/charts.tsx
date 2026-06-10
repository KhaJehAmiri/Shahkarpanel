import { FC } from "react";

const ACCENT = "var(--nx-accent)";

/* Lightweight inline SVG charts — no external dependency. */

export const Sparkline: FC<{ data: number[]; height?: number; color?: string }> = ({ data, height = 48, color = ACCENT }) => {
  if (!data.length) return <div style={{ height }} />;
  const w = 240;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const step = w / Math.max(1, data.length - 1);
  const pts = data.map((d, i) => `${i * step},${height - ((d - min) / range) * (height - 6) - 3}`).join(" ");
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2} />
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
          <div style={{ fontSize: 11, color: "var(--nx-text-faint)" }}>{format ? format(d.value) : d.value}</div>
          <div
            title={`${d.label}: ${d.value}`}
            style={{
              width: "100%", maxWidth: 46,
              height: `${(d.value / max) * (height - 50)}px`,
              minHeight: 3,
              background: `linear-gradient(180deg, ${ACCENT}, var(--nx-accent-2))`,
              borderRadius: "6px 6px 0 0",
            }}
          />
          <div style={{ fontSize: 11, color: "var(--nx-text-dim)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>{d.label}</div>
        </div>
      ))}
    </div>
  );
};

/** Ranked horizontal bars (leaderboard style) — much denser than vertical bars for few items. */
export const RankBars: FC<{
  data: { label: string; value: number; sub?: string }[];
  format?: (n: number) => string;
}> = ({ data, format }) => {
  if (!data.length) return null;
  const sorted = [...data].sort((a, b) => b.value - a.value);
  const max = Math.max(...sorted.map((d) => d.value), 1);
  return (
    <div className="nx-rankbars">
      {sorted.map((d, i) => (
        <div key={`${d.label}-${i}`} className={`nx-rankrow ${i === 0 ? "top" : ""}`}>
          <span className={`nx-rank-badge ${i < 3 ? `r${i + 1}` : ""}`}>{i + 1}</span>
          <div className="nx-rank-main">
            <div className="nx-rank-head">
              <span className="nx-rank-label" title={d.label}>{d.label}</span>
              {d.sub && <span className="nx-rank-sub">{d.sub}</span>}
              <span className="nx-rank-value">{format ? format(d.value) : d.value}</span>
            </div>
            <div className="nx-rank-track">
              <div
                className="nx-rank-fill"
                style={{ width: `${Math.max((d.value / max) * 100, 1.5)}%`, animationDelay: `${i * 50}ms` }}
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};

export const Donut: FC<{ segments: { label: string; value: number; color: string }[]; size?: number }> = ({ segments, size = 150 }) => {
  const total = segments.reduce((a, s) => a + s.value, 0) || 1;
  const r = size / 2 - 14;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div style={{ display: "flex", gap: 20, alignItems: "center", flexWrap: "wrap" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--nx-surface-3)" strokeWidth={14} />
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
        <text x="50%" y="50%" textAnchor="middle" dy="0.35em" fontSize="22" fontWeight="700" fill="var(--nx-text)">{total}</text>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {segments.map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5 }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: s.color }} />
            <span className="nx-muted">{s.label}</span>
            <span style={{ fontWeight: 600 }}>{s.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
