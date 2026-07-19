"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { SubAppTile } from "@/components/subscribe/SubAppTile";
import { SubWgAppTile } from "@/components/subscribe/SubWgAppTile";
import { QR } from "@/components/QR";
import { PLATFORMS, type Platform, type ClientApp, appsFor, detectPlatform } from "@/lib/apps";
import { wgAppsFor } from "@/lib/wg-apps";
import { copyToClipboard } from "@/lib/clipboard";
import { bytes, formatDate, relativeDays } from "@/lib/format";
import { SUB_LANGS, SubLang, detectSubLang, t as subT } from "@/lib/subscribe-i18n";
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
}

interface SubInfo {
  username: string;
  status: string;
  used_traffic: number;
  overage_traffic?: number;
  data_limit: number | null;
  expire: number | null;
  online_at?: string | null;
  links?: string[];
  link_items?: LinkItem[];
  proxies?: Record<string, unknown>;
  config_available?: boolean;
  block_reason?: string | null;
  public_subscription_url?: string;
  client_subscription_url?: string;
  subscription_profile_title?: string;
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
};

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

function ProtoBadge({ lang, proto, className = "" }: { lang: SubLang; proto: string; className?: string }) {
  return (
    <span className={`s-proto s-proto-${protoTone(proto)} ${className}`.trim()}>
      {protoLabel(lang, proto)}
    </span>
  );
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

function formatOnline(lang: SubLang, onlineAt: string | null | undefined): string {
  if (!onlineAt) return subT(lang, "neverOnline");
  const ts = new Date(onlineAt).getTime();
  if (Number.isNaN(ts)) return subT(lang, "neverOnline");
  const mins = Math.floor((Date.now() - ts) / 60000);
  if (mins < 3) return subT(lang, "onlineNow");
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
  const [showHowTo, setShowHowTo] = useState(false);
  const [busyConnect, setBusyConnect] = useState(false);
  const [wgConfByNode, setWgConfByNode] = useState<Record<number, string>>({});

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

  useEffect(() => {
    setLang(detectSubLang());
    const tok = getToken();
    setToken(tok);
    setPlatform(detectPlatform(typeof navigator !== "undefined" ? navigator.userAgent : ""));
    loadInfo(tok);
  }, [loadInfo]);

  const subUrl = useMemo(() => resolvePublicSubUrl(info, token, apiPrefix), [info, token, apiPrefix]);
  const importUrl = useMemo(
    () => resolveClientImportUrl(info, token, apiPrefix) || subUrl,
    [info, token, apiPrefix, subUrl],
  );
  const profileTitle = info?.subscription_profile_title?.trim() || "NexusPanel";

  const hasWireguard = !!info?.proxies && "wireguard" in info.proxies;
  const hasHysteria2 = !!info?.proxies && "hysteria2" in info.proxies;
  const hasTuic = !!info?.proxies && "tuic" in info.proxies;
  const hasAnytls = !!info?.proxies && "anytls" in info.proxies;
  const wgNodes = info?.wireguard_nodes ?? [];

  useEffect(() => {
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
      if (n.plain_available || n.wireguard_plain_uri || n.xray_available || n.wireguard_xray_uri) {
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
      }
    });
  }, [token, info, hasWireguard, wgNodes, apiPrefix]);

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
      ) => {
        if (!value && !downloadHref) return;
        out.push({ id, protocol, title, flag, value: value || downloadHref, downloadHref });
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
          // WireGuard app: QR/copy .conf; download .conf (not imported into Xray subs).
          if (hasPlain && (conf || plainUri)) {
            pushWg(
              `wg-${n.id}`,
              "wireguard",
              title,
              flag,
              conf || plainUri,
              resolveWgUrl(subUrl, "plain", n.id),
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
        if (hasHysteria2 && n.hysteria2_link) {
          out.push({ id: `hy2-${n.id}`, protocol: "hysteria2", title, flag: n.region_flag || undefined, value: n.hysteria2_link });
        }
        if (hasTuic && n.tuic_link) {
          out.push({ id: `tuic-${n.id}`, protocol: "tuic", title, flag: n.region_flag || undefined, value: n.tuic_link });
        }
        if (hasAnytls && n.anytls_link) {
          out.push({ id: `any-${n.id}`, protocol: "anytls", title, flag: n.region_flag || undefined, value: n.anytls_link });
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

  // Only show type filter when it actually helps (2+ types)
  const showTypeFilter = protocolTabs.length > 1;

  const filtered = useMemo(
    () => (protoFilter === "all" || !showTypeFilter ? configs : configs.filter((c) => c.protocol === protoFilter)),
    [configs, protoFilter, showTypeFilter],
  );

  useEffect(() => {
    if (!filtered.length) { setSelectedId(""); return; }
    if (!filtered.some((c) => c.id === selectedId)) setSelectedId(filtered[0].id);
  }, [filtered, selectedId]);

  const selected = filtered.find((c) => c.id === selectedId) || filtered[0] || null;

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
  const isPlainWireguard = selected?.protocol === "wireguard";
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
    return <Shell rtl={rtl} lang={lang} onPick={pickLang}><Empty msg={subT(lang, "fetchError")} /></Shell>;
  }
  if (err) {
    return (
      <Shell rtl={rtl} lang={lang} onPick={pickLang}>
        <div className="s-card s-center">
          <p className="s-title">{subT(lang, "fetchError")}</p>
          <button type="button" className="s-btn s-btn-main" onClick={() => loadInfo(token)}>{subT(lang, "refresh")}</button>
        </div>
      </Shell>
    );
  }
  if (!info) {
    return (
      <Shell rtl={rtl} lang={lang} onPick={pickLang}>
        <div className="s-skel" />
        <div className="s-skel s-skel-tall" />
      </Shell>
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
  const remainText = isUnlimited ? "" : bytes(left, 1);
  const remainParts = isUnlimited
    ? (() => {
        const usedText = bytes(used, 1);
        const m = usedText.match(/^([\d.]+)\s*(.*)$/);
        return m ? { num: m[1], unit: m[2] } : { num: usedText, unit: "" };
      })()
    : (() => {
        const m = remainText.match(/^([\d.]+)\s*(.*)$/);
        return m ? { num: m[1], unit: m[2] } : { num: remainText, unit: "" };
      })();
  const barTone = pct >= 100 ? "danger" : pct >= 85 ? "warn" : "ok";
  const onlineText = formatOnline(lang, info.online_at);
  const isOnlineNow = onlineText === subT(lang, "onlineNow");

  return (
    <Shell rtl={rtl} lang={lang} onPick={pickLang}>
      <section className={`s-card s-status s-status-${isUnlimited ? "ok" : barTone}${isUnlimited ? " s-status-unlimited" : ""}`}>
        <div className="s-status-glow" aria-hidden />
        <div className="s-status-top">
          <span className={`s-pill ${chip.cls}`}>
            <span className={`s-pill-dot ${chip.cls === "ok" && configAvailable ? "live" : ""}`} />
            {chip.label}
          </span>
          {isUnlimited ? (
            <span className="s-unlimited-badge">{subT(lang, "unlimited")}</span>
          ) : (
            <span className={`s-pct s-pct-${barTone}`}>{pct}%</span>
          )}
        </div>

        <div className="s-status-body">
          <div className="s-remain">
            <div className="s-remain-k">
              {subT(lang, isUnlimited ? "usedSoFar" : "remaining")}
            </div>
            <div className="s-remain-v" dir="ltr">
              <span className="s-remain-num">{remainParts.num}</span>
              {remainParts.unit ? <span className="s-remain-unit">{remainParts.unit}</span> : null}
            </div>
            {isUnlimited ? (
              <div className="s-remain-sub s-remain-sub-unlimited">
                <span className="s-remain-cap">{subT(lang, "unlimitedHint")}</span>
              </div>
            ) : (
              <>
                <div className="s-bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                  <div className={`s-bar-fill ${barTone}`} style={{ width: `${Math.max(pct, 2)}%` }} />
                </div>
                <div className="s-remain-sub" dir="ltr">
                  <span>{bytes(used, 1)}</span>
                  <span className="s-remain-sep">/</span>
                  <span>{bytes(total, 1)}</span>
                  <span className="s-remain-used">{subT(lang, "usedShort")}</span>
                  {overage > 0 ? (
                    <span className="s-overage">{subT(lang, "overage")} {bytes(overage, 1)}</span>
                  ) : null}
                </div>
              </>
            )}
          </div>

          <div className="s-meta">
            <div className="s-meta-tile">
              <span className="s-meta-ico" aria-hidden>
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="5" width="18" height="16" rx="2" />
                  <path d="M3 10h18M8 3v4M16 3v4" />
                </svg>
              </span>
              <div>
                <span className="s-meta-k">{subT(lang, "expire")}</span>
                <span className="s-meta-v">{expireText}</span>
                {info.expire ? <span className="s-meta-sub">{formatDate(info.expire)}</span> : null}
              </div>
            </div>
            <div className={`s-meta-tile ${isOnlineNow ? "live" : ""}`}>
              <span className="s-meta-ico" aria-hidden>
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M5 12.5a7 7 0 0 1 14 0" />
                  <path d="M8.5 12.5a3.5 3.5 0 0 1 7 0" />
                  <circle cx="12" cy="16" r="1.2" fill="currentColor" stroke="none" />
                </svg>
              </span>
              <div>
                <span className="s-meta-k">{subT(lang, "lastOnline")}</span>
                <span className="s-meta-v">
                  {isOnlineNow ? <span className="s-live-dot" /> : null}
                  {onlineText}
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {!configAvailable && (
        <section className="s-card s-alert">
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

      {configAvailable && (
        <section className="s-card s-servers">
          <div className="s-servers-head">
            <h2 className="s-title">{configs.length <= 1 ? subT(lang, "yourServer") : subT(lang, "pickServer")}</h2>
            {configs.length > 1 && (
              <span className="s-count">{subT(lang, "serversCount").replace("{n}", String(configs.length))}</span>
            )}
          </div>

          {showTypeFilter && (
            <div className="s-types" role="tablist" aria-label={subT(lang, "typeLabel")}>
              <button type="button" className={protoFilter === "all" ? "on" : ""} onClick={() => setProtoFilter("all")}>
                {subT(lang, "allTypes")}
              </button>
              {protocolTabs.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={`s-type-tab s-proto-${protoTone(p.id)} ${protoFilter === p.id ? "on" : ""}`}
                  onClick={() => setProtoFilter(p.id)}
                >
                  {protoLabel(lang, p.id)}
                </button>
              ))}
            </div>
          )}

          {!selected ? (
            <p className="s-muted s-center">{subT(lang, "noConfigs")}</p>
          ) : (
            <div className={`s-stage ${filtered.length > 1 ? "s-stage-split" : ""}`}>
              <div className="s-focus">
                <div className="s-focus-name">
                  {selected.flag ? <span className="s-flag">{selected.flag}</span> : null}
                  <span>{selected.title}</span>
                </div>
                <div className="s-focus-type">
                  <ProtoBadge lang={lang} proto={selected.protocol} />
                </div>

                <button type="button" className="s-qr" onClick={() => setQrModal(true)} aria-label={subT(lang, "tapBigger")}>
                  <div className="s-qr-frame">
                    <QR value={selected.value} size={280} />
                  </div>
                  <span className="s-qr-hint">{subT(lang, "scanHere")}</span>
                </button>

                {/* Plain WireGuard: download .conf only — keep WireGuard (Xray) copy CTA unchanged. */}
                {isPlainWireguard ? (
                  selected.downloadHref ? (
                    <button
                      type="button"
                      className="s-btn s-btn-main s-btn-xl"
                      onClick={() => void downloadConfFile(selected)}
                    >
                      {subT(lang, "downloadFile")}
                    </button>
                  ) : null
                ) : (
                  <>
                    <button type="button" className="s-btn s-btn-main s-btn-xl" onClick={() => copyValue(selected.value)}>
                      {copied ? subT(lang, "copied") : subT(lang, "copyForApp")}
                    </button>
                    {selected.downloadHref && (
                      <button
                        type="button"
                        className="s-btn s-btn-soft"
                        onClick={() => void downloadConfFile(selected)}
                      >
                        {subT(lang, "downloadFile")}
                      </button>
                    )}
                  </>
                )}

                {selected.protocol === "tuic" && <p className="s-warn">{subT(lang, "tuicWarn")}</p>}
              </div>

              {filtered.length > 1 && (
                <div className="s-list">
                  {filtered.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      className={`s-row ${c.id === selected.id ? "on" : ""}`}
                      onClick={() => setSelectedId(c.id)}
                    >
                      {c.flag ? <span className="s-flag">{c.flag}</span> : <span className="s-flag-ph" />}
                      <span className="s-row-title">{c.title}</span>
                      <ProtoBadge lang={lang} proto={c.protocol} className="s-row-type" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {configAvailable && importUrl && (
        <div className="s-howto">
          <button
            type="button"
            className={`s-howto-tog ${showHowTo ? "open" : ""}`}
            aria-expanded={showHowTo}
            onClick={() => setShowHowTo((v) => !v)}
          >
            <span className="s-howto-ico" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="5" y="2" width="14" height="20" rx="2" />
                <path d="M12 18h.01" />
              </svg>
            </span>
            <span className="s-howto-copy">
              <strong>{subT(lang, "howToTitle")}</strong>
              <small>{subT(lang, "howToHint")}</small>
            </span>
            <span className="s-howto-cta">
              <span className="s-howto-cta-label">{showHowTo ? subT(lang, "howToHide") : subT(lang, "howToShow")}</span>
              <span className="s-howto-chev" aria-hidden="true">{showHowTo ? "▴" : "▾"}</span>
            </span>
          </button>

          {showHowTo && (
            <div className="s-card s-howto-body">
              <p className="s-label">{subT(lang, "oneLink")}</p>
              <p className="s-muted" style={{ marginBottom: 8 }}>{subT(lang, "oneLinkHint")}</p>
              <div className="s-linkrow">
                <input readOnly dir="ltr" value={importUrl} className="s-linkin" onClick={(e) => (e.target as HTMLInputElement).select()} />
                <button type="button" className="s-linkbtn" onClick={() => copyValue(importUrl)}>{subT(lang, "copy")}</button>
              </div>

              <p className="s-label" style={{ marginTop: 16 }}>{subT(lang, "yourPhone")}</p>
              <div className="s-devices">
                {PLATFORMS.map((p) => (
                  <button key={p.id} type="button" className={platform === p.id ? "on" : ""} onClick={() => setPlatform(p.id)}>
                    {platformLabel(lang, p.id)}
                  </button>
                ))}
              </div>

              {primaryApp && (
                <>
                  <div className="s-app">
                    <div className="s-app-ico" style={{ background: primaryApp.color }}>{primaryApp.short}</div>
                    <div className="s-app-meta">
                      <div className="s-app-name">{primaryApp.name}</div>
                      <div className="s-app-tag">{subT(lang, "recommended")}</div>
                      <div className="s-app-actions">
                        {primaryApp.download?.[platform] && (
                          <a
                            href={primaryApp.download[platform]}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="sub-btn-action"
                          >
                            {subT(lang, "downloadApp")}
                          </a>
                        )}
                        <button
                          type="button"
                          className="sub-btn-action sub-btn-action-main"
                          disabled={busyConnect}
                          onClick={connectPrimary}
                        >
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
                </>
              )}

              {wgApps.length > 0 && (
                <div className="s-more-apps" style={{ marginTop: 16 }}>
                  <p className="s-label">{subT(lang, "wgApps")}</p>
                  <p className="s-muted" style={{ marginBottom: 8 }}>{subT(lang, "wgAppsHint")}</p>
                  {wgApps.map((a) => (
                    <SubWgAppTile
                      key={a.id}
                      app={a}
                      platform={platform}
                      downloadLabel={subT(lang, "downloadApp")}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <footer className="s-foot">{subT(lang, "footer")}</footer>
      {toast && <div role="status" className={`s-toast ${toast.kind}`}>{toast.msg}</div>}

      {qrModal && selected && (
        <div className="s-modal" onClick={() => setQrModal(false)} role="dialog" aria-modal="true">
          <div className="s-modal-box" onClick={(e) => e.stopPropagation()}>
            <p className="s-modal-name">{selected.flag} {selected.title}</p>
            <div className="s-qr-frame s-qr-lg">
              <QR value={selected.value} size={340} />
            </div>
            <button type="button" className="s-btn s-btn-main" style={{ width: "100%", marginTop: 14 }} onClick={() => setQrModal(false)}>
              {subT(lang, "close")}
            </button>
          </div>
        </div>
      )}
    </Shell>
  );
}

function Shell({ children, rtl, lang, onPick }: {
  children: React.ReactNode; rtl: boolean; lang: SubLang; onPick: (c: SubLang) => void;
}) {
  const [theme, setTheme] = useState<SubTheme>("light");
  useEffect(() => { setTheme(detectSubTheme()); }, []);
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applySubTheme(next);
  };

  return (
    <main className="s-shell" dir={rtl ? "rtl" : "ltr"} lang={lang}>
      <header className="s-top">
        <div className="s-brand">
          <img className="s-mark" src="/sub-assets/brand/nexuspanel-logo.png" alt="" width={28} height={28} />
          <span className="s-brand-name">NexusPanel</span>
        </div>
        <div className="s-tools">
          <button type="button" className="s-icon" onClick={toggle} aria-label="theme">
            {theme === "dark" ? (
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
            ) : (
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 14.5A8.5 8.5 0 1 1 9.5 3a7 7 0 0 0 11.5 11.5z"/></svg>
            )}
          </button>
          <div className="s-langs">
            {SUB_LANGS.map((l) => (
              <button key={l.code} type="button" className={lang === l.code ? "on" : ""} onClick={() => onPick(l.code)}>
                {l.label}
              </button>
            ))}
          </div>
        </div>
      </header>
      {children}
    </main>
  );
}

function Empty({ msg }: { msg: string }) {
  return <div className="s-card s-center"><p className="s-muted">{msg}</p></div>;
}

export default function SubscribePage() {
  return (
    <Suspense fallback={<div className="s-shell s-center" style={{ paddingTop: 40 }}>…</div>}>
      <SubscribeBody />
    </Suspense>
  );
}
