"use client";

import { useState } from "react";
import type { ClientApp, Platform } from "@/lib/apps";
import { copyToClipboard } from "@/lib/clipboard";

interface Props {
  app: ClientApp;
  platform: Platform;
  subUrl: string;
  importLabel: string;
  downloadLabel: string;
  pasteFallback: (name: string) => string;
  streisandHint: string;
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

export function SubAppTile({
  app, platform, subUrl, importLabel, downloadLabel, pasteFallback, streisandHint, clipboardHint, noResponse, onToast,
}: Props) {
  const [busy, setBusy] = useState(false);
  const deepLink = app.buildScheme(subUrl, { name: "NexusPanel" });
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
      <div
        className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-lg text-[11px] font-extrabold text-white shadow-md"
        style={{ background: `linear-gradient(135deg, ${app.color}, #312e81)` }}
      >
        {app.short}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-bold text-slate-800">{app.name}</div>
        {dl ? (
          <a href={dl} target="_blank" rel="noopener noreferrer" className="text-[10px] font-semibold text-indigo-600 hover:underline">
            {downloadLabel}
          </a>
        ) : (
          <span className="text-[10px] text-slate-400">{importLabel}</span>
        )}
      </div>
      <button type="button" disabled={busy || !subUrl} onClick={importInApp} className="sub-btn-primary flex-shrink-0 disabled:opacity-50">
        {busy ? "…" : importLabel}
      </button>
    </div>
  );
}
