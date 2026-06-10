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
      <div className="sub-app-icon" style={{ background: `linear-gradient(135deg, ${app.color}, #881337)` }}>
        {app.short}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="sub-app-name">{app.name}</div>
        <div className="sub-app-hint">{app.hint || "WireGuard"}</div>
      </div>
      {dl ? (
        <a href={dl} target="_blank" rel="noopener noreferrer" className="sub-btn-primary sub-btn-rose" style={{ flexShrink: 0, textDecoration: "none" }}>
          {downloadLabel}
        </a>
      ) : null}
    </div>
  );
}
