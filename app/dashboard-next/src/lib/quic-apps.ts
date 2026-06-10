// Hysteria2 / TUIC client catalog for the public subscription page.

import type { Platform } from "@/lib/apps";

export type QuicProtocol = "hysteria2" | "tuic";

export interface QuicClientApp {
  id: string;
  name: string;
  short: string;
  color: string;
  platforms: Platform[];
  protocols: QuicProtocol[];
  /** Deep-link import for a hysteria2:// or tuic:// share URL. */
  buildScheme: (shareUrl: string) => string;
  download?: Partial<Record<Platform, string>>;
  hint?: string;
  /** Copy to clipboard before opening the deep link (iOS / macOS clients). */
  copyFirst?: boolean;
}

const enc = encodeURIComponent;

const QUIC_APPS: QuicClientApp[] = [
  {
    id: "hiddify",
    name: "Hiddify",
    short: "Hi",
    color: "#7c3aed",
    platforms: ["android", "ios", "windows", "macos", "linux"],
    protocols: ["hysteria2", "tuic"],
    buildScheme: (url) => `hiddify://import/${enc(url)}`,
    download: {
      android: "https://github.com/hiddify/hiddify-next/releases",
      ios: "https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532",
      windows: "https://github.com/hiddify/hiddify-next/releases",
      macos: "https://github.com/hiddify/hiddify-next/releases",
      linux: "https://github.com/hiddify/hiddify-next/releases",
    },
    hint: "Hysteria2 + TUIC",
    copyFirst: true,
  },
  {
    id: "v2rayng",
    name: "v2rayNG",
    short: "V2",
    color: "#1f6feb",
    platforms: ["android"],
    protocols: ["hysteria2", "tuic"],
    buildScheme: (url) => `v2rayng://install-config?url=${enc(url)}`,
    download: { android: "https://github.com/2dust/v2rayNG/releases" },
    hint: "Paste hysteria2:// link if import fails",
  },
  {
    id: "nekobox",
    name: "NekoBox",
    short: "NB",
    color: "#ec4899",
    platforms: ["android"],
    protocols: ["hysteria2", "tuic"],
    buildScheme: (url) => `sn://import?url=${enc(url)}`,
    download: { android: "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases" },
    hint: "sing-box based",
  },
  {
    id: "hysteria-official",
    name: "Hysteria2",
    short: "H2",
    color: "#f59e0b",
    platforms: ["windows", "macos", "linux"],
    protocols: ["hysteria2"],
    buildScheme: (url) => url,
    download: {
      windows: "https://github.com/apernet/hysteria/releases",
      macos: "https://github.com/apernet/hysteria/releases",
      linux: "https://github.com/apernet/hysteria/releases",
    },
    hint: "Official client — paste share link",
    copyFirst: true,
  },
  {
    id: "v2rayn",
    name: "v2rayN",
    short: "VN",
    color: "#2563eb",
    platforms: ["windows"],
    protocols: ["hysteria2", "tuic"],
    buildScheme: (url) => url,
    download: { windows: "https://github.com/2dust/v2rayN/releases" },
    hint: "Servers → Import from clipboard",
    copyFirst: true,
  },
  {
    id: "nekoray",
    name: "NekoRay",
    short: "NR",
    color: "#db2777",
    platforms: ["windows", "macos", "linux"],
    protocols: ["hysteria2", "tuic"],
    buildScheme: (url) => url,
    download: {
      windows: "https://github.com/MatsuriDayo/nekoray/releases",
      macos: "https://github.com/MatsuriDayo/nekoray/releases",
      linux: "https://github.com/MatsuriDayo/nekoray/releases",
    },
    hint: "sing-box / hysteria2",
    copyFirst: true,
  },
  {
    id: "streisand",
    name: "Streisand",
    short: "St",
    color: "#0ea5e9",
    platforms: ["ios", "macos"],
    protocols: ["hysteria2", "tuic"],
    buildScheme: (url) => `streisand://import/${enc(url)}`,
    download: {
      ios: "https://apps.apple.com/app/streisand/id6450534064",
      macos: "https://apps.apple.com/app/streisand/id6450534064",
    },
    hint: "Import from clipboard",
    copyFirst: true,
  },
  {
    id: "shadowrocket",
    name: "Shadowrocket",
    short: "SR",
    color: "#6366f1",
    platforms: ["ios", "macos"],
    protocols: ["hysteria2", "tuic"],
    buildScheme: (url) => `shadowrocket://add/${enc(url)}`,
    download: { ios: "https://apps.apple.com/app/shadowrocket/id932747118" },
    hint: "Paste hysteria2:// link",
    copyFirst: true,
  },
  {
    id: "sing-box",
    name: "sing-box",
    short: "SB",
    color: "#14b8a6",
    platforms: ["android", "windows", "macos", "linux"],
    protocols: ["hysteria2", "tuic"],
    buildScheme: (url) => url,
    download: {
      android: "https://github.com/SagerNet/sing-box/releases",
      windows: "https://github.com/SagerNet/sing-box/releases",
      macos: "https://github.com/SagerNet/sing-box/releases",
      linux: "https://github.com/SagerNet/sing-box/releases",
    },
    hint: "Import profile from clipboard",
    copyFirst: true,
  },
];

export function quicAppsFor(
  platform: Platform,
  protocols: QuicProtocol[],
): QuicClientApp[] {
  const want = new Set(protocols);
  return QUIC_APPS.filter(
    (a) => a.platforms.includes(platform) && a.protocols.some((p) => want.has(p)),
  );
}
