"use client";

import { useState } from "react";
import type { Platform } from "@/lib/apps";
import type { QuicClientApp } from "@/lib/quic-apps";
import { copyToClipboard } from "@/lib/clipboard";

interface Props {
  app: QuicClientApp;
  platform: Platform;
  shareUrl: string;
  importLabel: string;
  downloadLabel: string;
  pasteFallback: (name: string) => string;
  clipboardHint: string;
  noResponse: string;
  onToast: (msg: string, kind?: "ok" | "error") => void;
}

function openDeepLink(href: string) {
  const a = document.createElement("a");
  a.href = href;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

export function SubQuicAppTile({
  app,
  platform,
  shareUrl,
  importLabel,
  downloadLabel,
  pasteFallback,
  clipboardHint,
  noResponse,
  onToast,
}: Props) {
  const [busy, setBusy] = useState(false);
  const deepLink = app.buildScheme(shareUrl);
  const dl = app.download?.[platform];

  async function importInApp() {
    if (!shareUrl) return;
    setBusy(true);
    const finish = () => setBusy(false);

    if (app.copyFirst) {
      const ok = await copyToClipboard(shareUrl);
      if (!ok) {
        onToast(noResponse, "error");
        finish();
        return;
      }
      onToast(clipboardHint.replace("{app}", app.name), "ok");
      if (deepLink !== shareUrl) {
        try {
          openDeepLink(deepLink);
        } catch { /* clipboard is primary */ }
      }
      setTimeout(finish, 600);
      return;
    }

    let blurred = false;
    const onBlur = () => { blurred = true; };
    window.addEventListener("blur", onBlur, { once: true });
    const start = Date.now();
    try {
      openDeepLink(deepLink);
    } catch { /* ignore */ }
    setTimeout(async () => {
      window.removeEventListener("blur", onBlur);
      finish();
      if (!blurred && Date.now() - start < 1500) {
        const ok = await copyToClipboard(shareUrl);
        onToast(ok ? pasteFallback(app.name) : noResponse, ok ? "ok" : "error");
      }
    }, 1200);
  }

  return (
    <div className="sub-app-tile">
      <div className="sub-app-icon" style={{ background: `linear-gradient(135deg, ${app.color}, #5b21b6)` }}>
        {app.short}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="sub-app-name">{app.name}</div>
        {dl ? (
          <a href={dl} target="_blank" rel="noopener noreferrer" className="sub-app-link" style={{ color: "#c4b5fd" }}>
            {downloadLabel}
          </a>
        ) : (
          <span className="sub-app-hint">{app.hint || "QUIC"}</span>
        )}
      </div>
      <button
        type="button"
        disabled={busy || !shareUrl}
        onClick={importInApp}
        className="sub-btn-primary"
        style={{ flexShrink: 0 }}
      >
        {busy ? "…" : importLabel}
      </button>
    </div>
  );
}
