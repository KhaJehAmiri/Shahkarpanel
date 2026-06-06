"use client";

import type { Platform } from "@/lib/apps";
import type { WgClientApp } from "@/lib/wg-apps";

interface Props {
  app: WgClientApp;
  platform: Platform;
  downloadLabel: string;
}

export function SubWgAppTile({ app, platform, downloadLabel }: Props) {
  const dl = app.download?.[platform];
  return (
    <div className="sub-app-tile">
      <div
        className="grid h-8 w-8 flex-shrink-0 place-items-center rounded-lg text-[10px] font-extrabold text-white shadow-md"
        style={{ background: `linear-gradient(135deg, ${app.color}, #881337)` }}
      >
        {app.short}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-bold text-slate-800">{app.name}</div>
        <div className="text-[10px] text-slate-400">{app.hint || "WireGuard"}</div>
      </div>
      {dl ? (
        <a href={dl} target="_blank" rel="noopener noreferrer" className="sub-btn-primary sub-btn-rose flex-shrink-0 !py-1.5 !px-3 !text-[11px]">
          {downloadLabel}
        </a>
      ) : null}
    </div>
  );
}
