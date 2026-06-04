/** Helpers for NexusPanel Xray config UI (3x-ui parity). */

export const INBOUND_PROTOCOLS = [
  "vless",
  "vmess",
  "trojan",
  "shadowsocks",
  "http",
  "socks",
  "mixed",
  "wireguard",
  "dokodemo-door",
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
  "quic",
] as const;
export const SS_METHODS = [
  "chacha20-ietf-poly1305",
  "aes-256-gcm",
  "aes-128-gcm",
  "aes-128-ctr",
  "aes-192-gcm",
  "chacha20-poly1305",
];
export const SS_NETWORKS = ["tcp", "udp", "tcp,udp"] as const;
export const LOG_LEVELS = ["none", "debug", "info", "warning", "error"];
export const DOMAIN_STRATEGIES = ["AsIs", "IPIfNonMatch", "IPOnDemand"];
export const VLESS_FLOWS = ["", "xtls-rprx-vision", "xtls-rprx-vision-udp443"];
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
export const SNIFF_OVERRIDES = ["http", "tls", "quic", "fakedns"];
export const KCP_HEADERS = ["none", "srtp", "utp", "wechat-video", "dtls", "wireguard"];
export const OUTBOUND_PROTOCOLS = [
  "freedom",
  "blackhole",
  "socks",
  "http",
  "vless",
  "vmess",
  "trojan",
  "shadowsocks",
  "wireguard",
] as const;

const SYSTEM_TAGS = new Set(["API_INBOUND", "API", "TUN_IN", "metrics_in"]);

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
  if (!c.dns) c.dns = { servers: [] };
  return c;
}

export type FallbackForm = {
  dest: string;
  path: string;
  xver: string;
  alpn: string;
  name: string;
};

export type InboundForm = {
  tag: string;
  listen: string;
  port: string;
  protocol: string;
  network: string;
  path: string;
  host: string;
  method: string;
  ssNetwork: string;
  security: string;
  sni: string;
  alpn: string;
  fingerprint: string;
  allowInsecure: boolean;
  realityDest: string;
  realityServerNames: string;
  realityPrivateKey: string;
  realityPublicKey: string;
  realityShortIds: string;
  realitySpiderX: string;
  realityXver: string;
  sniffing: boolean;
  sniffDestOverride: string;
  flow: string;
  kcpSeed: string;
  kcpHeader: string;
  grpcMultiMode: boolean;
  xhttpMode: string;
  tunnelAddress: string;
  tunnelPort: string;
  tunnelNetwork: string;
  tunnelFollowRedirect: boolean;
  wgSecretKey: string;
  wgPeerPublicKey: string;
  wgAllowedIPs: string;
  wgMtu: string;
  fallbacks: FallbackForm[];
};

export const emptyFallback = (): FallbackForm => ({ dest: "", path: "", xver: "0", alpn: "", name: "" });

export function supportsFallback(protocol: string): boolean {
  return protocol === "vless" || protocol === "trojan";
}

export const defaultInboundForm = (): InboundForm => ({
  tag: "",
  listen: "0.0.0.0",
  port: "443",
  protocol: "vless",
  network: "tcp",
  path: "/",
  host: "",
  method: SS_METHODS[0],
  ssNetwork: "tcp,udp",
  security: "none",
  sni: "",
  alpn: "",
  fingerprint: "chrome",
  allowInsecure: false,
  realityDest: "",
  realityServerNames: "",
  realityPrivateKey: "",
  realityPublicKey: "",
  realityShortIds: "",
  realitySpiderX: "",
  realityXver: "0",
  sniffing: true,
  sniffDestOverride: "http,tls,quic",
  flow: "",
  kcpSeed: "",
  kcpHeader: "none",
  grpcMultiMode: false,
  xhttpMode: "auto",
  tunnelAddress: "",
  tunnelPort: "0",
  tunnelNetwork: "tcp,udp",
  tunnelFollowRedirect: false,
  wgSecretKey: "",
  wgPeerPublicKey: "",
  wgAllowedIPs: "0.0.0.0/0",
  wgMtu: "1420",
  fallbacks: [],
});

function readStreamHints(ss: Record<string, unknown>): {
  network: string;
  path: string;
  host: string;
  kcpSeed: string;
  kcpHeader: string;
} {
  const network = String(ss.network || "tcp");
  let path = "/";
  let host = "";
  let kcpSeed = "";
  let kcpHeader = "none";
  if (network === "ws") {
    const ws = (ss.wsSettings || {}) as Record<string, unknown>;
    path = String(ws.path || "/");
    host = String(((ws.headers as Record<string, unknown>)?.Host) || "");
  } else if (network === "grpc") {
    const g = (ss.grpcSettings || {}) as Record<string, unknown>;
    path = String(g.serviceName || "");
  } else if (network === "http" || network === "h2") {
    const h = (ss.httpSettings || ss.httpSettings || {}) as Record<string, unknown>;
    path = String(h.path || "/");
    host = String(h.host || "");
  } else if (network === "httpupgrade") {
    const u = (ss.httpupgradeSettings || {}) as Record<string, unknown>;
    path = String(u.path || "/");
    host = String(u.host || "");
  } else if (network === "splithttp") {
    const x = (ss.splithttpSettings || ss.xhttpSettings || {}) as Record<string, unknown>;
    path = String(x.path || "/");
    host = String(x.host || "");
  } else if (network === "kcp") {
    const k = (ss.kcpSettings || {}) as Record<string, unknown>;
    const hdr = (k.header || {}) as Record<string, unknown>;
    kcpSeed = String(k.seed || "");
    kcpHeader = String(hdr.type || "none");
  } else if (network === "quic") {
    const q = (ss.quicSettings || {}) as Record<string, unknown>;
    const hdr = (q.header || {}) as Record<string, unknown>;
    path = String(q.key || "");
    host = String(hdr.type || "");
  }
  return { network, path, host, kcpSeed, kcpHeader };
}

export function inboundToForm(i: Record<string, unknown>): InboundForm {
  const ss = (i.streamSettings || {}) as Record<string, unknown>;
  const sec = (ss.security as string) || "none";
  const rs = (ss.realitySettings || {}) as Record<string, unknown>;
  const ts = (ss.tlsSettings || ss.tls || {}) as Record<string, unknown>;
  const sniff = i.sniffing as Record<string, unknown> | undefined;
  const settings = (i.settings || {}) as Record<string, unknown>;
  const clients = (settings.clients as unknown[]) || [];
  const flow =
    clients[0] && typeof clients[0] === "object"
      ? String((clients[0] as Record<string, unknown>).flow || "")
      : "";

  const stream = readStreamHints(ss);
  const grpc = (ss.grpcSettings || {}) as Record<string, unknown>;
  const xhttp = (ss.splithttpSettings || ss.xhttpSettings || {}) as Record<string, unknown>;

  const sniffOverride = Array.isArray(sniff?.destOverride)
    ? (sniff.destOverride as string[]).join(",")
    : "http,tls,quic";

  const f = defaultInboundForm();
  f.tag = String(i.tag || "");
  f.listen = typeof i.listen === "string" ? i.listen : "0.0.0.0";
  f.port = String(i.port || "");
  f.protocol = String(i.protocol || "vless");
  f.network = stream.network;
  f.path = stream.path;
  f.host = stream.host;
  f.kcpSeed = stream.kcpSeed;
  f.kcpHeader = stream.kcpHeader;
  f.method = String(settings.method || settings.cipher || SS_METHODS[0]);
  f.ssNetwork = String(settings.network || "tcp,udp");
  f.security = sec;
  f.sni = String(
    ts.serverName ||
      (Array.isArray(rs.serverNames) ? (rs.serverNames as string[])[0] : "") ||
      "",
  );
  f.alpn = Array.isArray(ts.alpn) ? (ts.alpn as string[]).join(",") : "";
  f.fingerprint = String(ts.fingerprint || rs.fingerprint || "");
  f.allowInsecure = Boolean(ts.allowInsecure);
  f.realityDest = String(rs.dest || "");
  f.realityServerNames = Array.isArray(rs.serverNames) ? (rs.serverNames as string[]).join(",") : "";
  f.realityPrivateKey = String(rs.privateKey || "");
  f.realityPublicKey = String(rs.publicKey || "");
  f.realityShortIds = Array.isArray(rs.shortIds) ? (rs.shortIds as string[]).join(",") : "";
  f.realitySpiderX = String(rs.spiderX || "");
  f.realityXver = String(rs.xver ?? "0");
  f.sniffing = sniff?.enabled !== false;
  f.sniffDestOverride = sniffOverride;
  f.flow = flow;
  f.grpcMultiMode = Boolean(grpc.multiMode);
  f.xhttpMode = String(xhttp.mode || "auto");

  const rawFallbacks = settings.fallbacks;
  if (Array.isArray(rawFallbacks)) {
    f.fallbacks = rawFallbacks.map((raw) => {
      const fb = (raw || {}) as Record<string, unknown>;
      return {
        dest: fb.dest === undefined || fb.dest === null ? "" : String(fb.dest),
        path: String(fb.path || ""),
        xver: String(fb.xver ?? "0"),
        alpn: String(fb.alpn || ""),
        name: String(fb.name || ""),
      };
    });
  }

  if (f.protocol === "dokodemo-door") {
    const addr = settings.address as string | undefined;
    f.tunnelAddress = typeof addr === "string" ? addr : "";
    f.tunnelPort = String(settings.port ?? "0");
    f.tunnelNetwork = String(settings.network || "tcp,udp");
    f.tunnelFollowRedirect = Boolean(settings.followRedirect);
  }
  if (f.protocol === "wireguard") {
    const peers = (settings.peers as Record<string, unknown>[]) || [];
    f.wgSecretKey = String(settings.secretKey || "");
    f.wgMtu = String(settings.mtu || "1420");
    if (peers[0]) {
      f.wgPeerPublicKey = String(peers[0].publicKey || "");
      f.wgAllowedIPs = Array.isArray(peers[0].allowedIPs)
        ? (peers[0].allowedIPs as string[]).join(",")
        : "0.0.0.0/0";
    }
  }
  return f;
}

function applyTransport(stream: Record<string, unknown>, f: InboundForm) {
  stream.network = f.network;
  if (f.network === "ws") {
    stream.wsSettings = {
      path: f.path || "/",
      headers: f.host ? { Host: f.host } : undefined,
    };
  } else if (f.network === "grpc") {
    stream.grpcSettings = {
      serviceName: f.path || "",
      multiMode: f.grpcMultiMode || undefined,
    };
  } else if (f.network === "http" || f.network === "h2") {
    stream.httpSettings = { path: f.path || "/", host: f.host ? [f.host] : undefined };
  } else if (f.network === "httpupgrade") {
    stream.httpupgradeSettings = { path: f.path || "/", host: f.host || undefined };
  } else if (f.network === "splithttp") {
    stream.splithttpSettings = {
      path: f.path || "/",
      host: f.host || undefined,
      mode: f.xhttpMode || "auto",
    };
  } else if (f.network === "kcp") {
    stream.kcpSettings = {
      mtu: 1350,
      tti: 50,
      uplinkCapacity: 5,
      downlinkCapacity: 20,
      congestion: false,
      readBufferSize: 2,
      writeBufferSize: 2,
      seed: f.kcpSeed || undefined,
      header: { type: f.kcpHeader || "none" },
    };
  } else if (f.network === "quic") {
    stream.quicSettings = {
      security: f.security === "tls" ? "tls" : "none",
      key: f.path || "",
      header: { type: f.host || "none" },
    };
  }
}

function applySecurity(stream: Record<string, unknown>, f: InboundForm) {
  if (f.security === "tls") {
    stream.security = "tls";
    stream.tlsSettings = {
      serverName: f.sni || undefined,
      alpn: f.alpn ? f.alpn.split(",").map((s) => s.trim()).filter(Boolean) : undefined,
      fingerprint: f.fingerprint || undefined,
      allowInsecure: f.allowInsecure || undefined,
    };
  } else if (f.security === "reality") {
    stream.security = "reality";
    stream.realitySettings = {
      show: false,
      dest: f.realityDest || `${f.sni || "www.google.com"}:443`,
      xver: parseInt(f.realityXver, 10) || 0,
      serverNames: f.realityServerNames
        ? f.realityServerNames.split(",").map((s) => s.trim()).filter(Boolean)
        : [f.sni || "www.google.com"],
      privateKey: f.realityPrivateKey,
      publicKey: f.realityPublicKey || undefined,
      shortIds: f.realityShortIds
        ? f.realityShortIds.split(",").map((s) => s.trim()).filter(Boolean)
        : [""],
      fingerprint: f.fingerprint || "chrome",
      spiderX: f.realitySpiderX || undefined,
    };
  } else if (f.network !== "quic") {
    stream.security = "none";
  }
}

export function buildInboundFromForm(f: InboundForm): Record<string, unknown> {
  const inbound: Record<string, unknown> = {
    tag: f.tag.trim(),
    listen: f.listen.trim() || "0.0.0.0",
    port: parseInt(f.port, 10),
    protocol: f.protocol,
    settings: { clients: [] },
  };

  if (f.protocol === "vless") {
    inbound.settings = { clients: [], decryption: "none" };
    if (f.flow) (inbound.settings as Record<string, unknown>).clients = [{ flow: f.flow }];
  } else if (f.protocol === "vmess") {
    inbound.settings = { clients: [] };
  } else if (f.protocol === "trojan") {
    inbound.settings = { clients: [] };
  } else if (f.protocol === "shadowsocks") {
    inbound.settings = {
      clients: [],
      method: f.method,
      network: f.ssNetwork,
    };
  } else if (f.protocol === "http") {
    inbound.settings = { accounts: [] };
  } else if (f.protocol === "socks") {
    inbound.settings = { auth: "noauth", accounts: [], udp: true };
  } else if (f.protocol === "mixed") {
    inbound.settings = { auth: "noauth", accounts: [], udp: true };
  } else if (f.protocol === "dokodemo-door") {
    inbound.settings = {
      address: f.tunnelAddress || "8.8.8.8",
      port: parseInt(f.tunnelPort, 10) || 0,
      network: f.tunnelNetwork || "tcp,udp",
      followRedirect: f.tunnelFollowRedirect,
    };
  } else if (f.protocol === "wireguard") {
    const peers: Record<string, unknown>[] = [];
    if (f.wgPeerPublicKey.trim()) {
      peers.push({
        publicKey: f.wgPeerPublicKey.trim(),
        allowedIPs: f.wgAllowedIPs
          ? f.wgAllowedIPs.split(",").map((s) => s.trim()).filter(Boolean)
          : ["0.0.0.0/0"],
      });
    }
    inbound.settings = {
      secretKey: f.wgSecretKey,
      mtu: parseInt(f.wgMtu, 10) || 1420,
      peers,
    };
  }

  if (supportsFallback(f.protocol) && f.fallbacks.length) {
    const fallbacks = f.fallbacks
      .filter((fb) => String(fb.dest).trim() !== "")
      .map((fb) => {
        const out: Record<string, unknown> = {};
        const destRaw = String(fb.dest).trim();
        const destNum = Number(destRaw);
        out.dest = /^\d+$/.test(destRaw) ? destNum : destRaw;
        const xver = parseInt(fb.xver, 10);
        if (xver) out.xver = xver;
        if (fb.path.trim()) out.path = fb.path.trim();
        if (fb.alpn.trim()) out.alpn = fb.alpn.trim();
        if (fb.name.trim()) out.name = fb.name.trim();
        return out;
      });
    if (fallbacks.length) {
      (inbound.settings as Record<string, unknown>).fallbacks = fallbacks;
    }
  }

  if (supportsStream(f.protocol)) {
    const stream: Record<string, unknown> = {};
    applyTransport(stream, f);
    applySecurity(stream, f);
    inbound.streamSettings = stream;
  }

  if (f.sniffing && f.protocol !== "wireguard" && f.protocol !== "dokodemo-door") {
    const overrides = f.sniffDestOverride
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    inbound.sniffing = {
      enabled: true,
      destOverride: overrides.length ? overrides : ["http", "tls", "quic"],
    };
  }

  return inbound;
}

export const RULE_PROTOCOLS = ["http", "tls", "quic", "bittorrent"] as const;

export type RoutingRuleForm = {
  type: string;
  outboundTag: string;
  balancerTag: string;
  inboundTag: string;
  ip: string;
  domain: string;
  port: string;
  network: string;
  protocol: string;
  source: string;
};

export const defaultRule = (): RoutingRuleForm => ({
  type: "field",
  outboundTag: "BLOCK",
  balancerTag: "",
  inboundTag: "",
  ip: "",
  domain: "",
  port: "",
  network: "",
  protocol: "",
  source: "",
});

export function ruleToForm(r: Record<string, unknown>): RoutingRuleForm {
  const protocol = r.protocol;
  return {
    type: String(r.type || "field"),
    outboundTag: String(r.outboundTag || ""),
    balancerTag: String(r.balancerTag || ""),
    inboundTag: Array.isArray(r.inboundTag) ? (r.inboundTag as string[]).join(",") : String(r.inboundTag || ""),
    ip: Array.isArray(r.ip) ? (r.ip as string[]).join(",") : "",
    domain: Array.isArray(r.domain) ? (r.domain as string[]).join(",") : "",
    port: String(r.port || ""),
    network: String(r.network || ""),
    protocol: Array.isArray(protocol) ? (protocol as string[]).join(",") : String(protocol || ""),
    source: Array.isArray(r.source) ? (r.source as string[]).join(",") : "",
  };
}

export function buildRuleFromForm(f: RoutingRuleForm): Record<string, unknown> {
  const r: Record<string, unknown> = { type: f.type || "field" };
  const splitList = (s: string) => s.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);
  if (f.balancerTag.trim()) r.balancerTag = f.balancerTag.trim();
  else if (f.outboundTag) r.outboundTag = f.outboundTag;
  if (f.inboundTag) {
    const tags = f.inboundTag.split(",").map((s) => s.trim()).filter(Boolean);
    r.inboundTag = tags.length === 1 ? tags[0] : tags;
  }
  if (f.ip) r.ip = splitList(f.ip);
  if (f.domain) r.domain = splitList(f.domain);
  if (f.source) r.source = splitList(f.source);
  if (f.port) r.port = f.port;
  if (f.network) r.network = f.network;
  if (f.protocol) r.protocol = splitList(f.protocol);
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

/* ---- Outbound builders (proxy chaining + WARP) ------------------------- */

export const OUTBOUND_NETWORKS = ["tcp", "ws", "grpc", "http", "httpupgrade", "splithttp"] as const;
export const OUTBOUND_SECURITIES = ["none", "tls", "reality"] as const;

export type OutboundForm = {
  tag: string;
  protocol: string;
  address: string;
  port: string;
  user: string;
  pass: string;
  id: string;
  flow: string;
  method: string;
  network: string;
  security: string;
  sni: string;
  path: string;
  hostHeader: string;
  fingerprint: string;
  realityPublicKey: string;
  realityShortId: string;
  wgSecretKey: string;
  wgAddress: string;
  wgPeerPublicKey: string;
  wgEndpoint: string;
  wgReserved: string;
};

export const defaultOutboundForm = (): OutboundForm => ({
  tag: "",
  protocol: "freedom",
  address: "",
  port: "443",
  user: "",
  pass: "",
  id: "",
  flow: "",
  method: SS_METHODS[0],
  network: "tcp",
  security: "none",
  sni: "",
  path: "/",
  hostHeader: "",
  fingerprint: "chrome",
  realityPublicKey: "",
  realityShortId: "",
  wgSecretKey: "",
  wgAddress: "172.16.0.2/32",
  wgPeerPublicKey: "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=",
  wgEndpoint: "engage.cloudflareclient.com:2408",
  wgReserved: "",
});

/** Cloudflare WARP scaffold (admin still pastes their registered secretKey/reserved). */
export const warpOutboundForm = (): OutboundForm => ({
  ...defaultOutboundForm(),
  tag: "warp",
  protocol: "wireguard",
});

function streamFromOutboundForm(f: OutboundForm): Record<string, unknown> | undefined {
  if (f.network === "tcp" && f.security === "none") return undefined;
  const stream: Record<string, unknown> = { network: f.network };
  if (f.network === "ws") {
    stream.wsSettings = { path: f.path || "/", headers: f.hostHeader ? { Host: f.hostHeader } : undefined };
  } else if (f.network === "grpc") {
    stream.grpcSettings = { serviceName: f.path || "" };
  } else if (f.network === "httpupgrade") {
    stream.httpupgradeSettings = { path: f.path || "/", host: f.hostHeader || undefined };
  } else if (f.network === "splithttp") {
    stream.splithttpSettings = { path: f.path || "/", host: f.hostHeader || undefined };
  } else if (f.network === "http") {
    stream.httpSettings = { path: f.path || "/", host: f.hostHeader ? [f.hostHeader] : undefined };
  }
  if (f.security === "tls") {
    stream.security = "tls";
    stream.tlsSettings = { serverName: f.sni || undefined, fingerprint: f.fingerprint || undefined };
  } else if (f.security === "reality") {
    stream.security = "reality";
    stream.realitySettings = {
      serverName: f.sni || undefined,
      fingerprint: f.fingerprint || "chrome",
      publicKey: f.realityPublicKey || undefined,
      shortId: f.realityShortId || undefined,
    };
  }
  return stream;
}

export function buildOutboundFromForm(f: OutboundForm): Record<string, unknown> {
  const ob: Record<string, unknown> = { tag: f.tag.trim(), protocol: f.protocol };
  const port = parseInt(f.port, 10) || 443;
  const addr = f.address.trim();

  if (f.protocol === "freedom" || f.protocol === "blackhole") {
    ob.settings = {};
    return ob;
  }
  if (f.protocol === "socks" || f.protocol === "http") {
    const server: Record<string, unknown> = { address: addr, port };
    if (f.user) server.users = [{ user: f.user, pass: f.pass }];
    ob.settings = { servers: [server] };
    const stream = streamFromOutboundForm(f);
    if (stream) ob.streamSettings = stream;
    return ob;
  }
  if (f.protocol === "shadowsocks") {
    ob.settings = {
      servers: [{ address: addr, port, method: f.method, password: f.pass }],
    };
    return ob;
  }
  if (f.protocol === "trojan") {
    ob.settings = { servers: [{ address: addr, port, password: f.pass }] };
    const stream = streamFromOutboundForm({ ...f, security: f.security === "none" ? "tls" : f.security });
    if (stream) ob.streamSettings = stream;
    return ob;
  }
  if (f.protocol === "vless" || f.protocol === "vmess") {
    const user: Record<string, unknown> = { id: f.id };
    if (f.protocol === "vless") {
      user.encryption = "none";
      if (f.flow) user.flow = f.flow;
    } else {
      user.security = "auto";
    }
    ob.settings = { vnext: [{ address: addr, port, users: [user] }] };
    const stream = streamFromOutboundForm(f);
    if (stream) ob.streamSettings = stream;
    return ob;
  }
  if (f.protocol === "wireguard") {
    const peer: Record<string, unknown> = {
      publicKey: f.wgPeerPublicKey.trim(),
      endpoint: f.wgEndpoint.trim(),
      allowedIPs: ["0.0.0.0/0", "::/0"],
    };
    const settings: Record<string, unknown> = {
      secretKey: f.wgSecretKey.trim(),
      address: f.wgAddress.split(",").map((s) => s.trim()).filter(Boolean),
      peers: [peer],
    };
    const reserved = f.wgReserved
      .split(",")
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => !Number.isNaN(n));
    if (reserved.length) settings.reserved = reserved;
    ob.settings = settings;
    return ob;
  }
  ob.settings = {};
  return ob;
}

export function outboundToForm(o: Record<string, unknown>): OutboundForm {
  const f = defaultOutboundForm();
  f.tag = String(o.tag || "");
  f.protocol = String(o.protocol || "freedom");
  const settings = (o.settings || {}) as Record<string, unknown>;
  const ss = (o.streamSettings || {}) as Record<string, unknown>;
  const servers = settings.servers as Record<string, unknown>[] | undefined;
  const vnext = settings.vnext as Record<string, unknown>[] | undefined;

  if (servers && servers[0]) {
    const s0 = servers[0];
    f.address = String(s0.address || "");
    f.port = String(s0.port ?? "443");
    f.method = String(s0.method || SS_METHODS[0]);
    f.pass = String(s0.password || "");
    const users = s0.users as Record<string, unknown>[] | undefined;
    if (users && users[0]) {
      f.user = String(users[0].user || "");
      f.pass = String(users[0].pass || f.pass);
    }
  }
  if (vnext && vnext[0]) {
    f.address = String(vnext[0].address || "");
    f.port = String(vnext[0].port ?? "443");
    const users = vnext[0].users as Record<string, unknown>[] | undefined;
    if (users && users[0]) {
      f.id = String(users[0].id || "");
      f.flow = String(users[0].flow || "");
    }
  }
  if (f.protocol === "wireguard") {
    f.wgSecretKey = String(settings.secretKey || "");
    f.wgAddress = Array.isArray(settings.address) ? (settings.address as string[]).join(",") : "";
    f.wgReserved = Array.isArray(settings.reserved) ? (settings.reserved as number[]).join(",") : "";
    const peers = settings.peers as Record<string, unknown>[] | undefined;
    if (peers && peers[0]) {
      f.wgPeerPublicKey = String(peers[0].publicKey || "");
      f.wgEndpoint = String(peers[0].endpoint || "");
    }
  }
  f.network = String(ss.network || "tcp");
  f.security = String(ss.security || "none");
  const tls = (ss.tlsSettings || ss.realitySettings || {}) as Record<string, unknown>;
  f.sni = String(tls.serverName || "");
  f.fingerprint = String(tls.fingerprint || "chrome");
  f.realityPublicKey = String((ss.realitySettings as Record<string, unknown>)?.publicKey || "");
  f.realityShortId = String((ss.realitySettings as Record<string, unknown>)?.shortId || "");
  return f;
}

export function outboundSupportsStream(protocol: string): boolean {
  return protocol === "vless" || protocol === "vmess" || protocol === "trojan" || protocol === "socks" || protocol === "http";
}

/** @deprecated use INBOUND_PROTOCOLS */
export const USER_PROTOCOLS = INBOUND_PROTOCOLS;
