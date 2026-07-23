"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Smartphone,
} from "lucide-react";
import { SubAppTile } from "@/components/subscribe/SubAppTile";
import { SubWgAppTile } from "@/components/subscribe/SubWgAppTile";
import { QR } from "@/components/QR";
import { PLATFORMS, type Platform, type ClientApp, appsFor, detectPlatform } from "@/lib/apps";
import { wgAppsFor } from "@/lib/wg-apps";
import { copyToClipboard } from "@/lib/clipboard";
import { bytes, formatDate, relativeDays } from "@/lib/format";
import { SUB_LANGS, SubLang, detectSubLang, rememberSubLang, t as subT } from "@/lib/subscribe-i18n";
import { resolveClientImportUrl, resolvePublicSubUrl, resolveWgUrl } from "@/lib/subscribe-url";
import { applySubTheme, detectSubTheme, type SubTheme } from "@/lib/sub-theme";
import { openDeepLink } from "@/lib/deepLink";

interface LinkItem {
  link: string;
  protocol: string;
  remark: string;
  region_flag?: string;
  region_name?: string;
  address_hint?: string;
  latency_ms?: number | null;
}

interface SubInfo {
  username: string;
  status: string;
  used_traffic: number;
  overage_traffic?: number;
  data_limit: number | null;
  expire: number | null;
  online_at?: string | null;
  online?: boolean;
  online_devices?: number;
  device_limit?: number | null;
  links?: string[];
  link_items?: LinkItem[];
  proxies?: Record<string, unknown>;
  config_available?: boolean;
  block_reason?: string | null;
  public_subscription_url?: string;
  client_subscription_url?: string;
  subscription_profile_title?: string;
  branding?: {
    panel_title?: string | null;
    logo_url?: string | null;
    favicon_url?: string | null;
    primary_color?: string | null;
    support_url?: string | null;
    sub_profile_title?: string | null;
  } | null;
  hysteria2_link?: string | null;
  tuic_link?: string | null;
  anytls_link?: string | null;
  wireguard_uri?: string | null;
  wireguard_variant?: "plain" | "awg" | "xray_native" | null;
  wireguard_plain_uri?: string | null;
  wireguard_xray_uri?: string | null;
  wireguard_nodes?: Array<{
    id: number;
    name: string;
    address: string;
    region_flag?: string | null;
    region_name?: string | null;
    latency_ms?: number | null;
    wireguard_uri?: string | null;
    wireguard_variant?: "plain" | "awg" | "xray_native" | null;
    wireguard_plain_uri?: string | null;
    wireguard_xray_uri?: string | null;
    plain_available?: boolean;
    xray_available?: boolean;
  }>;
  singbox_nodes?: Array<{
    id: number;
    name: string;
    region_flag?: string | null;
    region_name?: string | null;
    latency_ms?: number | null;
    hysteria2_link?: string | null;
    tuic_link?: string | null;
    anytls_link?: string | null;
    hysteria2_available?: boolean;
    tuic_available?: boolean;
    anytls_available?: boolean;
  }>;
}

type ConfigEntry = {
  id: string;
  protocol: string;
  title: string;
  flag?: string;
  value: string;
  downloadHref?: string;
  latencyMs?: number | null;
};

type RegionBucket = "europe" | "asia" | "americas" | "middleEast" | "other";

const REGION_KEYWORDS: Record<RegionBucket, string[]> = {
  europe: [
    "germany", "france", "netherlands", "uk", "united kingdom", "england", "finland", "sweden",
    "norway", "poland", "spain", "italy", "austria", "switzerland", "belgium", "czech", "romania",
    "bulgaria", "hungary", "portugal", "ireland", "greece", "denmark", "ukraine", "latvia",
    "lithuania", "estonia", "slovakia", "croatia", "serbia", " آلمان", "فرانسه", "هلند", "انگلیس",
  ],
  asia: [
    "japan", "singapore", "korea", "hong kong", "taiwan", "india", "thailand", "vietnam",
    "malaysia", "indonesia", "philippines", "china", "ژاپن", "سنگاپور", "کره", "هند",
  ],
  americas: [
    "usa", "united states", "america", "canada", "brazil", "mexico", "argentina", "chile",
    "colombia", "آمریکا", "کانادا", "برزیل",
  ],
  middleEast: [
    "iran", "turkey", "uae", "dubai", "israel", "qatar", "bahrain", "saudi", "iraq", "kuwait",
    "ایران", "ترکیه", "امارات",
  ],
  other: [],
};

function regionBucket(title: string): RegionBucket {
  const t = (title || "").toLowerCase();
  for (const key of ["middleEast", "europe", "asia", "americas"] as RegionBucket[]) {
    if (REGION_KEYWORDS[key].some((k) => t.includes(k))) return key;
  }
  return "other";
}

function regionBucketLabel(lang: SubLang, bucket: RegionBucket): string {
  const map: Record<RegionBucket, string> = {
    europe: "regionEurope",
    asia: "regionAsia",
    americas: "regionAmericas",
    middleEast: "regionMiddleEast",
    other: "regionOther",
  };
  return subT(lang, map[bucket]);
}

function latencyTone(ms: number | null | undefined): "ok" | "warn" | "danger" | "unknown" {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "unknown";
  if (ms < 80) return "ok";
  if (ms < 180) return "warn";
  return "danger";
}

function getToken(): string {
  if (typeof window === "undefined") return "";
  const q = new URLSearchParams(window.location.search).get("token");
  if (q) return q;
  const m = window.location.pathname.match(/\/subscribe\/([^/]+)\/?$/);
  return m?.[1] ?? "";
}

function normProto(raw: string): string {
  const p = (raw || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  if (p.includes("vless")) return "vless";
  if (p.includes("vmess")) return "vmess";
  if (p.includes("trojan")) return "trojan";
  if (p.includes("shadowsocks") || p === "ss") return "shadowsocks";
  if (p.includes("wireguardxray") || p === "wgxray") return "wireguard-xray";
  if (p.includes("wireguard") || p === "wg") return "wireguard";
  if (p.includes("hysteria")) return "hysteria2";
  if (p.includes("tuic")) return "tuic";
  if (p.includes("anytls")) return "anytls";
  return p || "other";
}

function protoLabel(lang: SubLang, proto: string): string {
  const map: Record<string, string> = {
    vless: "protoVless",
    vmess: "protoVmess",
    trojan: "protoTrojan",
    shadowsocks: "protoShadowsocks",
    wireguard: "protoWireguard",
    "wireguard-xray": "protoWireguardXray",
    hysteria2: "protoHysteria2",
    tuic: "protoTuic",
    anytls: "protoAnytls",
  };
  return subT(lang, map[proto] || "protoOther");
}

/** CSS modifier for per-protocol color badges (e.g. wireguard-xray → wireguard-xray). */
function protoTone(proto: string): string {
  const p = (proto || "other").toLowerCase();
  if (p === "wireguard-xray" || p === "wireguardxray") return "wireguard-xray";
  return p.replace(/[^a-z0-9-]/g, "") || "other";
}


/** Outline protocol glyph — monochrome via currentColor (no emoji/PNG). */
function ProtoIcon({ proto, size = 18 }: { proto: string; size?: number }) {
  const p = protoTone(proto);
  const props = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className: "s-proto-svg",
    "aria-hidden": true as const,
  };
  if (p === "vless" || p === "vmess") {
    return (
      <svg {...props}>
        <path d="M12 3 4.5 7.5v9L12 21l7.5-4.5v-9L12 3z" />
        <path d="M12 12v9M4.5 7.5 12 12l7.5-4.5" />
      </svg>
    );
  }
  if (p === "trojan") {
    return (
      <svg {...props}>
        <rect x="5" y="11" width="14" height="10" rx="2" />
        <path d="M8 11V8a4 4 0 0 1 8 0v3" />
      </svg>
    );
  }
  if (p === "shadowsocks") {
    return (
      <svg {...props}>
        <circle cx="12" cy="12" r="8" />
        <path d="M8 12h8M12 8v8" />
      </svg>
    );
  }
  if (p === "wireguard" || p === "wireguard-xray") {
    return (
      <svg {...props}>
        <path d="M12 3 4 6v6c0 5 3.5 8.5 8 9.5 4.5-1 8-4.5 8-9.5V6l-8-3z" />
        <path d="M9.5 12.5 11.5 14.5 15 10.5" />
      </svg>
    );
  }
  if (p === "hysteria2") {
    return (
      <svg {...props}>
        <path d="M13 2 4 14h7l-1 8 10-14h-7l0-6z" />
      </svg>
    );
  }
  if (p === "tuic") {
    return (
      <svg {...props}>
        <circle cx="12" cy="12" r="9" />
        <path d="M8 12h8M12 7v10" />
        <path d="M9 9.5 15 14.5M15 9.5 9 14.5" opacity="0.35" />
      </svg>
    );
  }
  if (p === "anytls") {
    return (
      <svg {...props}>
        <path d="M7 11V8a5 5 0 0 1 10 0v3" />
        <rect x="5" y="11" width="14" height="9" rx="2" />
        <path d="M12 14v3" />
      </svg>
    );
  }
  return (
    <svg {...props}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l2.5 2.5" />
    </svg>
  );
}

function protoServersLabel(lang: SubLang, n: number): string | null {
  if (n <= 1) return null;
  return subT(lang, "protoServersN").replace("{n}", String(n));
}

/** Panel health RTT is a float; show whole milliseconds only. */
function formatLatencyMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  return String(Math.max(0, Math.round(ms)));
}

function protoFromLink(link: string): string {
  return normProto((link.split("://")[0] || "").toLowerCase());
}

/** Clean remark: prefer region name over ugly panel codes. */
function friendlyTitle(item: { remark?: string; region_name?: string; region_flag?: string; protocol: string }, lang: SubLang): string {
  const region = item.region_name?.trim();
  if (region) return region;
  const remark = (item.remark || "").trim();
  if (remark) {
    // "🇩🇪 Germany · p1 BlackBridge VLESS" → take part before · if present
    const head = remark.split("·")[0]?.trim();
    if (head && head.length < 40) return head.replace(/^[\u{1F1E0}-\u{1F1FF}\s]+/u, "").trim() || head;
    return remark;
  }
  return protoLabel(lang, item.protocol);
}

function statusChip(lang: SubLang, s: string): { label: string; cls: string } {
  const label = subT(lang, s) !== s ? subT(lang, s) : s;
  const cls =
    s === "active" ? "ok" :
    s === "expired" ? "warn" :
    s === "limited" ? "danger" : "neutral";
  return { label, cls };
}

/** Parse panel timestamps. Naive ISO from the API is UTC — append Z so browsers
 *  (esp. Iran UTC+3:30) don't treat it as local and skew "last online" by hours. */
function parseServerTime(value: string | null | undefined): number {
  if (!value) return NaN;
  const raw = value.trim();
  if (!raw) return NaN;
  if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(raw)) return new Date(raw).getTime();
  return new Date(`${raw}Z`).getTime();
}

type DailyUsageDay = { date: string; used_traffic: number };

function estimateRunOutDays(remainingBytes: number, days: DailyUsageDay[]): number | null {
  if (remainingBytes <= 0 || !days.length) return null;
  const total = days.reduce((sum, d) => sum + Math.max(0, Number(d.used_traffic) || 0), 0);
  if (total <= 0) return null;
  const avg = total / days.length;
  if (avg <= 0) return null;
  return remainingBytes / avg;
}

function dayLabel(iso: string, lang: SubLang): string {
  const parts = iso.split("-");
  if (parts.length < 3) return iso;
  const d = Number(parts[2]);
  if (lang === "fa") {
    try {
      return new Intl.DateTimeFormat("fa-IR", { day: "numeric", month: "short" }).format(new Date(`${iso}T12:00:00Z`));
    } catch {
      return String(d);
    }
  }
  return String(d);
}

function formatOnline(
  lang: SubLang,
  onlineAt: string | null | undefined,
  onlineFlag?: boolean | null,
): string {
  if (onlineFlag) return subT(lang, "onlineNow");
  if (!onlineAt) return subT(lang, "neverOnline");
  const ts = parseServerTime(onlineAt);
  if (Number.isNaN(ts)) return subT(lang, "neverOnline");
  const mins = Math.floor((Date.now() - ts) / 60000);
  if (mins < 0) return subT(lang, "onlineNow"); // clock skew guard
  // Keep in sync with config.ONLINE_WINDOW_MINUTES (default 1).
  if (mins < 1) return subT(lang, "onlineNow");
  if (mins < 60) return subT(lang, "minutesAgo").replace("{n}", String(mins));
  const hours = Math.floor(mins / 60);
  if (hours < 48) return subT(lang, "hoursAgo").replace("{n}", String(hours));
  return subT(lang, "daysAgo").replace("{n}", String(Math.floor(hours / 24)));
}

function recommendedApp(platform: Platform, apps: ClientApp[]): ClientApp | null {
  if (!apps.length) return null;
  const order: Record<Platform, string[]> = {
    android: ["v2rayng", "hiddify", "nekobox"],
    ios: ["streisand", "v2box", "hiddify"],
    windows: ["hiddify", "v2rayn", "clash-verge"],
    macos: ["hiddify", "streisand", "v2box"],
    linux: ["hiddify", "clash-verge"],
  };
  for (const id of order[platform]) {
    const hit = apps.find((a) => a.id === id);
    if (hit) return hit;
  }
  return apps[0];
}

function platformLabel(lang: SubLang, id: Platform): string {
  const key =
    id === "android" ? "platformAndroid" :
    id === "ios" ? "platformIos" :
    id === "windows" ? "platformWindows" :
    id === "macos" ? "platformMacos" : "platformLinux";
  return subT(lang, key);
}

const PROTO_ORDER = [
  "vless",
  "wireguard",
  "wireguard-xray",
  "hysteria2",
  "anytls",
  "tuic",
  "vmess",
  "trojan",
  "shadowsocks",
  "other",
];

/** API path prefixes to try when loading subscription JSON (legacy 3x-ui uses ``info``). */
function candidateSubPrefixes(): string[] {
  const out: string[] = [];
  try {
    const q = new URLSearchParams(window.location.search);
    for (const key of ["path", "prefix", "path_prefix"]) {
      const raw = (q.get(key) || "").trim().replace(/^\/+|\/+$/g, "");
      if (raw) out.push(raw);
    }
  } catch {
    /* ignore */
  }
  for (const p of ["sub", "info"]) {
    if (!out.includes(p)) out.push(p);
  }
  return out;
}

async function fetchSubApi(tok: string, suffix: string, prefixes?: string[]): Promise<{ prefix: string; response: Response }> {
  const list = prefixes?.length ? prefixes : candidateSubPrefixes();
  let last: Response | null = null;
  for (const prefix of list) {
    const response = await fetch(`/${prefix}/${tok}${suffix}`, {
      headers: { Accept: suffix === "/info" ? "application/json" : "*/*" },
    });
    if (response.ok) return { prefix, response };
    last = response;
  }
  throw new Error(last ? `HTTP ${last.status}` : "fetch failed");
}

function SubscribeBody() {
  const [lang, setLang] = useState<SubLang>("fa");
  const [token, setToken] = useState("");
  const [apiPrefix, setApiPrefix] = useState("sub");
  const [info, setInfo] = useState<SubInfo | null>(null);
  const [err, setErr] = useState("");
  const [platform, setPlatform] = useState<Platform>("android");
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "error" } | null>(null);
  const [protoFilter, setProtoFilter] = useState("all");
  const [selectedId, setSelectedId] = useState("");
  const [copied, setCopied] = useState(false);
  const [qrModal, setQrModal] = useState(false);
  const [busyConnect, setBusyConnect] = useState(false);
  const [view, setView] = useState<"overview" | "servers" | "import" | "apps">("overview");
  const [wgConfByNode, setWgConfByNode] = useState<Record<number, string>>({});
  const wgFetchStarted = useRef<Set<number>>(new Set());
  const [stepsDone, setStepsDone] = useState<{ apps: boolean; import: boolean; servers: boolean }>({
    apps: false, import: false, servers: false,
  });
  const [setupExpanded, setSetupExpanded] = useState(false);
  const [serverQuery, setServerQuery] = useState("");
  const [serverSort, setServerSort] = useState<"recommended" | "name">("recommended");
  const [pickingServer, setPickingServer] = useState(true);
  const [dailyUsage, setDailyUsage] = useState<DailyUsageDay[]>([]);
  const [usageOpen, setUsageOpen] = useState(false);
  const [usageLoading, setUsageLoading] = useState(false);

  const goView = useCallback((next: "overview" | "servers" | "import" | "apps") => {
    if (next === "apps" || next === "import" || next === "servers") {
      setStepsDone((prev) => {
        const updated = { ...prev, [next]: true };
        try { localStorage.setItem("nx_sub_steps_done", JSON.stringify(updated)); } catch { /* ignore */ }
        return updated;
      });
    }
    setView(next);
  }, []);

  const loadInfo = useCallback((tok: string) => {
    if (!tok) return;
    setErr("");
    fetchSubApi(tok, "/info")
      .then(async ({ prefix, response }) => {
        setApiPrefix(prefix);
        return response.json();
      })
      .then((data: SubInfo) => setInfo(data))
      .catch((e: Error) => setErr(e.message || subT(lang, "fetchError")));
  }, [lang]);

  const loadDailyUsage = useCallback((tok: string) => {
    if (!tok) return;
    setUsageLoading(true);
    fetchSubApi(tok, "/usage/daily?days=7")
      .then(async ({ response }) => response.json())
      .then((data: { days?: DailyUsageDay[] }) => {
        const rows = Array.isArray(data?.days) ? data.days : [];
        setDailyUsage(rows.map((d) => ({
          date: String(d.date || ""),
          used_traffic: Math.max(0, Number(d.used_traffic) || 0),
        })));
      })
      .catch(() => setDailyUsage([]))
      .finally(() => setUsageLoading(false));
  }, []);

  useEffect(() => {
    setLang(detectSubLang());
    const tok = getToken();
    setToken(tok);
    setPlatform(detectPlatform(typeof navigator !== "undefined" ? navigator.userAgent : ""));
    try {
      const raw = localStorage.getItem("nx_sub_steps_done");
      if (raw) {
        const parsed = JSON.parse(raw) as { apps?: boolean; import?: boolean; servers?: boolean };
        setStepsDone({
          apps: !!parsed.apps,
          import: !!parsed.import,
          servers: !!parsed.servers,
        });
      }
    } catch { /* ignore */ }
    loadInfo(tok);
    loadDailyUsage(tok);
  }, [loadInfo, loadDailyUsage]);

  const subUrl = useMemo(() => resolvePublicSubUrl(info, token, apiPrefix), [info, token, apiPrefix]);
  const importUrl = useMemo(
    () => resolveClientImportUrl(info, token, apiPrefix) || subUrl,
    [info, token, apiPrefix, subUrl],
  );
  const profileTitle =
    info?.subscription_profile_title?.trim()
    || info?.branding?.sub_profile_title?.trim()
    || info?.branding?.panel_title?.trim()
    || "NexusPanel";

  useEffect(() => {
    const b = info?.branding;
    if (!b) return;
    if (b.primary_color) {
      document.documentElement.style.setProperty("--nx-accent", b.primary_color);
      document.documentElement.style.setProperty("--s-accent", b.primary_color);
    }
    if (b.favicon_url) {
      let link = document.querySelector("link[rel='icon']") as HTMLLinkElement | null;
      if (!link) {
        link = document.createElement("link");
        link.rel = "icon";
        document.head.appendChild(link);
      }
      link.href = b.favicon_url;
    }
    const tabTitle = (b.panel_title || "").trim() || "NexusPanel";
    document.title = tabTitle;
  }, [info?.branding]);

  const hasWireguard = !!info?.proxies && "wireguard" in info.proxies;
  const hasHysteria2 = !!info?.proxies && "hysteria2" in info.proxies;
  const hasTuic = !!info?.proxies && "tuic" in info.proxies;
  const hasAnytls = !!info?.proxies && "anytls" in info.proxies;
  const wgNodes = info?.wireguard_nodes ?? [];

  useEffect(() => {
    // Only fetch .conf when the user opens Servers — overview must not hit
    // /wireguard (that path records device IPs and used to bump online_at).
    if (view !== "servers") return;
    if (!token || !info || info.config_available === false || !hasWireguard) return;
    const nodes = wgNodes.length
      ? wgNodes
      : [{
          id: -1,
          plain_available: !!info.wireguard_plain_uri,
          xray_available: !!info.wireguard_xray_uri,
        } as (typeof wgNodes)[number]];
    nodes.forEach((n) => {
      const nodePath = n.id > 0 ? `/${n.id}` : "";
      // 3x-ui style .conf (Finalmask port) for WireGuard-app QR / download.
      if (!(n.plain_available || n.wireguard_plain_uri || n.xray_available || n.wireguard_xray_uri)) return;
      if (wgFetchStarted.current.has(n.id)) return;
      wgFetchStarted.current.add(n.id);
      fetch(`/${apiPrefix}/${token}/wireguard${nodePath}`)
        .then(async (r) => (r.ok ? r.text() : ""))
        .then((body) => {
          const t = body.trim();
          // .conf only — JSON is the separate Xray download.
          if (t && t.includes("[Interface]") && !t.startsWith("{")) {
            setWgConfByNode((prev) => ({ ...prev, [n.id]: t }));
          }
        })
        .catch(() => {});
    });
  }, [view, token, info, hasWireguard, wgNodes, apiPrefix]);

  const configs: ConfigEntry[] = useMemo(() => {
    if (!info) return [];
    const out: ConfigEntry[] = [];
    const quic = (info.singbox_nodes || []).filter((n) =>
      (hasHysteria2 && n.hysteria2_available)
      || (hasTuic && n.tuic_available)
      || (hasAnytls && n.anytls_available),
    );
    // Prefer structured node cards (region/flag). Skip the same protocols from
    // unified share-link items so we don't show "user-node-hy2" duplicates.
    const skipFromLinks = new Set<string>();
    if (quic.length || info.hysteria2_link || info.tuic_link || info.anytls_link) {
      if (hasHysteria2) skipFromLinks.add("hysteria2");
      if (hasTuic) skipFromLinks.add("tuic");
      if (hasAnytls) skipFromLinks.add("anytls");
    }
    if (hasWireguard && (wgNodes.length || info.wireguard_uri || info.wireguard_xray_uri)) {
      skipFromLinks.add("wireguard");
      skipFromLinks.add("wireguard-xray");
    }

    const items = info.link_items?.length
      ? info.link_items
      : (info.links || []).map((link) => ({
          link,
          protocol: protoFromLink(link),
          remark: "",
          region_flag: "",
          region_name: "",
          latency_ms: null as number | null,
        }));

    items.forEach((item, i) => {
      const protocol = normProto(item.protocol || protoFromLink(item.link));
      if (skipFromLinks.has(protocol)) return;
      out.push({
        id: `x-${i}`,
        protocol,
        title: friendlyTitle({ ...item, protocol }, lang),
        flag: item.region_flag,
        value: item.link,
        latencyMs: item.latency_ms ?? null,
      });
    });

    if (hasWireguard) {
      const pushWg = (
        id: string,
        protocol: "wireguard" | "wireguard-xray",
        title: string,
        flag: string | undefined,
        value: string,
        downloadHref: string,
        latencyMs?: number | null,
      ) => {
        if (!value && !downloadHref) return;
        out.push({ id, protocol, title, flag, value: value || downloadHref, downloadHref, latencyMs });
      };

      if (wgNodes.length) {
        wgNodes.forEach((n) => {
          const title = n.region_name || n.name;
          const flag = n.region_flag || undefined;
          const conf = (wgConfByNode[n.id] || "").trim();
          const plainUri = (n.wireguard_plain_uri || "").trim();
          const xrayUri = (n.wireguard_xray_uri || "").trim();
          const hasPlain = !!(n.plain_available || plainUri || conf);
          const hasXray = !!(n.xray_available || xrayUri);
          const latencyMs = n.latency_ms ?? null;
          // WireGuard app: QR/copy .conf; download .conf (not imported into Xray subs).
          if (hasPlain && (conf || plainUri)) {
            pushWg(
              `wg-${n.id}`,
              "wireguard",
              title,
              flag,
              conf || plainUri,
              resolveWgUrl(subUrl, "plain", n.id),
              latencyMs,
            );
          }
          // Xray apps: wireguard:// + fm= only (no JSON download — sub import is enough).
          if (hasXray && xrayUri) {
            pushWg(
              `wg-xray-${n.id}`,
              "wireguard-xray",
              title,
              flag,
              xrayUri,
              "",
              latencyMs,
            );
          }
        });
      } else {
        const conf = (wgConfByNode[-1] || "").trim();
        const plainUri = (info.wireguard_plain_uri || "").trim();
        const xrayUri = (info.wireguard_xray_uri || "").trim();
        if (plainUri || conf) {
          pushWg("wg-0", "wireguard", "WireGuard", undefined, conf || plainUri, resolveWgUrl(subUrl, "plain"));
        }
        if (xrayUri) {
          pushWg("wg-xray-0", "wireguard-xray", "WireGuard", undefined, xrayUri, "");
        }
      }
    }

    if (quic.length) {
      quic.forEach((n) => {
        const title = n.region_name || n.name;
        const latencyMs = n.latency_ms ?? null;
        if (hasHysteria2 && n.hysteria2_link) {
          out.push({ id: `hy2-${n.id}`, protocol: "hysteria2", title, flag: n.region_flag || undefined, value: n.hysteria2_link, latencyMs });
        }
        if (hasTuic && n.tuic_link) {
          out.push({ id: `tuic-${n.id}`, protocol: "tuic", title, flag: n.region_flag || undefined, value: n.tuic_link, latencyMs });
        }
        if (hasAnytls && n.anytls_link) {
          out.push({ id: `any-${n.id}`, protocol: "anytls", title, flag: n.region_flag || undefined, value: n.anytls_link, latencyMs });
        }
      });
    } else {
      if (hasHysteria2 && info.hysteria2_link) {
        out.push({ id: "hy2", protocol: "hysteria2", title: protoLabel(lang, "hysteria2"), value: info.hysteria2_link });
      }
      if (hasTuic && info.tuic_link) {
        out.push({ id: "tuic", protocol: "tuic", title: protoLabel(lang, "tuic"), value: info.tuic_link });
      }
      if (hasAnytls && info.anytls_link) {
        out.push({ id: "any", protocol: "anytls", title: protoLabel(lang, "anytls"), value: info.anytls_link });
      }
    }
    const rank = (p: string) => {
      const i = PROTO_ORDER.indexOf(p);
      return i < 0 ? PROTO_ORDER.length : i;
    };
    out.sort((a, b) => rank(a.protocol) - rank(b.protocol) || a.title.localeCompare(b.title));
    return out;
  }, [info, lang, hasWireguard, hasHysteria2, hasTuic, hasAnytls, wgNodes, wgConfByNode, subUrl]);

  const protocolTabs = useMemo(() => {
    const counts = new Map<string, number>();
    configs.forEach((c) => counts.set(c.protocol, (counts.get(c.protocol) || 0) + 1));
    return PROTO_ORDER.filter((p) => counts.has(p)).map((p) => ({ id: p, count: counts.get(p)! }));
  }, [configs]);

  const filtered = useMemo(
    () => {
      if (!protocolTabs.length) return [];
      if (protoFilter === "all") return configs;
      return configs.filter((c) => c.protocol === protoFilter);
    },
    [configs, protoFilter, protocolTabs.length],
  );

  useEffect(() => {
    if (!protocolTabs.length) return;
    if (protoFilter === "all" || !protocolTabs.some((p) => p.id === protoFilter)) {
      setProtoFilter(protocolTabs[0].id);
    }
  }, [protocolTabs, protoFilter]);

  useEffect(() => {
    setServerQuery("");
    setPickingServer(filtered.length !== 1);
  }, [protoFilter, filtered.length]);

  const visibleServers = useMemo(() => {
    const q = serverQuery.trim().toLowerCase();
    let list = filtered;
    if (q) {
      list = list.filter((c) =>
        c.title.toLowerCase().includes(q)
        || (c.flag || "").includes(q)
        || c.protocol.toLowerCase().includes(q),
      );
    }
    const sorted = [...list];
    if (serverSort === "name") {
      sorted.sort((a, b) => a.title.localeCompare(b.title));
    } else {
      sorted.sort((a, b) => {
        const la = a.latencyMs != null && a.latencyMs >= 0 ? a.latencyMs : Number.POSITIVE_INFINITY;
        const lb = b.latencyMs != null && b.latencyMs >= 0 ? b.latencyMs : Number.POSITIVE_INFINITY;
        if (la !== lb) return la - lb;
        return a.title.localeCompare(b.title);
      });
    }
    return sorted;
  }, [filtered, serverQuery, serverSort]);

  const serversByRegion = useMemo(() => {
    const order: RegionBucket[] = ["middleEast", "europe", "asia", "americas", "other"];
    const map = new Map<RegionBucket, ConfigEntry[]>();
    for (const b of order) map.set(b, []);
    for (const c of visibleServers) {
      const b = regionBucket(c.title);
      map.get(b)!.push(c);
    }
    return order
      .map((bucket) => ({ bucket, items: map.get(bucket)! }))
      .filter((g) => g.items.length > 0);
  }, [visibleServers]);

  const bestServer = useMemo(() => {
    if (!filtered.length) return null;
    const withLatency = filtered.filter((c) => c.latencyMs != null && c.latencyMs >= 0);
    // Without probe data, "lowest latency" would just pick alphabetical first —
    // hide the Auto card so we don't pretend.
    if (!withLatency.length) return null;
    return [...withLatency].sort((a, b) => {
      const la = a.latencyMs as number;
      const lb = b.latencyMs as number;
      if (la !== lb) return la - lb;
      return a.title.localeCompare(b.title);
    })[0] || null;
  }, [filtered]);

  useEffect(() => {
    if (!filtered.length) { setSelectedId(""); return; }
    if (!filtered.some((c) => c.id === selectedId)) {
      const pick = serverSort === "recommended" && bestServer ? bestServer.id : filtered[0].id;
      setSelectedId(pick);
    }
  }, [filtered, selectedId, serverSort, bestServer]);

  const selected = filtered.find((c) => c.id === selectedId) || filtered[0] || null;

  // Must stay above early returns (err / !info) — Rules of Hooks.
  const uniqueServerCount = useMemo(() => {
    const keys = new Set(
      configs.map((c) => `${(c.flag || "").trim()}|${String(c.title || "").trim().toLowerCase()}`),
    );
    return keys.size;
  }, [configs]);

  const pickServer = useCallback((id: string) => {
    setSelectedId(id);
    if (filtered.length > 1) setPickingServer(false);
  }, [filtered.length]);

  const configAvailable = info?.config_available !== false;
  const blockReason = info?.block_reason;
  const used = info?.used_traffic ?? 0;
  const overage = info?.overage_traffic ?? 0;
  const total = info?.data_limit || 0;
  const left = total ? Math.max(0, total - used) : 0;
  const pct = total ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const chip = info ? statusChip(lang, info.status) : { label: "—", cls: "neutral" };
  const expiry = info ? relativeDays(info.expire) : null;
  const rtl = lang === "fa";

  const showToast = useCallback((msg: string, kind: "ok" | "error" = "ok") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 2500);
  }, []);

  const pickLang = (code: SubLang) => {
    setLang(code);
    rememberSubLang(code);
    const u = new URL(window.location.href);
    u.searchParams.set("lang", code);
    window.history.replaceState({}, "", u.toString());
  };

  async function copyValue(value: string) {
    const ok = await copyToClipboard(value);
    if (ok) {
      setCopied(true);
      showToast(subT(lang, "copied"));
      setTimeout(() => setCopied(false), 1500);
    } else showToast(subT(lang, "copyFailed"), "error");
  }

  /** Mobile Safari ignores ``<a download>`` for navigations; use Blob + Share. */
  async function downloadConfFile(entry: ConfigEntry) {
    const safeName = (entry.title || "wireguard")
      .replace(/[^\w.\-()\u0600-\u06FF\s]+/g, "")
      .trim()
      .replace(/\s+/g, "-")
      .slice(0, 48) || "wireguard";
    const filename = safeName.endsWith(".conf") ? safeName : `${safeName}.conf`;

    let body = "";
    if (entry.value.includes("[Interface]") && !entry.value.startsWith("wireguard://")) {
      body = entry.value;
    } else if (entry.downloadHref) {
      try {
        const r = await fetch(entry.downloadHref, { credentials: "same-origin" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        body = await r.text();
      } catch {
        showToast(subT(lang, "downloadFailed"), "error");
        return;
      }
    }
    if (!body.trim()) {
      showToast(subT(lang, "downloadFailed"), "error");
      return;
    }

    const file = new File([body], filename, { type: "application/octet-stream" });
    const nav = navigator as Navigator & {
      canShare?: (data?: ShareData) => boolean;
      share?: (data?: ShareData) => Promise<void>;
    };
    try {
      if (typeof nav.canShare === "function" && nav.canShare({ files: [file] }) && nav.share) {
        await nav.share({ files: [file], title: filename });
        showToast(subT(lang, "downloaded"));
        return;
      }
    } catch (err) {
      // User cancelled share sheet — not an error.
      if (err instanceof DOMException && err.name === "AbortError") return;
    }

    try {
      const url = URL.createObjectURL(file);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.rel = "noopener";
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      showToast(subT(lang, "downloaded"));
    } catch {
      const ok = await copyToClipboard(body);
      showToast(ok ? subT(lang, "copied") : subT(lang, "downloadFailed"), ok ? "ok" : "error");
    }
  }

  const proxyApps = appsFor(platform);
  const primaryApp = recommendedApp(platform, proxyApps);
  const otherApps = proxyApps.filter((a) => a.id !== primaryApp?.id);
  // Official WireGuard + AmneziaWG only (skip duplicate store variants).
  const wgApps = wgAppsFor(platform).filter((a) => a.id === "wireguard" || a.id === "amneziawg");
  const pasteFallback = (n: string) => subT(lang, "pasteFallback").replace("{app}", n);

  async function connectPrimary() {
    if (!primaryApp || !importUrl) return;
    setBusyConnect(true);
    const deepLink = primaryApp.buildScheme(importUrl, { name: profileTitle });
    const copyFirst = platform === "macos" || platform === "ios" || primaryApp.id === "hiddify" || primaryApp.id === "streisand";
    if (copyFirst) {
      const ok = await copyToClipboard(importUrl);
      if (!ok) { showToast(subT(lang, "noAppResponse"), "error"); setBusyConnect(false); return; }
      showToast(
        primaryApp.id === "streisand"
          ? subT(lang, "streisandHint")
          : subT(lang, "clipboardHint").replace("{app}", primaryApp.name),
      );
      try { openDeepLink(deepLink); } catch { /* */ }
      setTimeout(() => setBusyConnect(false), 500);
      return;
    }
    let blurred = false;
    const onBlur = () => { blurred = true; };
    window.addEventListener("blur", onBlur, { once: true });
    try { openDeepLink(deepLink); } catch { /* */ }
    setTimeout(async () => {
      window.removeEventListener("blur", onBlur);
      setBusyConnect(false);
      if (!blurred) {
        const ok = await copyToClipboard(importUrl);
        showToast(ok ? pasteFallback(primaryApp.name) : subT(lang, "noAppResponse"), ok ? "ok" : "error");
      }
    }, 1100);
  }

  if (!token) {
    return <SimpleShell rtl={rtl} lang={lang} onPick={pickLang}><Empty msg={subT(lang, "fetchError")} /></SimpleShell>;
  }
  if (err) {
    return (
      <SimpleShell rtl={rtl} lang={lang} onPick={pickLang}>
        <div className="s-card s-center">
          <p className="s-title">{subT(lang, "fetchError")}</p>
          <button type="button" className="s-btn s-btn-main" onClick={() => loadInfo(token)}>{subT(lang, "refresh")}</button>
        </div>
      </SimpleShell>
    );
  }
  if (!info) {
    return (
      <SimpleShell rtl={rtl} lang={lang} onPick={pickLang}>
        <div className="s-skel" />
        <div className="s-skel s-skel-tall" />
      </SimpleShell>
    );
  }

  const expireText = !info.expire
    ? subT(lang, "noExpiry")
    : !expiry || expiry.days < 0
      ? formatDate(info.expire)
      : expiry.days === 0
        ? subT(lang, "today")
        : subT(lang, "daysLeft").replace("{n}", String(expiry.days));

  const isUnlimited = !total;
  const usedText = bytes(used, 1);
  const usedParts = (() => {
    const m = usedText.match(/^([\d.]+)\s*(.*)$/);
    return m ? { num: m[1], unit: m[2] } : { num: usedText, unit: "" };
  })();
  const remainText = isUnlimited ? "" : bytes(left, 1);
  const remainParts = isUnlimited
    ? { num: "", unit: "" }
    : (() => {
        const m = remainText.match(/^([\d.]+)\s*(.*)$/);
        return m ? { num: m[1], unit: m[2] } : { num: remainText, unit: "" };
      })();
  const barTone = pct >= 85 ? "danger" : pct >= 70 ? "warn" : "ok";
  const runOutDays = !isUnlimited ? estimateRunOutDays(left, dailyUsage) : null;
  const runOutText =
    runOutDays == null
      ? ""
      : runOutDays < 1
        ? subT(lang, "runsOutSoon")
        : subT(lang, "runsOutIn").replace("{n}", String(Math.max(1, Math.ceil(runOutDays))));
  const usageMax = Math.max(1, ...dailyUsage.map((d) => d.used_traffic), 1);
  const weekTotal = dailyUsage.reduce((s, d) => s + d.used_traffic, 0);
  const avgDailyText = dailyUsage.length && weekTotal > 0
    ? subT(lang, "avgDaily").replace("{n}", bytes(Math.round(weekTotal / dailyUsage.length), 1))
    : "";
  const showUsageWarn = !isUnlimited && pct >= 80 && configAvailable;
  const isOnlineNow = info.online === true || formatOnline(lang, info.online_at) === subT(lang, "onlineNow");
  const onlineText = formatOnline(lang, info.online_at, isOnlineNow);
  // Prefer server count; if account is live but API omitted devices, show at least 1.
  const onlineDevices = Math.max(
    0,
    Number(info.online_devices ?? 0) || (isOnlineNow ? 1 : 0),
  );
  const deviceLimit = info.device_limit && info.device_limit > 0 ? info.device_limit : null;
  const devicesText = deviceLimit
    ? subT(lang, "devicesOfLimit").replace("{n}", String(onlineDevices)).replace("{max}", String(deviceLimit))
    : subT(lang, "devicesUnlimited").replace("{n}", String(onlineDevices));
  const brandName = info.branding?.panel_title?.trim() || "NexusPanel";
  const brandLogo = info.branding?.logo_url?.trim() || "/sub-assets/brand/nexuspanel-logo.png";
  const supportUrl = info.branding?.support_url?.trim() || "";
  // Headline = plan label, never brand (brand already lives in the topbar).
  const rawPlan = (info.branding?.sub_profile_title || "").trim();
  const displayTitle =
    rawPlan && rawPlan !== brandName && !rawPlan.includes("·")
      ? rawPlan
      : subT(lang, "personalSub");
  const accountId = (info.username || "").trim();
  const allStepsDone = stepsDone.apps && stepsDone.import && stepsDone.servers;

  const configActions = selected ? (
    <div className="s-qr-bundle">
      <button type="button" className="s-qr" onClick={() => setQrModal(true)} aria-label={subT(lang, "tapBigger")}>
        <div className="s-qr-frame">
          <QR value={selected.value} size={160} />
        </div>
        <span className="s-qr-hint">{subT(lang, "scanHere")}</span>
      </button>
      <div className="s-qr-side">
        {/* Plain WireGuard uses Download .conf — copy is for share links (VLESS / WG Xray). */}
        {selected.protocol !== "wireguard" && selected.value ? (
          <>
            <button type="button" className="s-btn s-btn-main s-btn-xl" onClick={() => copyValue(selected.value)}>
              {copied ? subT(lang, "copied") : subT(lang, "copyConfig")}
            </button>
            <p className="s-copy-hint">{subT(lang, "copyConfigHint")}</p>
          </>
        ) : null}
        {selected.downloadHref ? (
          <button type="button" className="s-btn s-btn-soft s-btn-xl" onClick={() => void downloadConfFile(selected)}>
            {subT(lang, "downloadFile")}
          </button>
        ) : null}
        {selected.protocol === "tuic" ? (
          <p className="s-warn s-warn-strong" role="status">
            <span className="s-warn-ico" aria-hidden>!</span>
            {subT(lang, "tuicWarn")}
          </p>
        ) : null}
      </div>
    </div>
  ) : null;

  const overviewInfo = (
    <div className="s-overview">
      {showUsageWarn ? (
        <section className={`s-alert s-usage-alert ${pct >= 85 ? "danger" : "warn"}`} role="status">
          <p className="s-title">
            {pct >= 85 ? subT(lang, "usageCriticalTitle") : subT(lang, "usageWarnTitle")}
          </p>
          <p className="s-muted">
            {(pct >= 85 ? subT(lang, "usageCriticalBody") : subT(lang, "usageWarnBody")).replace("{n}", String(pct))}
          </p>
        </section>
      ) : null}
      <section className="s-ov-hero" aria-label={subT(lang, "personalSub")}>
        <div className="s-ov-identity">
          <div className="s-ov-title-block">
            {displayTitle !== subT(lang, "personalSub") ? (
              <span className="s-ov-kicker">{subT(lang, "personalSub")}</span>
            ) : null}
            <h2 className="s-ov-user">{displayTitle}</h2>
            {accountId ? (
              <button
                type="button"
                className="s-id-inline"
                onClick={() => void copyValue(accountId)}
                title={subT(lang, "copyId")}
                aria-label={`${subT(lang, "accountId")}: ${accountId}`}
              >
                <span className="s-id-label">{subT(lang, "accountId")}</span>
                <span className="s-id-mono" dir="ltr">{accountId}</span>
              </button>
            ) : null}
          </div>
          <div className={`s-ov-presence ${isOnlineNow ? "live" : ""}`}>
            <span className={`s-live-dot ${isOnlineNow ? "" : "off"}`} aria-hidden />
            <span>{isOnlineNow ? subT(lang, "accountLive") : onlineText}</span>
          </div>
        </div>

        <div className="s-ov-metrics" role="list">
          <article className={`s-ov-metric s-ov-data ${isUnlimited ? "unlimited" : barTone}`} role="listitem">
            <div className="s-data-head">
              <span className="s-ov-k">{subT(lang, "dataUsage")}</span>
              {isUnlimited ? (
                <span className="s-data-badge">{subT(lang, "planUnlimited")}</span>
              ) : (
                <span className={`s-data-badge tone-${barTone}`}>
                  {subT(lang, "usedPercent").replace("{n}", String(pct))}
                </span>
              )}
            </div>

            {isUnlimited ? (
              <div className="s-data-body">
                <div className="s-data-main">
                  <div className="s-data-figure" dir="ltr">
                    <span className="s-data-num">{usedParts.num}</span>
                    {usedParts.unit ? <span className="s-data-unit">{usedParts.unit}</span> : null}
                  </div>
                  <span className="s-data-caption">{subT(lang, "usedLabel")}</span>
                  {avgDailyText ? <span className="s-data-avg" dir="ltr">{avgDailyText}</span> : null}
                </div>
                {dailyUsage.length ? (
                  <div className="s-data-spark" aria-hidden>
                    {dailyUsage.map((d) => {
                      const h = Math.round((d.used_traffic / usageMax) * 100);
                      return (
                        <span
                          key={d.date}
                          className={`s-data-spark-bar ${d.used_traffic > 0 ? "on" : ""}`}
                          style={{ height: `${Math.max(d.used_traffic > 0 ? 12 : 4, h)}%` }}
                          title={`${d.date}: ${bytes(d.used_traffic, 1)}`}
                        />
                      );
                    })}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="s-data-body limited">
                <div className="s-data-split">
                  <div className="s-data-main">
                    <div className="s-data-figure" dir="ltr">
                      <span className="s-data-num">{remainParts.num}</span>
                      {remainParts.unit ? <span className="s-data-unit">{remainParts.unit}</span> : null}
                    </div>
                    <span className="s-data-caption">{subT(lang, "leftLabel")}</span>
                  </div>
                  <div className="s-data-side">
                    <div className={`s-data-pct ${barTone}`} dir="ltr">
                      {subT(lang, "usedPercentBig").replace("{n}", String(pct))}
                    </div>
                    <span className="s-data-caption">{subT(lang, "usedLabel")}</span>
                  </div>
                </div>
                <div className="s-bar-row">
                  <div className="s-bar s-ov-bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                    <div className={`s-bar-fill ${barTone}`} style={{ width: `${Math.max(pct, pct === 0 ? 0 : 2)}%` }} />
                  </div>
                </div>
                <div className="s-data-foot" dir="ltr">
                  <span>{subT(lang, "usedLabel")}: {bytes(used, 1)}</span>
                  <span>{subT(lang, "ofTotal").replace("{n}", bytes(total, 1))}</span>
                  {overage > 0 ? <span>{subT(lang, "overage")} {bytes(overage, 1)}</span> : null}
                </div>
                {runOutText ? <span className="s-ov-predict">{runOutText}</span> : null}
              </div>
            )}
          </article>

          <article className="s-ov-metric" role="listitem">
            <span className="s-ov-k">{subT(lang, "expire")}</span>
            <div className="s-ov-v">{expireText}</div>
            <span className="s-ov-sub">{info.expire ? formatDate(info.expire) : subT(lang, "noExpiry")}</span>
          </article>

          <article className={`s-ov-metric s-ov-devices ${onlineDevices > 0 ? "on" : ""}`} role="listitem">
            <span className="s-ov-k">{subT(lang, "devicesOnline")}</span>
            <div className="s-ov-v s-ov-devices-v">
              <Smartphone size={18} strokeWidth={2} aria-hidden />
              <span dir="ltr">{onlineDevices > 0 ? devicesText : subT(lang, "noDevices")}</span>
            </div>
            <span className="s-ov-sub">
              {onlineDevices > 0
                ? subT(lang, "connectedDevices")
                : (isOnlineNow ? subT(lang, "onlineNow") : subT(lang, "accountIdle"))}
            </span>
          </article>

          <article className="s-ov-metric" role="listitem">
            <span className="s-ov-k">{subT(lang, "lastOnline")}</span>
            <div className="s-ov-v s-ov-online">
              {isOnlineNow ? <span className="s-live-dot" aria-hidden /> : null}
              {onlineText}
            </div>
          </article>
        </div>

        <div className="s-usage-hist">
          <button
            type="button"
            className={`s-usage-toggle ${usageOpen ? "open" : ""}`}
            aria-expanded={usageOpen}
            onClick={() => setUsageOpen((v) => !v)}
          >
            <span>{subT(lang, "usageHistory")}</span>
            <span className="s-usage-toggle-meta">{subT(lang, "usageHistoryHint")}</span>
            <span className="s-usage-chevron" aria-hidden>{usageOpen ? "▾" : "◂"}</span>
          </button>
          {usageOpen ? (
            <div className="s-usage-panel">
              {usageLoading && !dailyUsage.length ? (
                <div className="s-skel" style={{ height: 88 }} />
              ) : (
                <div className="s-usage-chart" role="img" aria-label={subT(lang, "usageHistoryHint")}>
                  {dailyUsage.map((d) => {
                    const h = Math.round((d.used_traffic / usageMax) * 100);
                    return (
                      <div key={d.date} className="s-usage-col" title={`${d.date}: ${bytes(d.used_traffic, 1)}`}>
                        <div className="s-usage-bar-wrap">
                          <div
                            className={`s-usage-bar ${d.used_traffic > 0 ? "on" : ""}`}
                            style={{ height: `${Math.max(d.used_traffic > 0 ? 8 : 2, h)}%` }}
                          />
                        </div>
                        <span className="s-usage-day">{dayLabel(d.date, lang)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ) : null}
        </div>
      </section>

      {configAvailable ? (
        <section className="s-ov-actions s-surface">
          {allStepsDone && !setupExpanded ? (
            <div className="s-allset">
              <div className="s-allset-head">
                <h3 className="s-ov-protos-title">{subT(lang, "allSetTitle")} ✓</h3>
                <button type="button" className="s-linkish" onClick={() => setSetupExpanded(true)}>
                  {subT(lang, "showSteps")}
                </button>
              </div>
              <button type="button" className="s-btn s-btn-main s-btn-xl" onClick={() => goView("servers")}>
                {subT(lang, "manageServers")}
              </button>
            </div>
          ) : (
            <>
              <div className="s-ov-actions-head">
                <h3 className="s-ov-protos-title">
                  {allStepsDone ? subT(lang, "setupDoneTitle") : subT(lang, "quickSetup")}
                </h3>
                {allStepsDone ? (
                  <button type="button" className="s-linkish" onClick={() => setSetupExpanded(false)}>
                    {subT(lang, "hideSteps")}
                  </button>
                ) : (
                  <span className="s-setup-hint">{subT(lang, "setupTapHint")}</span>
                )}
              </div>
              <div className="s-setup-steps">
                <button type="button" className={`s-setup-step ${stepsDone.apps ? "done" : ""}`} onClick={() => goView("apps")}>
                  <span className="s-setup-num">{stepsDone.apps ? "✓" : "1"}</span>
                  <span className="s-setup-label">{subT(lang, "quickSetupApps")}</span>
                  <span className="s-setup-go" aria-hidden>›</span>
                </button>
                <button type="button" className={`s-setup-step ${stepsDone.import ? "done" : ""}`} onClick={() => goView("import")}>
                  <span className="s-setup-num">{stepsDone.import ? "✓" : "2"}</span>
                  <span className="s-setup-label">{subT(lang, "quickSetupImport")}</span>
                  <span className="s-setup-go" aria-hidden>›</span>
                </button>
                <button type="button" className={`s-setup-step ${stepsDone.servers ? "done" : ""}`} onClick={() => goView("servers")}>
                  <span className="s-setup-num">{stepsDone.servers ? "✓" : "3"}</span>
                  <span className="s-setup-label">{subT(lang, "quickSetupServers")}</span>
                  <span className="s-setup-go" aria-hidden>›</span>
                </button>
              </div>
              {allStepsDone ? (
                <button type="button" className="s-btn s-btn-main s-btn-xl" onClick={() => goView("servers")}>
                  {subT(lang, "manageServers")}
                </button>
              ) : null}
            </>
          )}
          {supportUrl ? (
            <a className="s-support" href={supportUrl} target="_blank" rel="noopener noreferrer">
              {subT(lang, "supportLink")}
            </a>
          ) : null}
        </section>
      ) : null}
    </div>
  );

  const crumbProto = protoFilter !== "all" ? protoLabel(lang, protoFilter) : null;
  const crumbServer = selected?.title || null;
  const showPicker = pickingServer || filtered.length > 1;

  const serversView = (
    <div className="s-servers-view">
      <nav className="s-crumb-steps" aria-label={subT(lang, "pickProtocol")}>
        <button
          type="button"
          className={`s-crumb-step ${!crumbProto ? "on" : "done"}`}
          onClick={() => setProtoFilter(protocolTabs[0]?.id || "all")}
        >
          <span className="s-step-i">1</span>
          <span>{subT(lang, "stepProtocol")}{crumbProto ? ` · ${crumbProto}` : ""}</span>
        </button>
        <span className="s-step-sep" aria-hidden>›</span>
        <button
          type="button"
          className={`s-crumb-step ${showPicker ? "on" : selected ? "done" : ""}`}
          disabled={protoFilter === "all"}
          onClick={() => setPickingServer(true)}
        >
          <span className="s-step-i">2</span>
          <span>
            {subT(lang, "stepServer")}
            {crumbServer && !showPicker ? ` · ${selected?.flag || ""} ${crumbServer}`.replace(/\s+/g, " ").trim() : ""}
          </span>
        </button>
        {selected && !showPicker ? (
          <button type="button" className="s-crumb-change" onClick={() => setPickingServer(true)}>
            {subT(lang, "changeServer")}
          </button>
        ) : null}
        <span className="s-step-sep" aria-hidden>›</span>
        <span className={`s-crumb-step ${selected && !showPicker ? "on" : ""}`}>
          <span className="s-step-i">3</span>
          <span>{subT(lang, "stepConfig")}</span>
        </span>
      </nav>

      <section className="s-panel">
        <div className="s-panel-head">
          <h2 className="s-panel-title">{subT(lang, "stepProtocol")}</h2>
        </div>
        <div className="s-panel-body">
          {!protocolTabs.length ? (
            <p className="s-empty">{subT(lang, "noConfigs")}</p>
          ) : (
            <div className="s-proto-grid" role="listbox" aria-label={subT(lang, "pickProtocol")}>
              {protocolTabs.map((p) => {
                const countLabel = protoServersLabel(lang, p.count);
                return (
                  <button
                    key={p.id}
                    type="button"
                    role="option"
                    aria-selected={protoFilter === p.id}
                    className={`s-proto-card ${protoFilter === p.id ? "on" : ""}`}
                    onClick={() => setProtoFilter(p.id)}
                  >
                    <span className="s-proto-card-ico"><ProtoIcon proto={p.id} size={22} /></span>
                    <span className="s-proto-card-name">{protoLabel(lang, p.id)}</span>
                    {countLabel ? <span className="s-proto-card-count">{countLabel}</span> : null}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </section>

      {protoFilter !== "all" && filtered.length > 0 ? (
        <>
          {showPicker ? (
            <section className="s-panel s-server-picker">
              <div className="s-panel-head">
                <h2 className="s-panel-title">{subT(lang, "stepServer")}</h2>
                <span className="s-count">
                  {subT(lang, "serversFound").replace("{n}", String(visibleServers.length))}
                </span>
              </div>
              <div className="s-panel-body">
                <div className="s-server-toolbar">
                  <input
                    type="search"
                    className="s-server-search"
                    value={serverQuery}
                    onChange={(e) => setServerQuery(e.target.value)}
                    placeholder={subT(lang, "searchServers")}
                    aria-label={subT(lang, "searchServers")}
                  />
                  <div className="s-server-sort" role="group" aria-label="sort">
                    <button
                      type="button"
                      className={serverSort === "recommended" ? "on" : ""}
                      onClick={() => setServerSort("recommended")}
                    >
                      {subT(lang, "sortRecommended")}
                    </button>
                    <button
                      type="button"
                      className={serverSort === "name" ? "on" : ""}
                      onClick={() => setServerSort("name")}
                    >
                      {subT(lang, "sortName")}
                    </button>
                  </div>
                </div>

                {bestServer ? (
                  <button
                    type="button"
                    className={`s-server-auto ${selected?.id === bestServer.id ? "on" : ""}`}
                    onClick={() => pickServer(bestServer.id)}
                  >
                    <span className="s-server-auto-title">{subT(lang, "autoBestServer")}</span>
                    <span className="s-server-auto-meta">
                      {bestServer.flag} {bestServer.title}
                      {bestServer.latencyMs != null && bestServer.latencyMs >= 0
                        ? ` · ${subT(lang, "latencyMs").replace("{n}", formatLatencyMs(bestServer.latencyMs))}`
                        : ""}
                    </span>
                    <span className="s-server-auto-hint">{subT(lang, "autoBestHint")}</span>
                  </button>
                ) : null}

                {!visibleServers.length ? (
                  <p className="s-empty">{subT(lang, "noServerMatch")}</p>
                ) : (
                  <div className="s-server-groups">
                    {serversByRegion.map((group) => (
                      <div key={group.bucket} className="s-server-group">
                        <h3 className="s-server-group-title">{regionBucketLabel(lang, group.bucket)}</h3>
                        <div className="s-server-list" role="listbox" aria-label={regionBucketLabel(lang, group.bucket)}>
                          {group.items.map((c) => {
                            const tone = latencyTone(c.latencyMs);
                            return (
                              <button
                                key={c.id}
                                type="button"
                                role="option"
                                aria-selected={c.id === selected?.id}
                                className={`s-server-row ${c.id === selected?.id ? "on" : ""}`}
                                onClick={() => pickServer(c.id)}
                              >
                                <span className="s-server-row-main">
                                  {c.flag ? <span className="s-flag">{c.flag}</span> : null}
                                  <span className="s-td-name">{c.title}</span>
                                </span>
                                <span className={`s-lat s-lat-${tone}`}>
                                  {c.latencyMs != null && c.latencyMs >= 0
                                    ? subT(lang, "latencyMs").replace("{n}", formatLatencyMs(c.latencyMs))
                                    : subT(lang, "latencyUnknown")}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          ) : null}

          {selected && !showPicker ? (
            <section className="s-panel s-inspector s-inspector-merged">
              <div className="s-panel-head">
                <h2 className="s-panel-title">
                  {selected.flag ? <span className="s-flag">{selected.flag}</span> : null}
                  {" "}{selected.title}
                </h2>
                <div className="s-inspector-tools">
                  <span className="s-proto-label">
                    <ProtoIcon proto={selected.protocol} size={12} />
                    {protoLabel(lang, selected.protocol)}
                  </span>
                  {filtered.length > 1 ? (
                    <button type="button" className="s-btn s-btn-soft" onClick={() => setPickingServer(true)}>
                      {subT(lang, "changeServer")}
                    </button>
                  ) : null}
                </div>
              </div>
              <div className="s-panel-body">{configActions}</div>
            </section>
          ) : null}

          {selected && showPicker && filtered.length === 1 ? (
            <section className="s-panel s-inspector s-inspector-merged">
              <div className="s-panel-head">
                <h2 className="s-panel-title">
                  {selected.flag ? <span className="s-flag">{selected.flag}</span> : null}
                  {" "}{selected.title}
                </h2>
                <span className="s-proto-label">
                  <ProtoIcon proto={selected.protocol} size={12} />
                  {protoLabel(lang, selected.protocol)}
                </span>
              </div>
              <div className="s-panel-body">{configActions}</div>
            </section>
          ) : null}

          {selected && showPicker && filtered.length > 1 ? (
            <section className="s-panel s-inspector">
              <div className="s-panel-head">
                <h2 className="s-panel-title">{subT(lang, "stepConfig")}</h2>
              </div>
              <div className="s-panel-body">
                <div className="s-insp-name">
                  {selected.flag ? <span className="s-flag">{selected.flag}</span> : null}
                  <span>{selected.title}</span>
                </div>
                {configActions}
              </div>
            </section>
          ) : null}
        </>
      ) : protocolTabs.length ? (
        <p className="s-hint s-servers-hint">{subT(lang, "serversEmptyPick")}</p>
      ) : null}
    </div>
  );

  const importPanel = importUrl ? (
    <section className="s-panel s-import-panel">
      <div className="s-import-bar">
        <div>
          <h2 className="s-panel-title">{subT(lang, "sectionImport")}</h2>
          <p className="s-hint" style={{ marginTop: 8 }}>{subT(lang, "sectionImportHint")}</p>
        </div>
        <button type="button" className="s-apps-cta" onClick={() => goView("apps")}>
          {subT(lang, "goToApps")}
        </button>
        <div className="s-linkblock">
          <p className="s-label">{subT(lang, "oneLink")}</p>
          <div className="s-linkrow">
            <button
              type="button"
              className="s-linkin"
              dir="ltr"
              title={importUrl}
              aria-label={subT(lang, "oneLink")}
              onClick={() => void copyValue(importUrl)}
            >
              <span className="s-linkin-text">{importUrl}</span>
            </button>
            <button type="button" className="s-linkbtn" onClick={() => void copyValue(importUrl)}>
              {copied ? subT(lang, "copied") : subT(lang, "copy")}
            </button>
          </div>
          <p className="s-hint">{subT(lang, "afterCopyApps")}</p>
        </div>
      </div>
      <div className="s-panel-body s-import-qr">
        <div className="s-qr" style={{ width: "100%" }}>
          <div className="s-qr-frame">
            <QR value={importUrl} size={180} />
          </div>
          <span className="s-qr-hint">{subT(lang, "oneLinkHint")}</span>
        </div>
      </div>
    </section>
  ) : null;

  const appsPanel = importUrl ? (
    <section className="s-panel">
      <div className="s-panel-head">
        <h2 className="s-panel-title">{subT(lang, "sectionApps")}</h2>
      </div>
      <div className="s-panel-body">
        <p className="s-hint">{subT(lang, "sectionAppsHint")}</p>
        <div className="s-apps-grid">
          <div>
            <p className="s-label">{subT(lang, "yourPhone")}</p>
            <div className="s-devices" role="group" aria-label={subT(lang, "yourPhone")}>
              {PLATFORMS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={platform === p.id ? "on" : ""}
                  aria-pressed={platform === p.id}
                  onClick={() => setPlatform(p.id)}
                >
                  {platformLabel(lang, p.id)}
                </button>
              ))}
            </div>
          </div>
          <div>
            {primaryApp && (
              <div className="s-apps-block">
                <div className="s-app s-app-primary">
                  <div className="s-app-ico" style={{ background: primaryApp.color }}>{primaryApp.short}</div>
                  <div className="s-app-meta">
                    <div className="s-app-name">{primaryApp.name}</div>
                    <div className="s-app-tag">{subT(lang, "recommended")}</div>
                    <div className="s-app-actions">
                      {primaryApp.download?.[platform] && (
                        <a href={primaryApp.download[platform]} target="_blank" rel="noopener noreferrer" className="sub-btn-action">
                          {subT(lang, "downloadApp")}
                        </a>
                      )}
                      <button type="button" className="sub-btn-action sub-btn-action-main" disabled={busyConnect} onClick={connectPrimary}>
                        {busyConnect ? "…" : subT(lang, "importApp")}
                      </button>
                    </div>
                  </div>
                </div>
                {otherApps.length > 0 && (
                  <div className="s-more-apps">
                    <p className="s-label">{subT(lang, "otherApps")}</p>
                    {otherApps.map((a) => (
                      <SubAppTile
                        key={a.id}
                        app={a}
                        platform={platform}
                        subUrl={importUrl}
                        profileName={profileTitle}
                        importLabel={subT(lang, "importApp")}
                        downloadLabel={subT(lang, "downloadApp")}
                        pasteFallback={pasteFallback}
                        streisandHint={subT(lang, "streisandHint")}
                        clipboardHint={subT(lang, "clipboardHint")}
                        noResponse={subT(lang, "noAppResponse")}
                        onToast={showToast}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
            {wgApps.length > 0 && (
              <div className="s-apps-block s-apps-wg">
                <p className="s-label">{subT(lang, "wgAppsSection")}</p>
                <p className="s-hint">{subT(lang, "wgAppsSectionHint")}</p>
                <div className="s-more-apps">
                  {wgApps.map((a) => (
                    <SubWgAppTile key={a.id} app={a} platform={platform} downloadLabel={subT(lang, "downloadApp")} />
                  ))}
                </div>
              </div>
            )}
            <button type="button" className="s-btn s-btn-soft" style={{ marginTop: 12 }} onClick={() => goView("import")}>
              {subT(lang, "quickSetupImport")}
            </button>
          </div>
        </div>
      </div>
    </section>
  ) : null;

  return (
    <DashShell
      rtl={rtl}
      lang={lang}
      onPick={pickLang}
      brandName={brandName}
      brandLogo={brandLogo}
      view={view}
      onView={goView}
      serverCount={uniqueServerCount}
      chip={chip}
      configAvailable={configAvailable}
    >
      <div className={`s-view ${view === "overview" ? "on" : ""}`}>
        {overviewInfo}
        {!configAvailable && (
          <section className="s-alert" role="alert" style={{ marginTop: 10 }}>
            <p className="s-title">
              {blockReason === "data_limit" ? subT(lang, "quotaBannerTitle") :
               blockReason === "expired" ? subT(lang, "expiredBannerTitle") :
               subT(lang, "inactiveBannerTitle")}
            </p>
            <p className="s-muted">
              {blockReason === "data_limit" ? subT(lang, "quotaBannerBody") :
               blockReason === "expired" ? subT(lang, "expiredBannerBody") :
               subT(lang, "inactiveBannerBody")}
            </p>
          </section>
        )}
      </div>

      {configAvailable && (
        <>
          <div className={`s-view ${view === "servers" ? "on" : ""}`}>
            {serversView}
          </div>
          <div className={`s-view ${view === "import" ? "on" : ""}`}>
            {importPanel || <p className="s-empty">{subT(lang, "noConfigs")}</p>}
          </div>
          <div className={`s-view ${view === "apps" ? "on" : ""}`}>
            {appsPanel || <p className="s-empty">{subT(lang, "noConfigs")}</p>}
          </div>
        </>
      )}

      {toast && <div role="status" className={`s-toast ${toast.kind}`}>{toast.msg}</div>}

      {qrModal && selected && (
        <div className="s-modal" onClick={() => setQrModal(false)} role="dialog" aria-modal="true" aria-label={subT(lang, "scanHere")}>
          <div className="s-modal-box" onClick={(e) => e.stopPropagation()}>
            <p className="s-modal-name">{selected.flag} {selected.title}</p>
            <div className="s-qr-frame s-qr-lg">
              <QR value={selected.value} size={300} />
            </div>
            <button type="button" className="s-btn s-btn-main" style={{ width: "100%", marginTop: 12 }} onClick={() => setQrModal(false)}>
              {subT(lang, "close")}
            </button>
          </div>
        </div>
      )}
    </DashShell>
  );
}

type DashView = "overview" | "servers" | "import" | "apps";

function NavIcon({ name }: { name: DashView }) {
  const props = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.75, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (name === "overview") return <svg {...props}><path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z"/></svg>;
  if (name === "servers") return <svg {...props}><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01"/></svg>;
  if (name === "import") return <svg {...props}><path d="M12 3v12"/><path d="m8 11 4 4 4-4"/><path d="M5 19h14"/></svg>;
  return <svg {...props}><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M12 18h.01"/></svg>;
}

function DashShell({ children, rtl, lang, onPick, brandName = "NexusPanel", brandLogo, view, onView, serverCount, chip, configAvailable }: {
  children: React.ReactNode;
  rtl: boolean;
  lang: SubLang;
  onPick: (c: SubLang) => void;
  brandName?: string;
  brandLogo?: string;
  view: DashView;
  onView: (v: DashView) => void;
  serverCount: number;
  chip: { label: string; cls: string };
  configAvailable: boolean;
}) {
  const [theme, setTheme] = useState<SubTheme>("light");
  useEffect(() => { setTheme(detectSubTheme()); }, []);
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applySubTheme(next);
  };

  const navItems: { id: DashView; label: string; badge?: number }[] = [
    { id: "overview", label: subT(lang, "navOverview") },
    { id: "apps", label: subT(lang, "navApps") },
    { id: "import", label: subT(lang, "navImport") },
    { id: "servers", label: subT(lang, "navServers"), badge: serverCount },
  ];

  return (
    <div className="s-frame" dir={rtl ? "rtl" : "ltr"} lang={lang}>
      <header className="s-topbar">
        <div className="s-brand">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="s-mark" src={brandLogo || "/sub-assets/brand/nexuspanel-logo.png"} alt="" width={38} height={38} />
          <div className="s-brand-meta">
            <span className="s-brand-name">{brandName}</span>
            <span className="s-brand-sub">
              <span className={`s-pill ${chip.cls}`} style={{ padding: "2px 8px", verticalAlign: "middle" }}>
                <span className={`s-pill-dot ${chip.cls === "ok" && configAvailable ? "live" : ""}`} />
                {chip.label}
              </span>
            </span>
          </div>
        </div>
        <div className="s-tools">
          <button type="button" className="s-icon" onClick={toggle} aria-label="theme">
            {theme === "dark" ? (
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
            ) : (
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 14.5A8.5 8.5 0 1 1 9.5 3a7 7 0 0 0 11.5 11.5z"/></svg>
            )}
          </button>
          <div className="s-langs" role="group" aria-label={subT(lang, "lang")}>
            {SUB_LANGS.map((l) => (
              <button key={l.code} type="button" className={lang === l.code ? "on" : ""} onClick={() => onPick(l.code)}>
                {l.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="s-body">
        <div className="s-shell">
          <nav className="s-rail" aria-label="sections">
            <div className="s-rail-nav">
              {navItems.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`s-rail-btn ${view === item.id ? "on" : ""}`}
                  onClick={() => onView(item.id)}
                  title={item.label}
                  aria-label={item.label}
                  aria-current={view === item.id ? "page" : undefined}
                >
                  <span className="s-rail-ico"><NavIcon name={item.id} /></span>
                  <span className="s-rail-label">{item.label}</span>
                  {typeof item.badge === "number" && item.badge > 0 ? (
                    <span className="s-rail-badge">{item.badge}</span>
                  ) : null}
                </button>
              ))}
            </div>
          </nav>
          <main className="s-workspace">{children}</main>
        </div>
      </div>

      <nav className="s-mobile-nav" aria-label="mobile">
        {navItems.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`s-mnav-btn ${view === item.id ? "on" : ""}`}
            onClick={() => onView(item.id)}
            aria-current={view === item.id ? "page" : undefined}
          >
            <NavIcon name={item.id} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return <div className="s-card s-center"><p className="s-muted">{msg}</p></div>;
}

function SimpleShell({ children, rtl, lang, onPick }: {
  children: React.ReactNode; rtl: boolean; lang: SubLang; onPick: (c: SubLang) => void;
}) {
  return (
    <div className="s-frame" dir={rtl ? "rtl" : "ltr"} lang={lang}>
      <header className="s-topbar">
        <div className="s-brand">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="s-mark" src="/sub-assets/brand/nexuspanel-logo.png" alt="" width={38} height={38} />
          <span className="s-brand-name">NexusPanel</span>
        </div>
        <div className="s-tools">
          <div className="s-langs" role="group" aria-label={subT(lang, "lang")}>
            {SUB_LANGS.map((l) => (
              <button key={l.code} type="button" className={lang === l.code ? "on" : ""} onClick={() => onPick(l.code)}>
                {l.label}
              </button>
            ))}
          </div>
        </div>
      </header>
      <main className="s-workspace">{children}</main>
    </div>
  );
}

export default function SubscribePage() {
  return (
    <Suspense fallback={<div className="s-shell s-center" style={{ paddingTop: 40 }}>…</div>}>
      <SubscribeBody />
    </Suspense>
  );
}
