"use client";

import type { Platform } from "@/lib/apps";
import type { WgClientApp } from "@/lib/wg-apps";

interface Props {
  app: WgClientApp;
  platform: Platform;
  downloadLabel: string;
  installHint: string;
}

export function WgAppTile({ app, platform, downloadLabel, installHint }: Props) {
  const dl = app.download?.[platform];

  return (
    <div className="group flex items-center gap-3 rounded-xl border border-border/80 bg-surface/80 px-3 py-3 backdrop-blur-sm transition hover:border-[#f87171]/40 hover:bg-[#f87171]/5">
      <div
        className="grid h-11 w-11 flex-shrink-0 place-items-center rounded-lg text-base font-bold text-white shadow-lg"
        style={{ background: `linear-gradient(135deg, ${app.color}, #1a1a2e)` }}
        aria-hidden
      >
        {app.short}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold leading-tight">{app.name}</div>
        <div className="mt-0.5 text-[11px] leading-relaxed text-text-faint">
          {app.hint || installHint}
        </div>
      </div>
      {dl ? (
        <a
          href={dl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex-shrink-0 rounded-lg border border-[#f87171]/30 bg-[#f87171]/10 px-3.5 py-2 text-xs font-bold text-[#fca5a5] transition hover:bg-[#f87171]/20"
        >
          {downloadLabel}
        </a>
      ) : null}
    </div>
  );
}
