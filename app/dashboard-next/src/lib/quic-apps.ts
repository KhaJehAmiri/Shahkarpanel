// QUIC / AnyTLS clients on Servers tab: Karing (primary) + Hiddify.

import type { Platform } from "@/lib/apps";
import { hiddifySubScheme, karingSubScheme } from "./deepLink";

export type QuicProtocol = "hysteria2" | "tuic" | "anytls";

export interface QuicClientApp {
  id: string;
  name: string;
  short: string;
  color: string;
  platforms: Platform[];
  protocols: QuicProtocol[];
  buildScheme: (
    shareUrl: string,
    opts?: {
      singboxSubUrl?: string;
      name?: string;
      ispName?: string;
      ispUrl?: string;
      ispFaq?: string;
    },
  ) => string;
  importViaSingboxSub?: boolean;
  download?: Partial<Record<Platform, string>>;
  hint?: string;
  copyFirst?: boolean;
}

const QUIC_APPS: QuicClientApp[] = [
  {
    id: "karing",
    name: "Karing",
    short: "Ka",
    color: "#2563eb",
    platforms: ["android", "ios", "windows", "macos", "linux"],
    protocols: ["hysteria2", "tuic", "anytls"],
    importViaSingboxSub: true,
    buildScheme: (_share, opts) =>
      karingSubScheme(opts?.singboxSubUrl || _share, {
        name: opts?.name,
        ispName: opts?.ispName,
        ispUrl: opts?.ispUrl,
        ispFaq: opts?.ispFaq,
      }),
    download: {
      ios: "https://apps.apple.com/app/karing/id6472431552",
      macos: "https://apps.apple.com/app/karing/id6472431552",
      android:
        "https://github.com/KaringX/karing/releases/download/v1.2.23.2606/karing_1.2.23.2606_android_arm64-v8a.apk",
      windows:
        "https://github.com/KaringX/karing/releases/download/v1.2.23.2606/karing_1.2.23.2606_windows_x64.exe",
      linux:
        "https://github.com/KaringX/karing/releases/download/v1.2.23.2606/karing_1.2.23.2606_linux_amd64.deb",
    },
    hint: "Hysteria2 · TUIC · AnyTLS",
  },
  {
    id: "hiddify",
    name: "Hiddify",
    short: "Hi",
    color: "#7c3aed",
    platforms: ["android", "ios", "windows", "macos", "linux"],
    protocols: ["hysteria2", "tuic", "anytls"],
    importViaSingboxSub: true,
    buildScheme: (_share, opts) => {
      const url = opts?.singboxSubUrl || _share;
      return hiddifySubScheme(url, opts?.name);
    },
    download: {
      android: "https://github.com/hiddify/hiddify-next/releases",
      ios: "https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532",
      windows: "https://github.com/hiddify/hiddify-next/releases",
      macos: "https://github.com/hiddify/hiddify-next/releases",
      linux: "https://github.com/hiddify/hiddify-next/releases",
    },
    hint: "sing-box sub",
    copyFirst: true,
  },
];

export function quicAppsFor(
  platform: Platform,
  protocols?: QuicProtocol[],
): QuicClientApp[] {
  const want = protocols?.length ? new Set(protocols) : null;
  return QUIC_APPS.filter((a) => {
    if (!a.platforms.includes(platform)) return false;
    if (!want) return true;
    return a.protocols.some((p) => want.has(p));
  });
}
