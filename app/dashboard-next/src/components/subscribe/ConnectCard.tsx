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
      <div className={embedded ? "sub-connect-embedded" : `sub-card ${accentCls}`} style={{ padding: 16 }}>
        <h3 className="sub-mobile-title sub-heading" style={{ fontSize: 14 }}>{title}</h3>
        <p className="sub-text-muted" style={{ marginTop: 8, fontSize: 13 }}>{pausedHint}</p>
      </div>
    );
  }

  return (
    <div className={wrap} style={{ padding: embedded ? 0 : 14 }}>
      <h3 className="sub-mobile-title sub-heading" style={{ fontSize: 14 }}>{title}</h3>
      <p className="sub-connect-hint">{hint}</p>

      <div className="sub-connect-inline">
        <div className="sub-connect-qr-box">
          {url ? <QR value={url} size={84} /> : null}
        </div>
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
          <div className="sub-link-row">
            <input
              readOnly
              dir="ltr"
              value={url}
              className="sub-link-input"
              style={{ flex: 1, minWidth: 0, border: "none", background: "transparent", padding: "9px 11px", outline: "none" }}
              onClick={(e) => (e.target as HTMLInputElement).select()}
            />
            <button type="button" onClick={onCopy} className={`sub-link-copy ${copied ? "ok" : ""}`}>
              {copied ? "✓" : copyLabel}
            </button>
          </div>
          {downloadHref && downloadLabel ? (
            <a href={downloadHref} download className={btnCls} style={{ textAlign: "center", textDecoration: "none" }}>
              ↓ {downloadLabel}
            </a>
          ) : null}
        </div>
      </div>
    </div>
  );
}
