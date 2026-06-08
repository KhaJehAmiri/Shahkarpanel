// WireGuard client catalog — separate from proxy/V2Ray apps (no shared deep links).

import type { Platform } from "@/lib/apps";

export interface WgClientApp {
  id: string;
  name: string;
  short: string;
  color: string;
  platforms: Platform[];
  download?: Partial<Record<Platform, string>>;
  hint?: string;
}

const WG_APPS: WgClientApp[] = [
  {
    id: "wireguard",
    name: "WireGuard",
    short: "WG",
    color: "#88171a",
    platforms: ["android", "ios", "windows", "macos", "linux"],
    download: {
      android: "https://play.google.com/store/apps/details?id=com.wireguard.android",
      ios: "https://apps.apple.com/app/wireguard/id1441195209",
      windows: "https://www.wireguard.com/install/",
      macos: "https://apps.apple.com/app/wireguard/id1451685025",
      linux: "https://www.wireguard.com/install/",
    },
    hint: "Import tunnel from file or scan QR",
  },
  {
    id: "amneziawg",
    name: "AmneziaWG",
    short: "AW",
    color: "#2563eb",
    platforms: ["android", "ios", "windows", "macos", "linux"],
    download: {
      android: "https://play.google.com/store/apps/details?id=org.amnezia.vpn",
      ios: "https://apps.apple.com/app/amneziavpn/id1600529900",
      windows: "https://amnezia.org/en/downloads",
      macos: "https://amnezia.org/en/downloads",
      linux: "https://amnezia.org/en/downloads",
    },
    hint: "Obfuscated WireGuard — import the same .conf (Jc/Jmin/S1/S2/H1–H4 supported)",
  },
  {
    id: "wireguard-android",
    name: "WireGuard (Android)",
    short: "WA",
    color: "#b91c1c",
    platforms: ["android"],
    download: {
      android: "https://play.google.com/store/apps/details?id=com.wireguard.android",
    },
  },
  {
    id: "wiresock",
    name: "WireSock",
    short: "WS",
    color: "#0f766e",
    platforms: ["windows"],
    download: {
      windows: "https://www.wiresock.net/",
    },
    hint: "Windows WireGuard client",
  },
  {
    id: "wireguard-apple",
    name: "WireGuard (App Store)",
    short: "W+",
    color: "#dc2626",
    platforms: ["ios", "macos"],
    download: {
      ios: "https://apps.apple.com/app/wireguard/id1441195209",
      macos: "https://apps.apple.com/app/wireguard/id1451685025",
    },
  },
];

export function wgAppsFor(platform: Platform): WgClientApp[] {
  return WG_APPS.filter((a) => a.platforms.includes(platform));
}
