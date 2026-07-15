/** Helpers for NexusPanel Xray config UI (3x-ui parity). */

/** Inbounds that panel users can be assigned to. */
export const PRODUCT_INBOUND_PROTOCOLS = [
  "vless",
  "vmess",
  "trojan",
  "shadowsocks",
] as const;

/** Xray-only listeners — no user assignment; use Tunnels page for dokodemo relay. */
export const ADVANCED_INBOUND_PROTOCOLS = [
  "http",
  "socks",
  "mixed",
  "wireguard",
  "hysteria",
  "amneziawg",
  "tun",
  "dokodemo-door",
] as const;

export const INBOUND_PROTOCOLS = [
  ...PRODUCT_INBOUND_PROTOCOLS,
  ...ADVANCED_INBOUND_PROTOCOLS,
] as const;

export const PROXY_PROTOCOLS = ["vless", "vmess", "trojan"] as const;
export const NETWORKS = [
  "tcp",
  "kcp",
  "ws",
  "grpc",
  "http",
  "h2",
  "httpupgrade",
  "splithttp",
  "xhttp",
  "quic",
] as const;
export const SS_LEGACY_METHODS = [
  "chacha20-ietf-poly1305",
  "aes-256-gcm",
  "aes-128-gcm",
  "aes-192-gcm",
] as const;

export const SS_2022_METHODS = [
  "2022-blake3-aes-256-gcm",
  "2022-blake3-aes-128-gcm",
  "2022-blake3-chacha20-poly1305",
] as const;

export const SS_METHODS = [...SS_LEGACY_METHODS, ...SS_2022_METHODS];

export function isSs2022(method: string): boolean {
  return method.startsWith("2022-blake3");
}
export const SS_NETWORKS = ["tcp", "udp", "tcp,udp"] as const;
export const LOG_LEVELS = ["none", "debug", "info", "warning", "error"];
export const DOMAIN_STRATEGIES = ["AsIs", "IPIfNonMatch", "IPOnDemand"];
export const VLESS_FLOWS = ["", "xtls-rprx-vision"];
export const SECURITIES = ["none", "tls", "reality"] as const;
export const FINGERPRINTS = [
  "",
  "chrome",
  "firefox",
  "safari",
  "ios",
  "android",
  "edge",
  "qq",
  "random",
  "randomized",
];
export const TLS_VERSIONS = ["", "1.0", "1.1", "1.2", "1.3"] as const;
export const TLS_CIPHER_MODES = ["", "auto"] as const;
export const TLS_CERT_USAGE = ["encipherment", "verify", "issue"] as const;
export const ALPN_OPTIONS = ["h3", "h2", "http/1.1", "http/1.0"] as const;
export const HOST_ALPN_PRESETS = ["", "h3", "h2", "http/1.1", "h2,http/1.1", "h3,h2,http/1.1"] as const;
export const HOST_FINGERPRINT_PRESETS = [
  "",
  "chrome",
  "firefox",
  "safari",
  "ios",
  "android",
  "edge",
  "random",
  "randomized",
] as const;
export const INBOUND_TRANSMISSIONS = [
  { value: "tcp", label: "RAW" },
  { value: "kcp", label: "mKCP" },
  { value: "ws", label: "WebSocket" },
  { value: "grpc", label: "gRPC" },
  { value: "httpupgrade", label: "HTTPUpgrade" },
  { value: "splithttp", label: "SplitHTTP" },
  { value: "xhttp", label: "XHTTP" },
  { value: "http", label: "H2-HTTP" },
  { value: "h2", label: "HTTP/2" },
  { value: "quic", label: "QUIC" },
] as const;
export const KEY_GEN_TYPES = [
  { value: "none", label: "None" },
  { value: "x25519", label: "X25519 (native)" },
] as const;
export const SOCKOPT_REAL_IP = [
  { value: "direct", label: "Off / direct" },
  { value: "cloudflare", label: "Cloudflare CDN" },
  { value: "proxy", label: "L4 relay / Spectrum (PROXY)" },
] as const;
export const TPROXY_MODES = ["", "off", "redirect", "tproxy"] as const;
export const TCP_CONGESTION = ["", "bbr", "cubic", "reno"] as const;
export const SNIFF_OVERRIDES = ["http", "tls", "quic", "fakedns"];
export const KCP_HEADERS = ["none", "srtp", "utp", "wechat-video", "dtls", "wireguard"];
const SYSTEM_TAGS = new Set(["API_INBOUND", "API", "TUN_IN", "metrics_in"]);

/** Xray wireguard JSON marker — ignored by Xray, used by NexusPanel UI. */
export const NXPANEL_INBOUND_KIND = "nexusPanelKind";

export function isAmneziaInbound(i: {
  protocol?: string;
  tag?: string;
  settings?: unknown;
}): boolean {
  const settings = (i.settings || {}) as Record<string, unknown>;
  if (settings[NXPANEL_INBOUND_KIND] === "amneziawg") return true;
  const proto = String(i.protocol || "");
  const tag = String(i.tag || "");
  return proto === "amneziawg" || (proto === "wireguard" && /amnezia|awg/i.test(tag));
}

export function supportsStream(protocol: string): boolean {
  return (
    PROXY_PROTOCOLS.includes(protocol as (typeof PROXY_PROTOCOLS)[number]) ||
    protocol === "shadowsocks"
  );
}

export function isUserInbound(i: { protocol?: string; tag?: string }): boolean {
  if (!i?.protocol) return false;
  if (i.tag && SYSTEM_TAGS.has(i.tag)) return false;
  if (i.protocol === "dokodemo-door" && i.tag === "API_INBOUND") return false;
  return INBOUND_PROTOCOLS.includes(i.protocol as (typeof INBOUND_PROTOCOLS)[number]);
}

/** Inbounds stored in xray_config.json that the panel UI may list and delete. */
export function isManageableInbound(i: { protocol?: string; tag?: string }): boolean {
  const tag = String(i?.tag || "").trim();
  if (!tag || SYSTEM_TAGS.has(tag)) return false;
  if (i?.protocol === "dokodemo-door" && tag === "API_INBOUND") return false;
  return !!i?.protocol;
}

/** Label for inbound table/UI (amneziawg stored as wireguard in JSON). */
export function inboundDisplayProtocol(i: {
  protocol?: string;
  tag?: string;
  settings?: unknown;
}): string {
  if (isAmneziaInbound(i)) return "amneziawg";
  return String(i.protocol || "");
}

export function inboundTransportLabel(i: Record<string, unknown>): string {
  const ss = (i.streamSettings || {}) as Record<string, unknown>;
  const proto = String(i.protocol || "");
  if (isAmneziaInbound(i)) return "AWG";
  if (proto === "hysteria" || ss.network === "hysteria") return "HYSTERIA";
  if (proto === "wireguard") return "WG";
  if (proto === "tun") return "TUN";
  if (proto === "dokodemo-door") return "TUNNEL";
  if (proto === "http" || proto === "socks" || proto === "mixed") return proto.toUpperCase();
  const net = String(ss.network || (proto === "shadowsocks" ? "tcp" : "—"));
  return networkLabel(net);
}

export function networkLabel(network: string): string {
  const n = (network || "tcp").toLowerCase();
  if (n === "httpupgrade") return "HTTPUpgrade";
  if (n === "splithttp") return "SplitHTTP";
  if (n === "xhttp") return "XHTTP";
  return n.toUpperCase();
}

function b64url(bytes: Uint8Array): string {
  const s = btoa(String.fromCharCode(...bytes));
  return s.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function generateRealityKeypair(): Promise<{ privateKey: string; publicKey: string }> {
  if (!globalThis.crypto?.subtle) throw new Error("Web Crypto unavailable");
  const keyPair = (await crypto.subtle.generateKey(
    { name: "X25519" },
    true,
    ["deriveBits"],
  )) as CryptoKeyPair;
  const privPkcs8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", keyPair.privateKey));
  const priv = privPkcs8.slice(-32);
  const pub = new Uint8Array(await crypto.subtle.exportKey("raw", keyPair.publicKey));
  return { privateKey: b64url(priv), publicKey: b64url(pub) };
}

export function randomShortId(): string {
  const b = new Uint8Array(4);
  crypto.getRandomValues(b);
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

export function ensureConfigShape(cfg: Record<string, unknown>): Record<string, unknown> {
  const c = { ...cfg };
  if (!c.log) c.log = { loglevel: "warning" };
  if (!c.routing) c.routing = { domainStrategy: "AsIs", rules: [] };
  const routing = c.routing as Record<string, unknown>;
  if (!routing.rules) routing.rules = [];
  if (!c.outbounds) {
    c.outbounds = [
      { protocol: "freedom", tag: "DIRECT" },
      { protocol: "blackhole", tag: "BLOCK" },
    ];
  }
  if (!c.inbounds) c.inbounds = [];
  if (!c.dns) {
    c.dns = {
      servers: ["https://1.1.1.1/dns-query", "1.1.1.1", "8.8.8.8"],
      queryStrategy: "UseIPv4",
    };
  } else {
    const dns = c.dns as Record<string, unknown>;
    const servers = dns.servers as unknown[] | undefined;
    if (!servers || servers.length === 0) {
      dns.servers = ["https://1.1.1.1/dns-query", "1.1.1.1", "8.8.8.8"];
      dns.queryStrategy = dns.queryStrategy || "UseIPv4";
    }
  }
  return c;
}

/** DNS + Cloudflare bypass rules required for stable WARP routing. */
export const WARP_BYPASS_RULE: Record<string, unknown> = {
  type: "field",
  domain: [
    "domain:engage.cloudflareclient.com",
    "domain:cloudflareclient.com",
    "domain:cloudflare.com",
  ],
  outboundTag: "DIRECT",
};

export function usesWarpRouting(cfg: Record<string, unknown>): boolean {
  const routing = (cfg.routing || {}) as Record<string, unknown>;
  const rules = (routing.rules || []) as Record<string, unknown>[];
  return rules.some((r) => {
    const tag = String(r.outboundTag || "");
    return tag === "warp" || tag.startsWith("warp-");
  });
}

export function applyWarpSafeRouting(cfg: Record<string, unknown>): Record<string, unknown> {
  const next = ensureConfigShape(cfg);
  const routing = next.routing as Record<string, unknown>;
  routing.domainStrategy = routing.domainStrategy || "IPIfNonMatch";
  const rules = [...((routing.rules || []) as Record<string, unknown>[])];
  const hasBypass = rules.some((r) => {
    const dom = r.domain as string[] | undefined;
    return Array.isArray(dom) && dom.some((d) => String(d).includes("cloudflareclient"));
  });
  if (!hasBypass) {
    const warpIdx = rules.findIndex((r) => String(r.outboundTag || "") === "warp");
    const insertAt = warpIdx >= 0 ? warpIdx : rules.length;
    rules.splice(insertAt, 0, { ...WARP_BYPASS_RULE });
  }
  routing.rules = rules;
  const outbounds = (next.outbounds || []) as Record<string, unknown>[];
  next.outbounds = outbounds.map((ob) => {
    if (String(ob.tag || "") !== "warp" || ob.protocol !== "wireguard") return ob;
    const settings = { ...((ob.settings || {}) as Record<string, unknown>) };
    if (settings.workers == null) settings.workers = 2;
    return { ...ob, settings };
  });
  return next;
}

export const DEFAULT_HYSTERIA_INBOUND_TAG = "Hysteria2";
export const DEFAULT_AMNEZIA_INBOUND_TAG = "AmneziaWG";

export function defaultHysteriaInbound(
  tag = DEFAULT_HYSTERIA_INBOUND_TAG,
  port = "44333",
): Record<string, unknown> {
  const p = parseInt(port, 10) || 44333;
  return {
    tag,
    listen: "0.0.0.0",
    port: p,
    protocol: "hysteria",
    settings: { version: 2, clients: [] },
    streamSettings: {
      network: "hysteria",
      security: "tls",
      tlsSettings: { alpn: ["h3"] },
      hysteriaSettings: { version: 2 },
    },
  };
}

export function defaultAmneziaInbound(
  tag = DEFAULT_AMNEZIA_INBOUND_TAG,
  port = "51821",
): Record<string, unknown> {
  const p = parseInt(port, 10) || 51821;
  return {
    tag,
    listen: "0.0.0.0",
    port: p,
    protocol: "wireguard",
    settings: {
      secretKey: "",
      mtu: 1420,
      peers: [],
      [NXPANEL_INBOUND_KIND]: "amneziawg",
    },
  };
}

const toStrArray = (v: unknown): string[] => {
  if (Array.isArray(v)) return v.map((x) => String(x));
  if (typeof v === "string" && v) return [v];
  return [];
};

function routingRuleInboundTags(config: Record<string, unknown>): string[] {
  const routing = (config.routing || {}) as Record<string, unknown>;
  const rules = (routing.rules || []) as Record<string, unknown>[];
  const out: string[] = [];
  for (const r of rules) {
    out.push(...toStrArray(r.inboundTag));
  }
  return out;
}

/** Inbound tags available for routing rules (actual Xray inbounds + tags already used in rules). */
export function listRoutingInboundTags(config: Record<string, unknown>): string[] {
  const tags = new Set<string>();

  const inbounds = (config.inbounds || []) as Record<string, unknown>[];
  for (const i of inbounds) {
    const tag = String(i.tag || "").trim();
    if (!tag || SYSTEM_TAGS.has(tag)) continue;
    tags.add(tag);
  }

  for (const t of routingRuleInboundTags(config)) {
    if (t.trim()) tags.add(t.trim());
  }

  return [...tags].sort((a, b) => a.localeCompare(b));
}

export function hasInboundTag(config: Record<string, unknown>, tag: string): boolean {
  const inbounds = (config.inbounds || []) as Record<string, unknown>[];
  return inbounds.some((i) => String(i.tag || "") === tag);
}

export function appendInboundIfMissing(
  config: Record<string, unknown>,
  inbound: Record<string, unknown>,
): Record<string, unknown> {
  const tag = String(inbound.tag || "");
  if (!tag || hasInboundTag(config, tag)) return config;
  const inbounds = [...((config.inbounds || []) as Record<string, unknown>[]), inbound];
  return { ...config, inbounds };
}

export const RULE_PROTOCOLS = ["http", "tls", "quic", "bittorrent"] as const;
export const RULE_NETWORKS = ["", "tcp", "udp", "tcp,udp"] as const;

export type RuleAttr = { key: string; value: string };

export type RoutingRuleForm = {
  type: string;
  outboundTag: string;
  balancerTag: string;
  inboundTag: string[];
  ip: string;
  domain: string;
  port: string;
  sourcePort: string;
  network: string;
  protocol: string[];
  sourceIP: string;
  user: string;
  vlessRoute: string;
  attrs: RuleAttr[];
  ruleTag: string;
};

export const defaultRule = (): RoutingRuleForm => ({
  type: "field",
  outboundTag: "",
  balancerTag: "",
  inboundTag: [],
  ip: "",
  domain: "",
  port: "",
  sourcePort: "",
  network: "",
  protocol: [],
  sourceIP: "",
  user: "",
  vlessRoute: "",
  attrs: [],
  ruleTag: "",
});

export function ruleToForm(r: Record<string, unknown>): RoutingRuleForm {
  const attrsObj = (r.attrs && typeof r.attrs === "object" && !Array.isArray(r.attrs))
    ? (r.attrs as Record<string, unknown>)
    : {};
  return {
    type: String(r.type || "field"),
    outboundTag: String(r.outboundTag || ""),
    balancerTag: String(r.balancerTag || ""),
    inboundTag: toStrArray(r.inboundTag),
    ip: toStrArray(r.ip).join(","),
    domain: toStrArray(r.domain).join(","),
    port: r.port != null ? String(r.port) : "",
    sourcePort: r.sourcePort != null ? String(r.sourcePort) : "",
    network: String(r.network || ""),
    protocol: toStrArray(r.protocol),
    sourceIP: toStrArray(r.sourceIP ?? r.source).join(","),
    user: toStrArray(r.user).join(","),
    vlessRoute: r.vlessRoute != null ? String(r.vlessRoute) : "",
    attrs: Object.entries(attrsObj).map(([key, value]) => ({ key, value: String(value) })),
    ruleTag: String(r.ruleTag || ""),
  };
}

export function buildRuleFromForm(f: RoutingRuleForm): Record<string, unknown> {
  const r: Record<string, unknown> = { type: f.type || "field" };
  const splitList = (s: string) => s.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

  if (f.ruleTag.trim()) r.ruleTag = f.ruleTag.trim();
  if (f.sourceIP.trim()) r.sourceIP = splitList(f.sourceIP);
  if (f.sourcePort.trim()) r.sourcePort = f.sourcePort.trim();
  if (f.vlessRoute.trim()) r.vlessRoute = f.vlessRoute.trim();
  if (f.network) r.network = f.network;
  if (f.protocol.length) r.protocol = [...f.protocol];
  const attrEntries = f.attrs.filter((a) => a.key.trim());
  if (attrEntries.length) {
    r.attrs = Object.fromEntries(attrEntries.map((a) => [a.key.trim(), a.value]));
  }
  if (f.inboundTag.length) r.inboundTag = [...f.inboundTag];
  if (f.ip.trim()) r.ip = splitList(f.ip);
  if (f.domain.trim()) r.domain = splitList(f.domain);
  if (f.user.trim()) r.user = splitList(f.user);
  if (f.port.trim()) r.port = f.port.trim();
  if (f.balancerTag.trim()) r.balancerTag = f.balancerTag.trim();
  else if (f.outboundTag) r.outboundTag = f.outboundTag;
  return r;
}

export function socksEndpointFromSettings(settings: unknown): { address: string; port: string } {
  const s = (settings || {}) as Record<string, unknown>;
  const servers = s.servers;
  if (Array.isArray(servers) && servers[0] && typeof servers[0] === "object") {
    const srv = servers[0] as Record<string, unknown>;
    return { address: String(srv.address || ""), port: String(srv.port ?? "1080") };
  }
  return { address: String(s.address || ""), port: String(s.port ?? "1080") };
}

/* ---- Outbound builders — see outboundHelpers.ts (3x-ui parity) ---- */
export {
  OUTBOUND_NETWORKS,
  OUTBOUND_PROTOCOLS,
  OUTBOUND_SECURITIES,
  buildOutboundFromForm,
  defaultOutboundForm,
  finalizeOutboundFromForm,
  outboundSummary,
  outboundSupportsStream,
  outboundToForm,
  sanitizeConfigOutbounds,
  validateOutboundTag,
  warpOutboundForm,
  type OutboundForm,
} from "./outboundHelpers";

/** @deprecated use INBOUND_PROTOCOLS */
export const USER_PROTOCOLS = INBOUND_PROTOCOLS;
