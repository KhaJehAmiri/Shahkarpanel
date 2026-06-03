"use client";

import { useState } from "react";
import type { ClientApp, Platform } from "@/lib/apps";
import { copyToClipboard } from "@/lib/clipboard";

interface Props {
  app: ClientApp;
  platform: Platform;
  subUrl: string;
  profileName?: string;
  onToast: (msg: string, kind?: "ok" | "error") => void;
}

export function AppTile({ app, platform, subUrl, profileName, onToast }: Props) {
  const [busy, setBusy] = useState(false);
  const deepLink = app.buildScheme(subUrl, { name: profileName });
  const dl = app.download?.[platform];

  async function importInApp() {
    if (!subUrl) return;
    setBusy(true);
    let blurred = false;
    const onBlur = () => {
      blurred = true;
    };
    window.addEventListener("blur", onBlur, { once: true });
    const start = Date.now();
    try {
      // We use an anchor click rather than location assignment because some
      // browsers (esp. iOS Safari) handle custom URL schemes more reliably
      // when triggered from a synchronous user gesture.
      const a = document.createElement("a");
      a.href = deepLink;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch {
      /* ignore */
    }
    setTimeout(async () => {
      window.removeEventListener("blur", onBlur);
      setBusy(false);
      if (!blurred && Date.now() - start < 1500) {
        const ok = await copyToClipboard(subUrl);
        onToast(
          ok
            ? `اگر ${app.name} نصب نیست، لینک کپی شد — در اپ پیست کنید.`
            : "اپ پاسخ نداد",
          ok ? "ok" : "error",
        );
      }
    }, 1200);
  }

  return (
    <div className="group flex items-center gap-3 rounded-md border border-border bg-surface px-3 py-3 transition hover:border-accent hover:bg-accent-soft">
      <div
        className="grid h-11 w-11 flex-shrink-0 place-items-center rounded-md text-base font-bold text-white"
        style={{ background: app.color }}
        aria-hidden
      >
        {app.short}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold leading-tight">{app.name}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-text-faint">
          {dl && (
            <a
              href={dl}
              target="_blank"
              rel="noopener noreferrer"
              className="underline decoration-dotted underline-offset-2 hover:text-accent"
            >
              دانلود اپ
            </a>
          )}
          <span className="opacity-60">·</span>
          <span>ایمپورت مستقیم</span>
        </div>
      </div>
      <button
        type="button"
        disabled={busy || !subUrl}
        onClick={importInApp}
        className="flex-shrink-0 rounded-md bg-accent px-3.5 py-2 text-xs font-bold text-bg transition hover:opacity-90 disabled:opacity-50"
      >
        {busy ? "…" : "ایمپورت"}
      </button>
    </div>
  );
}
