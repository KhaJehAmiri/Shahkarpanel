// Client-app catalog for the public subscription page. Each app exposes a
// deep-link builder (custom URL scheme) so users can one-tap import their
// subscription URL, plus per-platform store/download links.

export type Platform = "android" | "ios" | "windows" | "macos" | "linux";

export interface PlatformInfo {
  id: Platform;
  label: string;
}

export const PLATFORMS: PlatformInfo[] = [
  { id: "android", label: "اندروید" },
  { id: "ios", label: "iOS" },
  { id: "windows", label: "ویندوز" },
  { id: "macos", label: "مک" },
  { id: "linux", label: "لینوکس" },
];

export interface ClientApp {
  id: string;
  name: string;
  short: string;
  color: string;
  platforms: Platform[];
  buildScheme: (subUrl: string, opts?: { name?: string }) => string;
  download?: Partial<Record<Platform, string>>;
}

const enc = encodeURIComponent;
const b64 = (s: string): string =>
  typeof btoa !== "undefined" ? btoa(s) : Buffer.from(s, "utf-8").toString("base64");

const APPS: ClientApp[] = [
  {
    id: "v2rayng",
    name: "v2rayNG",
    short: "V2",
    color: "#1f6feb",
    platforms: ["android"],
    buildScheme: (url) => `v2rayng://install-sub?url=${enc(url)}`,
    download: { android: "https://github.com/2dust/v2rayNG/releases" },
  },
  {
    id: "nekobox",
    name: "NekoBox",
    short: "NB",
    color: "#ec4899",
    platforms: ["android"],
    buildScheme: (url) => `sn://subscription?url=${enc(url)}`,
    download: { android: "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases" },
  },
  {
    id: "hiddify",
    name: "Hiddify",
    short: "Hi",
    color: "#7c3aed",
    platforms: ["android", "ios", "windows", "macos", "linux"],
    buildScheme: (url, o) => `hiddify://import/${url}${o?.name ? `#${enc(o.name)}` : ""}`,
    download: {
      android: "https://github.com/hiddify/hiddify-next/releases",
      ios: "https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532",
      windows: "https://github.com/hiddify/hiddify-next/releases",
      macos: "https://github.com/hiddify/hiddify-next/releases",
      linux: "https://github.com/hiddify/hiddify-next/releases",
    },
  },
  {
    id: "streisand",
    name: "Streisand",
    short: "St",
    color: "#0ea5e9",
    platforms: ["ios", "macos"],
    buildScheme: (url) => `streisand://import/${url}`,
    download: { ios: "https://apps.apple.com/app/streisand/id6450534064" },
  },
  {
    id: "shadowrocket",
    name: "Shadowrocket",
    short: "SR",
    color: "#6366f1",
    platforms: ["ios", "macos"],
    buildScheme: (url) => `sub://${b64(url)}`,
    download: { ios: "https://apps.apple.com/app/shadowrocket/id932747118" },
  },
  {
    id: "v2box",
    name: "V2Box",
    short: "VB",
    color: "#10b981",
    platforms: ["ios", "macos"],
    buildScheme: (url, o) => `v2box://install-sub?url=${enc(url)}${o?.name ? `&name=${enc(o.name)}` : ""}`,
    download: { ios: "https://apps.apple.com/app/v2box-v2ray-client/id6446814690" },
  },
  {
    id: "v2rayn",
    name: "v2rayN",
    short: "VN",
    color: "#2563eb",
    platforms: ["windows"],
    buildScheme: (url) => url,
    download: { windows: "https://github.com/2dust/v2rayN/releases" },
  },
  {
    id: "clash-verge",
    name: "Clash Verge",
    short: "CV",
    color: "#0891b2",
    platforms: ["windows", "macos", "linux"],
    buildScheme: (url) => `clash://install-config?url=${enc(url)}`,
    download: { windows: "https://github.com/clash-verge-rev/clash-verge-rev/releases", macos: "https://github.com/clash-verge-rev/clash-verge-rev/releases", linux: "https://github.com/clash-verge-rev/clash-verge-rev/releases" },
  },
];

export function appsFor(platform: Platform): ClientApp[] {
  return APPS.filter((a) => a.platforms.includes(platform));
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
