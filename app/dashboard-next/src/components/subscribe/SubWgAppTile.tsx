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
      <div className="sub-app-icon" style={{ background: `linear-gradient(145deg, ${app.color}, #9a3412)` }}>
        {app.short}
      </div>
      <div className="sub-app-meta">
        <div className="sub-app-name">{app.name}</div>
        {app.hint ? <div className="sub-app-hint">{app.hint}</div> : null}
        {dl ? (
          <div className="sub-app-actions">
            <a href={dl} target="_blank" rel="noopener noreferrer" className="sub-btn-action sub-btn-action-main">
              {downloadLabel}
            </a>
          </div>
        ) : null}
      </div>
    </div>
  );
}
