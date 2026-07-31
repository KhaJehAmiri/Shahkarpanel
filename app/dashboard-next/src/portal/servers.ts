import { PortalLang, pt } from "@/lib/portal-i18n";
import type { FriendlyServer, PortalConfigs, Quality } from "./types";

const COUNTRY_HINTS_FA: Record<string, string> = {
  germany: "برای واتساپ، اینستاگرام و وب‌گردی روزمره مناسبه",
  iran: "برای دسترسی سریع داخل ایران",
  netherlands: "برای استریم و دانلود مناسبه",
  france: "گزینه پایدار برای پیام‌رسان‌ها",
  turkey: "اتصال پایدار و نزدیک",
  uk: "برای شبکه‌های اجتماعی و وب",
  "united kingdom": "برای شبکه‌های اجتماعی و وب",
  usa: "برای سرویس‌های بین‌المللی",
  "united states": "برای سرویس‌های بین‌المللی",
  finland: "گزینه پایدار اروپایی",
  sweden: "گزینه پایدار اروپایی",
  canada: "برای سرویس‌های آمریکای شمالی",
  europe: "سرور اروپایی — مناسب استفاده روزانه",
};

const COUNTRY_NAMES: Record<string, Record<PortalLang, string>> = {
  europe: { fa: "اروپا", en: "Europe", ru: "Европа", zh: "欧洲" },
  germany: { fa: "آلمان", en: "Germany", ru: "Германия", zh: "德国" },
  netherlands: { fa: "هلند", en: "Netherlands", ru: "Нидерланды", zh: "荷兰" },
  france: { fa: "فرانسه", en: "France", ru: "Франция", zh: "法国" },
  turkey: { fa: "ترکیه", en: "Turkey", ru: "Турция", zh: "土耳其" },
  uk: { fa: "انگلیس", en: "UK", ru: "Британия", zh: "英国" },
  usa: { fa: "آمریکا", en: "USA", ru: "США", zh: "美国" },
  iran: { fa: "ایران", en: "Iran", ru: "Иран", zh: "伊朗" },
  finland: { fa: "فنلاند", en: "Finland", ru: "Финляндия", zh: "芬兰" },
  sweden: { fa: "سوئد", en: "Sweden", ru: "Швеция", zh: "瑞典" },
  canada: { fa: "کانادا", en: "Canada", ru: "Канада", zh: "加拿大" },
};

export function detectCountryKey(raw: string): string | null {
  const s = raw.trim().toLowerCase();
  if (!s) return null;
  if (/europe|اروپا/.test(s)) return "europe";
  if (/germany|^de$|آلمان/.test(s)) return "germany";
  if (/netherlands|^nl$|هلند/.test(s)) return "netherlands";
  if (/france|^fr$|فرانسه/.test(s)) return "france";
  if (/turkey|^tr$|ترکیه/.test(s)) return "turkey";
  if (/united kingdom|^uk$|england|انگلیس|بریتانیا/.test(s)) return "uk";
  if (/united states|^usa$|^us$|آمریکا/.test(s)) return "usa";
  if (/iran|^ir$|ایران/.test(s)) return "iran";
  if (/finland|^fi$|فنلاند/.test(s)) return "finland";
  if (/sweden|^se$|سوئد/.test(s)) return "sweden";
  if (/canada|^ca$|کانادا/.test(s)) return "canada";
  return null;
}

export function localizeCountry(key: string | null, fallback: string, lang: PortalLang): string {
  if (key && COUNTRY_NAMES[key]) return COUNTRY_NAMES[key][lang];
  return fallback || pt(lang, "genericServer");
}

function scrubCountryRaw(raw?: string | null): string {
  let s = (raw || "").trim();
  if (!s) return "";
  s = s.split("·")[0].trim();
  s = s.replace(/\[[^\]]*\]/g, "").trim();
  s = s.replace(/\([^)]*\)/g, "").trim();
  s = s.replace(/\b(vless|vmess|trojan|wireguard|hysteria2?|tuic|anytls|xhttp|ws|tcp|grpc|reality)\b/gi, "").trim();
  s = s.replace(/[-_/]+/g, " ").replace(/\s+/g, " ").trim();
  return s;
}

export function cleanCountryName(raw?: string | null, flag?: string | null, lang: PortalLang = "fa"): string {
  const s = scrubCountryRaw(raw);
  if (!s) return flag ? "" : pt(lang, "genericServer");
  const key = detectCountryKey(s);
  return localizeCountry(key, s, lang);
}

export function countryHint(lang: PortalLang, country: string, countryKey?: string | null): string {
  const hintKey = countryKey || detectCountryKey(country) || "";
  if (lang === "fa") {
    return COUNTRY_HINTS_FA[hintKey] || "برای اتصال اینترنت روزمره مناسبه";
  }
  if (lang === "en") return "Good for everyday browsing and apps";
  if (lang === "ru") return "Подходит для повседневного использования";
  return "适合日常上网";
}

export function qualityFromLatency(ms: number | null | undefined): Quality {
  if (ms == null || Number.isNaN(ms)) return "unknown";
  if (ms < 120) return "great";
  if (ms < 250) return "ok";
  return "busy";
}

export function qualityLabel(lang: PortalLang, q: Quality): string {
  return pt(lang, `quality_${q}`);
}

export function buildFriendlyServers(configs: PortalConfigs | null): FriendlyServer[] {
  if (!configs?.config_available) return [];
  const rows: FriendlyServer[] = [];

  (configs.link_items || []).forEach((item, i) => {
    if (!item.link) return;
    const protocolRaw = item.protocol || "";
    const normalized = normalizeProtocol(protocolRaw || item.link.split("://")[0] || "");
    // Hide WireGuard Xray share links in the portal location picker.
    if (normalized === "wireguard" && (item.link.includes("fm=") || /fm%3D/i.test(item.link))) {
      return;
    }
    if (protocolRaw === "wireguard-xray" || normalized === "wireguard-xray") return;
    const scrubbed = scrubCountryRaw(item.region_name || item.remark);
    const countryKey = detectCountryKey(scrubbed);
    const country = cleanCountryName(item.region_name || item.remark, item.region_flag, "fa");
    const latency = item.latency_ms != null ? Number(item.latency_ms) : null;
    rows.push({
      key: `link-${i}`,
      flag: item.region_flag || "🌐",
      country: country || "سرور",
      countryKey,
      hint: "",
      quality: qualityFromLatency(latency),
      latencyMs: latency,
      link: item.link,
      technicalTitle: item.remark || item.region_name || item.protocol || `cfg-${i}`,
      protocolRaw: protocolRaw || normalized,
    });
  });

  (configs.wireguard_nodes || []).forEach((n) => {
    const conf = (n.conf || "").trim();
    const link = conf || (n.link || "").trim();
    if (!link) return;
    const scrubbed = scrubCountryRaw(n.region_name || n.name);
    const countryKey = detectCountryKey(scrubbed);
    const country = cleanCountryName(n.region_name || n.name, n.region_flag, "fa");
    const latency = n.latency_ms != null ? Number(n.latency_ms) : null;
    rows.push({
      key: `wg-${n.id}`,
      flag: n.region_flag || "🌐",
      country: country || n.name,
      countryKey,
      hint: "",
      quality: qualityFromLatency(latency),
      latencyMs: latency,
      link,
      conf: conf || undefined,
      technicalTitle: n.name,
      protocolRaw: n.protocol || "wireguard",
    });
  });

  (configs.singbox_nodes || []).forEach((n) => {
    if (!n.link) return;
    const scrubbed = scrubCountryRaw(n.region_name || n.name);
    const countryKey = detectCountryKey(scrubbed);
    const country = cleanCountryName(n.region_name || n.name, n.region_flag, "fa");
    const latency = n.latency_ms != null ? Number(n.latency_ms) : null;
    rows.push({
      key: `sb-${n.protocol}-${n.id}`,
      flag: n.region_flag || "🌐",
      country: country || n.name,
      countryKey,
      hint: "",
      quality: qualityFromLatency(latency),
      latencyMs: latency,
      link: n.link,
      technicalTitle: n.name,
      protocolRaw: n.protocol || "",
    });
  });

  for (const r of rows) {
    r.hint = countryHint("fa", r.country, r.countryKey);
  }

  rows.sort((a, b) => {
    const am = a.latencyMs ?? 99999;
    const bm = b.latencyMs ?? 99999;
    return am - bm;
  });
  return rows;
}

export function groupServersByCountry(
  servers: FriendlyServer[],
): { country: string; flag: string; items: FriendlyServer[] }[] {
  const map = new Map<string, FriendlyServer[]>();
  for (const s of servers) {
    const key = s.country || "سرور";
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(s);
  }
  return Array.from(map.entries()).map(([country, items]) => ({
    country,
    flag: items[0]?.flag || "🌐",
    items,
  }));
}

export function localizeServers(servers: FriendlyServer[], lang: PortalLang): FriendlyServer[] {
  return servers.map((s) => {
    const country = localizeCountry(s.countryKey, s.country, lang);
    return {
      ...s,
      country,
      hint: countryHint(lang, country, s.countryKey),
    };
  });
}

const PROTO_ALIASES: Record<string, string> = {
  wg: "wireguard",
  hy2: "hysteria2",
  hysteria: "hysteria2",
  ss: "shadowsocks",
};

export function normalizeProtocol(raw?: string | null): string {
  let p = (raw || "").trim().toLowerCase();
  if (!p) return "other";
  p = p.replace(/\s+/g, "");
  if (p === "wireguard-xray" || p === "wireguardxray" || p === "wgxray") return "wireguard-xray";
  if (PROTO_ALIASES[p]) return PROTO_ALIASES[p];
  if (p.includes("hysteria")) return "hysteria2";
  if (p.includes("wireguard") || p === "wg") return "wireguard";
  if (p.includes("shadowsocks") || p === "ss") return "shadowsocks";
  if (p.includes("vless")) return "vless";
  if (p.includes("vmess")) return "vmess";
  if (p.includes("trojan")) return "trojan";
  if (p.includes("tuic")) return "tuic";
  if (p.includes("anytls")) return "anytls";
  return p.replace(/[^a-z0-9]/g, "") || "other";
}

export function protocolLabel(lang: PortalLang, protoId: string): string {
  const key = `proto_${protoId}` as const;
  const labeled = pt(lang, key);
  if (labeled && labeled !== key) return labeled;
  return protoId.toUpperCase();
}

/** Plain WireGuard (app .conf / QR) — not share-URI protocols. */
export function isPlainWireguard(server: FriendlyServer): boolean {
  const body = (server.conf || server.link || "").trim();
  if (body.includes("[Interface]") && !body.startsWith("wireguard://")) return true;
  if (server.key.startsWith("wg-")) return true;
  return normalizeProtocol(server.protocolRaw) === "wireguard";
}

/** Payload official WireGuard apps accept (INI only — not wireguard://). */
export function wireguardImportPayload(server: FriendlyServer): string {
  const conf = (server.conf || "").trim();
  if (conf.includes("[Interface]")) return conf;
  const link = (server.link || "").trim();
  if (link.includes("[Interface]") && !link.startsWith("wireguard://")) return link;
  return "";
}

const PROTO_ORDER = [
  "vless",
  "vmess",
  "trojan",
  "shadowsocks",
  "hysteria2",
  "tuic",
  "anytls",
  "wireguard",
  "other",
];

export function groupServersByProtocol(
  servers: FriendlyServer[],
): { id: string; items: FriendlyServer[] }[] {
  const map = new Map<string, FriendlyServer[]>();
  for (const s of servers) {
    const id = normalizeProtocol(s.protocolRaw) || "other";
    if (!map.has(id)) map.set(id, []);
    map.get(id)!.push(s);
  }
  const ids = Array.from(map.keys()).sort((a, b) => {
    const ai = PROTO_ORDER.indexOf(a);
    const bi = PROTO_ORDER.indexOf(b);
    const ao = ai === -1 ? 999 : ai;
    const bo = bi === -1 ? 999 : bi;
    if (ao !== bo) return ao - bo;
    return a.localeCompare(b);
  });
  return ids.map((id) => ({ id, items: map.get(id)! }));
}
