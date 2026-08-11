// Client-app catalog for the public subscription page.
// Primary (all platforms): Karing — https://karing.app/en/cooperation/scheme
// Servers page also offers Hiddify, V2Box, Happ.

import {
  happSubScheme,
  hiddifySubScheme,
  karingSubScheme,
  v2boxSubScheme,
} from "./deepLink";

export type Platform = "android" | "ios" | "windows" | "macos" | "linux";

export interface PlatformInfo {
  id: Platform;
  label: string;
}

export const PLATFORMS: PlatformInfo[] = [
  { id: "android", label: "Android" },
  { id: "ios", label: "iOS" },
  { id: "windows", label: "Windows" },
  { id: "macos", label: "macOS" },
  { id: "linux", label: "Linux" },
];

export interface ClientApp {
  id: string;
  name: string;
  short: string;
  color: string;
  platforms: Platform[];
  buildScheme: (
    subUrl: string,
    opts?: { name?: string; ispName?: string; ispUrl?: string; ispFaq?: string },
  ) => string;
  download?: Partial<Record<Platform, string>>;
}

/** Shown under the primary app on the Servers tab (not on Import). */
export const SERVER_SECONDARY_APP_IDS = ["hiddify", "v2box", "happ"] as const;

const KARING_DOWNLOAD = {
  ios: "https://apps.apple.com/app/karing/id6472431552",
  macos: "https://apps.apple.com/app/karing/id6472431552",
  // Direct APK (arm64) — not the GitHub releases HTML page.
  android:
    "https://github.com/KaringX/karing/releases/download/v1.2.23.2606/karing_1.2.23.2606_android_arm64-v8a.apk",
  windows:
    "https://github.com/KaringX/karing/releases/download/v1.2.23.2606/karing_1.2.23.2606_windows_x64.exe",
  linux:
    "https://github.com/KaringX/karing/releases/download/v1.2.23.2606/karing_1.2.23.2606_linux_amd64.deb",
} as const;

const APPS: ClientApp[] = [
  {
    id: "karing",
    name: "Karing",
    short: "Ka",
    color: "#2563eb",
    platforms: ["android", "ios", "windows", "macos", "linux"],
    buildScheme: (url, o) =>
      karingSubScheme(url, {
        name: o?.name,
        ispName: o?.ispName,
        ispUrl: o?.ispUrl,
        ispFaq: o?.ispFaq,
      }),
    download: { ...KARING_DOWNLOAD },
  },
  {
    id: "hiddify",
    name: "Hiddify",
    short: "Hi",
    color: "#7c3aed",
    platforms: ["android", "ios", "windows", "macos", "linux"],
    buildScheme: (url, o) => hiddifySubScheme(url, o?.name),
    download: {
      android: "https://github.com/hiddify/hiddify-next/releases",
      ios: "https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532",
      windows: "https://github.com/hiddify/hiddify-next/releases",
      macos: "https://github.com/hiddify/hiddify-next/releases",
      linux: "https://github.com/hiddify/hiddify-next/releases",
    },
  },
  {
    id: "v2box",
    name: "V2Box",
    short: "VB",
    color: "#10b981",
    platforms: ["ios", "macos"],
    buildScheme: (url, o) => v2boxSubScheme(url, o?.name),
    download: {
      ios: "https://apps.apple.com/app/v2box-v2ray-client/id6446814690",
      macos: "https://apps.apple.com/app/v2box-v2ray-client/id6446814690",
    },
  },
  {
    id: "happ",
    name: "Happ",
    short: "Hp",
    color: "#f59e0b",
    platforms: ["android", "ios", "windows", "macos", "linux"],
    // Official: happ://add/<plain-url> — do NOT urlencode or base64 the URL.
    buildScheme: (url) => happSubScheme(url),
    download: {
      android: "https://github.com/Happ-proxy/happ-android/releases/latest/download/Happ.apk",
      ios: "https://apps.apple.com/app/happ-proxy-utility/id6504287215",
      macos: "https://apps.apple.com/app/happ-proxy-utility/id6504287215",
      windows: "https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe",
      linux: "https://github.com/Happ-proxy/happ-desktop/releases/latest",
    },
  },
];

export function appsFor(platform: Platform): ClientApp[] {
  return APPS.filter((a) => a.platforms.includes(platform));
}

/** Secondary clients for the Servers tab (Hiddify / V2Box / Happ). */
export function serverSecondaryApps(platform: Platform): ClientApp[] {
  const order = SERVER_SECONDARY_APP_IDS as readonly string[];
  return appsFor(platform)
    .filter((a) => a.id !== "karing" && order.includes(a.id))
    .sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
}

export function detectPlatform(ua: string): Platform {
  const s = (ua || "").toLowerCase();
  if (/iphone|ipad|ipod/.test(s)) return "ios";
  if (/android/.test(s)) return "android";
  if (/windows|win32|win64/.test(s)) return "windows";
  if (/mac os x|macintosh/.test(s)) return "macos";
  if (/linux|x11/.test(s)) return "linux";
  return "android";
}
