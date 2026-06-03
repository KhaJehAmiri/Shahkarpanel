/** Helpers for NexusPanel Xray config UI (3x-ui style). */

export const USER_PROTOCOLS = ["vless", "vmess", "trojan", "shadowsocks"] as const;
export const NETWORKS = ["tcp", "ws", "grpc", "http", "h2"] as const;
export const SS_METHODS = ["chacha20-ietf-poly1305", "aes-256-gcm", "aes-128-gcm"];
export const LOG_LEVELS = ["none", "debug", "info", "warning", "error"];
export const DOMAIN_STRATEGIES = ["AsIs", "IPIfNonMatch", "IPOnDemand"];
export const VLESS_FLOWS = ["", "xtls-rprx-vision", "xtls-rprx-vision-udp443"];
export const SECURITIES = ["none", "tls", "reality"] as const;
export const OUTBOUND_PROTOCOLS = ["freedom", "blackhole", "socks"] as const;

const SYSTEM_PROTOCOLS = new Set(["dokodemo-door"]);
const SYSTEM_TAGS = new Set(["API_INBOUND", "API", "TUN_IN", "metrics_in"]);

export function isUserInbound(i: { protocol?: string; tag?: string }): boolean {
  if (!i?.protocol || SYSTEM_PROTOCOLS.has(i.protocol)) return false;
  if (i.tag && SYSTEM_TAGS.has(i.tag)) return false;
  return USER_PROTOCOLS.includes(i.protocol as (typeof USER_PROTOCOLS)[number]);
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

export type InboundForm = {
  tag: string;
  listen: string;
  port: string;
  protocol: string;
  network: string;
  path: string;
  method: string;
  security: string;
  sni: string;
  alpn: string;
  fingerprint: string;
  realityDest: string;
  realityServerNames: string;
  realityPrivateKey: string;
  realityShortIds: string;
  sniffing: boolean;
  flow: string;
};

export const defaultInboundForm = (): InboundForm => ({
  tag: "",
  listen: "0.0.0.0",
  port: "443",
  protocol: "vless",
  network: "tcp",
  path: "/",
  method: SS_METHODS[0],
  security: "none",
  sni: "",
  alpn: "",
  fingerprint: "",
  realityDest: "",
  realityServerNames: "",
  realityPrivateKey: "",
  realityShortIds: "",
  sniffing: true,
  flow: "",
});

export function inboundToForm(i: Record<string, unknown>): InboundForm {
  const ss = (i.streamSettings || {}) as Record<string, unknown>;
  const sec = (ss.security as string) || "none";
  const rs = (ss.realitySettings || {}) as Record<string, unknown>;
  const ts = (ss.tlsSettings || ss.tls || {}) as Record<string, unknown>;
  const sniff = i.sniffing as Record<string, unknown> | undefined;
  const settings = (i.settings || {}) as Record<string, unknown>;
  const clients = (settings.clients as unknown[]) || [];
  const flow = clients[0] && typeof clients[0] === "object" ? (clients[0] as Record<string, unknown>).flow as string : "";

  let path = "/";
  if (ss.network === "ws") path = ((ss.wsSettings as Record<string, unknown>)?.path as string) || "/";
  if (ss.network === "grpc") path = ((ss.grpcSettings as Record<string, unknown>)?.serviceName as string) || "";

  return {
    tag: String(i.tag || ""),
    listen: typeof i.listen === "string" ? i.listen : "0.0.0.0",
    port: String(i.port || ""),
    protocol: String(i.protocol || "vless"),
    network: String(ss.network || "tcp"),
    path,
    method: String(settings.method || SS_METHODS[0]),
    security: sec,
    sni: String(
      ts.serverName ||
        (Array.isArray(rs.serverNames) ? (rs.serverNames as string[])[0] : "") ||
        "",
    ),
    alpn: Array.isArray(ts.alpn) ? (ts.alpn as string[]).join(",") : "",
    fingerprint: String(ts.fingerprint || rs.fingerprint || ""),
    realityDest: String(rs.dest || ""),
    realityServerNames: Array.isArray(rs.serverNames) ? (rs.serverNames as string[]).join(",") : "",
    realityPrivateKey: String(rs.privateKey || ""),
    realityShortIds: Array.isArray(rs.shortIds) ? (rs.shortIds as string[]).join(",") : "",
    sniffing: sniff?.enabled !== false,
    flow: flow || "",
  };
}

export function buildInboundFromForm(f: InboundForm): Record<string, unknown> {
  const stream: Record<string, unknown> = { network: f.network };
  if (f.network === "ws") stream.wsSettings = { path: f.path || "/" };
  if (f.network === "grpc") stream.grpcSettings = { serviceName: f.path || "" };

  if (f.security === "tls") {
    stream.security = "tls";
    stream.tlsSettings = {
      serverName: f.sni || undefined,
      alpn: f.alpn ? f.alpn.split(",").map((s) => s.trim()).filter(Boolean) : undefined,
      fingerprint: f.fingerprint || undefined,
    };
  } else if (f.security === "reality") {
    stream.security = "reality";
    stream.realitySettings = {
      show: false,
      dest: f.realityDest || `${f.sni || "www.google.com"}:443`,
      xver: 0,
      serverNames: f.realityServerNames
        ? f.realityServerNames.split(",").map((s) => s.trim()).filter(Boolean)
        : [f.sni || "www.google.com"],
      privateKey: f.realityPrivateKey,
      shortIds: f.realityShortIds
        ? f.realityShortIds.split(",").map((s) => s.trim()).filter(Boolean)
        : [""],
      fingerprint: f.fingerprint || "chrome",
    };
  } else {
    stream.security = "none";
  }

  const settings: Record<string, unknown> = { clients: [] };
  if (f.protocol === "vless") {
    settings.decryption = "none";
    if (f.flow) settings.clients = [{ flow: f.flow }];
  }
  if (f.protocol === "shadowsocks") {
    settings.network = "tcp,udp";
    settings.method = f.method;
  }

  const inbound: Record<string, unknown> = {
    tag: f.tag.trim(),
    listen: f.listen.trim() || "0.0.0.0",
    port: parseInt(f.port, 10),
    protocol: f.protocol,
    settings,
  };
  if (f.protocol !== "shadowsocks") inbound.streamSettings = stream;
  if (f.sniffing) {
    inbound.sniffing = {
      enabled: true,
      destOverride: ["http", "tls", "quic"],
    };
  }
  return inbound;
}

export type RoutingRuleForm = {
  type: string;
  outboundTag: string;
  inboundTag: string;
  ip: string;
  domain: string;
  port: string;
  network: string;
  protocol: string;
};

export const defaultRule = (): RoutingRuleForm => ({
  type: "field",
  outboundTag: "BLOCK",
  inboundTag: "",
  ip: "",
  domain: "",
  port: "",
  network: "",
  protocol: "",
});

export function ruleToForm(r: Record<string, unknown>): RoutingRuleForm {
  return {
    type: String(r.type || "field"),
    outboundTag: String(r.outboundTag || ""),
    inboundTag: Array.isArray(r.inboundTag) ? (r.inboundTag as string[]).join(",") : String(r.inboundTag || ""),
    ip: Array.isArray(r.ip) ? (r.ip as string[]).join(",") : "",
    domain: Array.isArray(r.domain) ? (r.domain as string[]).join(",") : "",
    port: String(r.port || ""),
    network: String(r.network || ""),
    protocol: String(r.protocol || ""),
  };
}

export function buildRuleFromForm(f: RoutingRuleForm): Record<string, unknown> {
  const r: Record<string, unknown> = { type: f.type || "field" };
  if (f.outboundTag) r.outboundTag = f.outboundTag;
  if (f.inboundTag) {
    const tags = f.inboundTag.split(",").map((s) => s.trim()).filter(Boolean);
    r.inboundTag = tags.length === 1 ? tags[0] : tags;
  }
  const splitList = (s: string) =>
    s.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);
  if (f.ip) r.ip = splitList(f.ip);
  if (f.domain) r.domain = splitList(f.domain);
  if (f.port) r.port = f.port;
  if (f.network) r.network = f.network;
  if (f.protocol) r.protocol = f.protocol;
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
