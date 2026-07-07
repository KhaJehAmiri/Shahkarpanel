"use client";

import { useState } from "react";
import type { ClientApp, Platform } from "@/lib/apps";
import { copyToClipboard } from "@/lib/clipboard";
import { openDeepLink } from "@/lib/deepLink";

interface Props {
  app: ClientApp;
  platform: Platform;
  subUrl: string;
  profileName?: string;
  importLabel: string;
  downloadLabel: string;
  pasteFallback: (name: string) => string;
  streisandHint: string;
  clipboardHint: string;
  noResponse: string;
  onToast: (msg: string, kind?: "ok" | "error") => void;
}

export function SubAppTile({
  app, platform, subUrl, profileName = "NexusPanel", importLabel, downloadLabel, pasteFallback, streisandHint, clipboardHint, noResponse, onToast,
}: Props) {
  const [busy, setBusy] = useState(false);
  const deepLink = app.buildScheme(subUrl, { name: profileName });
  const dl = app.download?.[platform];
  const copyFirst = platform === "macos" || platform === "ios" || app.id === "hiddify";

  async function importInApp() {
    if (!subUrl) return;
    setBusy(true);
    const finish = () => setBusy(false);

    if (app.id === "streisand" || copyFirst) {
      const ok = await copyToClipboard(subUrl);
      if (!ok) {
        onToast(noResponse, "error");
        finish();
        return;
      }
      onToast(app.id === "streisand" ? streisandHint : clipboardHint.replace("{app}", app.name), "ok");
      try {
        openDeepLink(deepLink);
        if (app.id === "clash-verge") {
          setTimeout(() => openDeepLink(`clash://install-config?url=${encodeURIComponent(subUrl)}`), 400);
        }
      } catch { /* clipboard is primary */ }
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
        const ok = await copyToClipboard(subUrl);
        onToast(ok ? pasteFallback(app.name) : noResponse, ok ? "ok" : "error");
      }
    }, 1200);
  }

  return (
    <div className="sub-app-tile">
      <div className="sub-app-icon" style={{ background: `linear-gradient(135deg, ${app.color}, #312e81)` }}>
        {app.short}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="sub-app-name">{app.name}</div>
        {dl ? (
          <a href={dl} target="_blank" rel="noopener noreferrer" className="sub-app-link">
            {downloadLabel}
          </a>
        ) : (
          <span className="sub-app-hint">{importLabel}</span>
        )}
      </div>
      <button type="button" disabled={busy || !subUrl} onClick={importInApp} className="sub-btn-primary" style={{ flexShrink: 0 }}>
        {busy ? "…" : importLabel}
      </button>
    </div>
  );
}
