"use client";

import { QR } from "@/components/QR";

interface Props {
  title: string;
  hint: string;
  url: string;
  copyLabel: string;
  copiedLabel: string;
  copied: boolean;
  onCopy: () => void;
  accent: "indigo" | "rose";
  downloadHref?: string;
  downloadLabel?: string;
  paused?: boolean;
  pausedHint?: string;
  embedded?: boolean;
}

export function ConnectCard({
  title,
  hint,
  url,
  copyLabel,
  copiedLabel,
  copied,
  onCopy,
  accent,
  downloadHref,
  downloadLabel,
  paused,
  pausedHint,
  embedded,
}: Props) {
  const accentCls = accent === "rose" ? "sub-card-accent-rose" : "sub-card-accent-indigo";
  const btnCls = accent === "rose" ? "sub-btn-primary sub-btn-rose" : "sub-btn-primary";
  const wrap = embedded ? "sub-connect-embedded" : `sub-card sub-connect-compact ${accentCls}`;

  if (paused) {
    return (
      <div className={embedded ? "sub-connect-embedded p-2" : `sub-card ${accentCls} p-4`}>
        <h3 className="sub-mobile-title text-sm font-extrabold text-slate-800">{title}</h3>
        <p className="sub-mobile-text mt-2 text-sm text-slate-500">{pausedHint}</p>
      </div>
    );
  }

  return (
    <div className={`${wrap} p-3`}>
      <h3 className="sub-mobile-title text-sm font-extrabold text-slate-800">{title}</h3>
      <p className="sub-connect-hint line-clamp-2 text-xs leading-snug text-slate-500">{hint}</p>

      <div className="sub-connect-inline">
        <div className="sub-connect-qr-box shrink-0 rounded-lg border border-slate-100 bg-white p-1 shadow-sm">
          {url ? <QR value={url} size={84} /> : null}
        </div>
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
            <input
              readOnly
              dir="ltr"
              value={url}
              className="sub-link-input min-w-0 flex-1 border-0 bg-transparent px-2 py-2 outline-none text-slate-700"
              onClick={(e) => (e.target as HTMLInputElement).select()}
            />
            <button
              type="button"
              onClick={onCopy}
              className={`shrink-0 border-s border-slate-200 px-3 text-xs font-bold ${copied ? "bg-emerald-50 text-emerald-700" : "bg-white text-indigo-600 hover:bg-indigo-50"}`}
            >
              {copied ? `✓` : copyLabel}
            </button>
          </div>
          {downloadHref && downloadLabel ? (
            <a href={downloadHref} download className={`inline-flex w-full justify-center ${btnCls}`}>
              ↓ {downloadLabel}
            </a>
          ) : null}
        </div>
      </div>
    </div>
  );
}
