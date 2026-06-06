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
    <div className="flex min-w-0 flex-1 flex-col justify-center gap-1.5">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-semibold text-slate-500">{usedLabel}</span>
        <span className="tabular-nums font-bold text-slate-800">
          {fmt(used)}
          <span className="mx-1 font-normal text-slate-400">/</span>
          {total ? fmt(total) : totalLabel}
        </span>
        <span
          className={`rounded-md px-2 py-0.5 text-[11px] font-extrabold tabular-nums ${
            tone === "danger" ? "bg-rose-100 text-rose-700" :
            tone === "warn" ? "bg-amber-100 text-amber-700" :
            "bg-indigo-100 text-indigo-700"
          }`}
        >
          {total ? `${displayPct}%` : "∞"}
        </span>
      </div>
      <div className="sub-usage-track">
        <div className={`sub-usage-fill ${tone}`} style={{ width: `${total ? displayPct : 4}%` }} />
      </div>
    </div>
  );
}
