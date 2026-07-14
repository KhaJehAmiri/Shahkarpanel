"use client";

import { useState } from "react";
import { QR } from "@/components/QR";

interface Props {
  title: string;
  hint: string;
  url: string;
  /** QR payload — defaults to ``url``. Use raw .conf text for WireGuard plain import. */
  qrValue?: string;
  /** Input field text — defaults to ``url``. */
  displayValue?: string;
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
  /** ``stacked`` = large isolated QR per card (WireGuard). ``inline`` = compact side-by-side. */
  qrLayout?: "inline" | "stacked";
  qrEnlargeLabel?: string;
  closeLabel?: string;
}

export function ConnectCard({
  title,
  hint,
  url,
  qrValue,
  displayValue,
  copyLabel,
  copied,
  onCopy,
  accent,
  downloadHref,
  downloadLabel,
  paused,
  pausedHint,
  embedded,
  qrLayout = "inline",
  qrEnlargeLabel = "Tap to enlarge",
  closeLabel = "Close",
}: Props) {
  const [showQr, setShowQr] = useState(false);
  const accentCls = accent === "rose" ? "sub-card-accent-rose" : "sub-card-accent-indigo";
  const btnCls = accent === "rose" ? "sub-btn-primary sub-btn-rose" : "sub-btn-primary";
  const qrPayload = qrValue ?? url;
  const fieldValue = displayValue ?? url;
  const stacked = qrLayout === "stacked";
  const wrap = stacked
    ? `sub-card sub-connect-stacked ${accentCls}`
    : embedded
      ? "sub-connect-embedded"
      : `sub-card sub-connect-compact ${accentCls}`;

  if (paused) {
    return (
      <div className={stacked ? `sub-card sub-connect-stacked ${accentCls}` : embedded ? "sub-connect-embedded" : `sub-card ${accentCls}`} style={{ padding: 16 }}>
        <h3 className="sub-mobile-title sub-heading" style={{ fontSize: 14 }}>{title}</h3>
        <p className="sub-text-muted" style={{ marginTop: 8, fontSize: 13 }}>{pausedHint}</p>
      </div>
    );
  }

  const actions = (
    <div className="sub-connect-actions">
      <div className="sub-link-row">
        <input
          readOnly
          dir="ltr"
          value={fieldValue}
          className="sub-link-input"
          style={{ flex: 1, minWidth: 0, border: "none", background: "transparent", padding: "9px 11px", outline: "none" }}
          onClick={(e) => (e.target as HTMLInputElement).select()}
        />
        <button type="button" onClick={onCopy} className={`sub-link-copy ${copied ? "ok" : ""}`}>
          {copied ? "✓" : copyLabel}
        </button>
      </div>
      {downloadHref && downloadLabel ? (
        <a href={downloadHref} download className={btnCls} style={{ textAlign: "center", textDecoration: "none", width: "100%" }}>
          {downloadLabel}
        </a>
      ) : null}
    </div>
  );

  const qrModal = showQr && qrPayload ? (
    <div className="sub-qr-modal" onClick={() => setShowQr(false)} role="dialog" aria-modal="true">
      <div className="sub-qr-modal-inner sub-qr-modal-large" onClick={(e) => e.stopPropagation()}>
        <p className="sub-qr-modal-title">{title}</p>
        <div className="sub-connect-qr-box sub-connect-qr-box-lg">
          <QR value={qrPayload} size={280} />
        </div>
        <button type="button" onClick={() => setShowQr(false)} className="sub-btn-primary" style={{ marginTop: 14, width: "100%" }}>
          {closeLabel}
        </button>
      </div>
    </div>
  ) : null;

  if (stacked) {
    return (
      <>
        <div className={wrap}>
          <h3 className="sub-mobile-title sub-heading sub-connect-stacked-title">{title}</h3>
          <p className="sub-connect-hint">{hint}</p>
          {qrPayload ? (
            <button type="button" className="sub-connect-qr-stage" onClick={() => setShowQr(true)} aria-label={qrEnlargeLabel}>
              <div className="sub-connect-qr-box sub-connect-qr-box-lg">
                <QR value={qrPayload} size={220} />
              </div>
              <span className="sub-connect-qr-tap-hint">{qrEnlargeLabel}</span>
            </button>
          ) : null}
          {actions}
        </div>
        {qrModal}
      </>
    );
  }

  return (
    <>
      <div className={wrap} style={{ padding: embedded ? 0 : 14 }}>
        <h3 className="sub-mobile-title sub-heading" style={{ fontSize: 14 }}>{title}</h3>
        <p className="sub-connect-hint">{hint}</p>
        <div className="sub-connect-inline">
          <div className="sub-connect-qr-box">
            {qrPayload ? <QR value={qrPayload} size={84} /> : null}
          </div>
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
            {actions}
          </div>
        </div>
      </div>
      {qrModal}
    </>
  );
}
