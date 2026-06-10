"use client";

interface Props {
  used: number;
  total: number;
  usedLabel: string;
  totalLabel: string;
  pct: number;
  exhausted?: boolean;
}

function fmt(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

export function UsageBar({ used, total, usedLabel, totalLabel, pct, exhausted }: Props) {
  const tone = exhausted || pct >= 100 ? "danger" : pct >= 85 ? "warn" : "ok";
  const displayPct = total ? pct : 0;

  return (
    <div className="sub-usage-wrap">
      <div className="sub-usage-labels">
        <span className="sub-text-muted" style={{ fontWeight: 600 }}>{usedLabel}</span>
        <span className="sub-usage-values">
          {fmt(used)}
          <span className="sub-usage-sep">/</span>
          {total ? fmt(total) : totalLabel}
        </span>
        <span className={`sub-usage-pct ${tone}`}>
          {total ? `${displayPct}%` : "∞"}
        </span>
      </div>
      <div className="sub-usage-track">
        <div className={`sub-usage-fill ${tone}`} style={{ width: `${total ? displayPct : 4}%` }} />
      </div>
    </div>
  );
}
