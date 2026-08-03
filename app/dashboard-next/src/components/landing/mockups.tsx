import Image from "next/image";
import type { ReactNode } from "react";
import { ASSETS } from "./assets";
import type { LandingCopy } from "./i18n";

export function BrowserChrome({
  children,
  url = "panel.shahkar.app",
}: {
  children: ReactNode;
  url?: string;
}) {
  return (
    <div className="tg-chrome">
      <div className="tg-chrome-bar">
        <div className="tg-chrome-dots" aria-hidden>
          <span />
          <span />
          <span />
        </div>
        <div className="tg-chrome-url">{url}</div>
      </div>
      <div className="tg-chrome-body tg-chrome-body-media">{children}</div>
    </div>
  );
}

export function DashboardMock({ priority = false }: { priority?: boolean }) {
  return (
    <BrowserChrome url="panel.shahkar.app">
      <div className="tg-media-frame">
        <Image
          src={ASSETS.heroProduct}
          alt=""
          width={1600}
          height={900}
          priority={priority}
          sizes="(max-width: 1120px) 92vw, 1120px"
          className="tg-media-img"
        />
      </div>
    </BrowserChrome>
  );
}

export function FeatureShot({
  src,
  alt,
  ratio = "4/3",
}: {
  src: string;
  alt: string;
  ratio?: "4/3" | "16/9" | "3/4";
}) {
  return (
    <div className="tg-shot">
      <div className="tg-shot-glow" aria-hidden />
      <div
        className="tg-shot-frame"
        style={{ aspectRatio: ratio.replace("/", " / ") }}
      >
        <Image
          src={src}
          alt={alt}
          width={1400}
          height={1050}
          sizes="(max-width: 768px) 92vw, 560px"
          className="tg-media-img"
        />
      </div>
    </div>
  );
}

export function ProtocolBadgeRow({ t }: { t: LandingCopy }) {
  const items = [
    { src: ASSETS.protocols.vless, label: "VLESS" },
    { src: ASSETS.protocols.xray, label: "Reality" },
    { src: ASSETS.protocols.vmess, label: "VMess" },
    { src: ASSETS.protocols.shadowsocks, label: "Shadowsocks" },
    { src: ASSETS.protocols.trojan, label: "Trojan" },
    { src: ASSETS.protocols.wireguard, label: "WireGuard" },
  ];
  return (
    <div className="tg-trust-row tg-trust-icons" aria-label={t.trust.label}>
      {items.map((item) => (
        <div className="tg-proto-badge" key={item.label}>
          <Image src={item.src} alt="" width={28} height={28} />
          <span>{item.label}</span>
        </div>
      ))}
    </div>
  );
}
