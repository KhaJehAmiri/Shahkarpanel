"use client";

import { useState } from "react";
import type { Platform } from "@/lib/apps";
import type { QuicClientApp } from "@/lib/quic-apps";
import { copyToClipboard } from "@/lib/clipboard";
import { openDeepLink } from "@/lib/deepLink";

interface Props {
  app: QuicClientApp;
  platform: Platform;
  shareUrl: string;
  singboxSubUrl: string;
  importLabel: string;
  downloadLabel: string;
  pasteFallback: (name: string) => string;
  clipboardHint: string;
  noResponse: string;
  onToast: (msg: string, kind?: "ok" | "error") => void;
}

export function SubQuicAppTile({
  app,
  platform,
  shareUrl,
  singboxSubUrl,
  importLabel,
  downloadLabel,
  pasteFallback,
  clipboardHint,
  noResponse,
  onToast,
}: Props) {
  const [busy, setBusy] = useState(false);
  const importUrl = app.importViaSingboxSub && singboxSubUrl ? singboxSubUrl : shareUrl;
  const deepLink = app.buildScheme(shareUrl, { singboxSubUrl });
  const dl = app.download?.[platform];

  async function importInApp() {
    if (!importUrl) return;
    setBusy(true);
    const finish = () => setBusy(false);

    if (app.copyFirst) {
      const ok = await copyToClipboard(importUrl);
      if (!ok) {
        onToast(noResponse, "error");
        finish();
        return;
      }
      onToast(clipboardHint.replace("{app}", app.name), "ok");
      if (deepLink !== importUrl) {
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
        const ok = await copyToClipboard(importUrl);
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
        disabled={busy || !importUrl}
        onClick={importInApp}
        className="sub-btn-primary"
        style={{ flexShrink: 0 }}
      >
        {busy ? "…" : importLabel}
      </button>
    </div>
  );
}
