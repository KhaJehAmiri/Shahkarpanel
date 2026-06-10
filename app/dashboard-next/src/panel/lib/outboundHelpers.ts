/** Outbound helpers — 3x-ui parity for Xray outbounds (form + JSON merge). */

import { FINGERPRINTS, KCP_HEADERS, SS_METHODS, VLESS_FLOWS } from "./xrayHelpers";

export const OUTBOUND_PROTOCOLS = [
  "freedom",
  "blackhole",
  "dns",
  "socks",
  "http",
  "vless",
  "vmess",
  "trojan",
  "shadowsocks",
  "wireguard",
  "hysteria",
  "amneziawg",
] as const;

export const OUTBOUND_NETWORKS = [
  "tcp",
  "kcp",
  "ws",
  "grpc",
  "http",
  "httpupgrade",
  "splithttp",
  "xhttp",
  "quic",
] as const;

/** 3x-ui transmission labels */
export const TRANSMISSION_OPTIONS = [
  { value: "tcp", label: "RAW" },
  { value: "kcp", label: "mKCP" },
  { value: "ws", label: "WebSocket" },
  { value: "http", label: "HTTP/2" },
  { value: "grpc", label: "gRPC" },
  { value: "httpupgrade", label: "HTTPUpgrade" },
  { value: "splithttp", label: "SplitHTTP" },
  { value: "xhttp", label: "XHTTP" },
  { value: "quic", label: "QUIC" },
] as const;

export const OUTBOUND_SECURITIES = ["none", "tls", "reality"] as const;
export const OUTBOUND_DOMAIN_STRATEGIES = ["AsIs", "UseIP", "UseIPv4", "UseIPv6", "ForceIP", "ForceIPv4", "ForceIPv6"] as const;
export const WIREGUARD_DOMAIN_STRATEGIES = ["", "ForceIP", "ForceIPv4", "ForceIPv6", "ForceIPv6v4", "ForceIPv4v6"] as const;
export const VMESS_SECURITIES = ["auto", "aes-128-gcm", "chacha20-poly1305", "none", "zero"] as const;
export const MUX_XUDP_UDP443 = ["reject", "allow", "skip"] as const;
export const BLACKHOLE_TYPES = ["", "none", "http"] as const;
export const DNS_NETWORKS = ["udp", "tcp"] as const;
export const FRAGMENT_PACKETS = ["1-3", "1-5", "tlshello"] as const;

export const SYSTEM_OUT_TAGS = new Set(["DIRECT", "BLOCK", "API"]);

export type OutboundForm = {
  tag: string;
  protocol: string;
  sendThrough: string;
  /* proxy */
  address: string;
  port: string;
  user: string;
  pass: string;
  id: string;
  flow: string;
  encryption: string;
  vmessSecurity: string;
  method: string;
  ssUot: boolean;
  ssUotVersion: string;
  socksUdp: boolean;
  userLevel: string;
  /* freedom */
  freedomDomainStrategy: string;
  freedomRedirect: string;
  freedomFragment: boolean;
  fragPackets: string;
  fragLength: string;
  fragInterval: string;
  fragMaxSplit: string;
  /* blackhole */
  blackholeType: string;
  /* dns */
  dnsNetwork: string;
  /* stream */
  network: string;
  security: string;
  sni: string;
  alpn: string;
  allowInsecure: boolean;
  path: string;
  hostHeader: string;
  fingerprint: string;
  realityPublicKey: string;
  realityShortId: string;
  realitySpiderX: string;
  tcpHttpCamo: boolean;
  kcpSeed: string;
  kcpHeader: string;
  grpcMultiMode: boolean;
  grpcAuthority: string;
  xhttpMode: string;
  /* wireguard */
  wgSecretKey: string;
  wgAddress: string;
  wgPeerPublicKey: string;
  wgEndpoint: string;
  wgReserved: string;
  wgMtu: string;
  wgWorkers: string;
  wgDomainStrategy: string;
  wgNoKernelTun: boolean;
  wgPeerPsk: string;
  wgKeepAlive: string;
  wgAllowedIPs: string;
  /* mux */
  muxEnabled: boolean;
  muxConcurrency: string;
  muxXudpConcurrency: string;
  muxXudpProxyUDP443: string;
  /* sockopt / chaining */
  sockoptsEnabled: boolean;
  dialerProxy: string;
  reverseTag: string;
  /* hysteria (Xray v2) */
  hyUp: string;
  hyDown: string;
  hyUdpIdleTimeout: string;
};

export const defaultOutboundForm = (): OutboundForm => ({
  tag: "",
  protocol: "freedom",
  sendThrough: "",
  address: "",
  port: "443",
  user: "",
  pass: "",
  id: "",
  flow: "",
  encryption: "none",
  vmessSecurity: "auto",
  method: SS_METHODS[0],
  ssUot: false,
  ssUotVersion: "2",
  socksUdp: true,
  userLevel: "0",
  freedomDomainStrategy: "AsIs",
  freedomRedirect: "",
  freedomFragment: false,
  fragPackets: "tlshello",
  fragLength: "100-200",
  fragInterval: "10-20",
  fragMaxSplit: "",
  blackholeType: "none",
  dnsNetwork: "udp",
  network: "tcp",
  security: "none",
  sni: "",
  alpn: "",
  allowInsecure: false,
  path: "/",
  hostHeader: "",
  fingerprint: "chrome",
  realityPublicKey: "",
  realityShortId: "",
  realitySpiderX: "",
  tcpHttpCamo: false,
  kcpSeed: "",
  kcpHeader: "none",
  grpcMultiMode: false,
  grpcAuthority: "",
  xhttpMode: "auto",
  wgSecretKey: "",
  wgAddress: "172.16.0.2/32",
  wgPeerPublicKey: "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=",
  wgEndpoint: "engage.cloudflareclient.com:2408",
  wgReserved: "",
  wgMtu: "1420",
  wgWorkers: "2",
  wgDomainStrategy: "",
  wgNoKernelTun: false,
  wgPeerPsk: "",
  wgKeepAlive: "0",
  wgAllowedIPs: "0.0.0.0/0,::/0",
  muxEnabled: false,
  muxConcurrency: "8",
  muxXudpConcurrency: "16",
  muxXudpProxyUDP443: "reject",
  sockoptsEnabled: false,
  dialerProxy: "",
  reverseTag: "",
  hyUp: "",
  hyDown: "",
  hyUdpIdleTimeout: "60",
});

export const freedomOutboundForm = (tag = "DIRECT"): OutboundForm => ({
  ...defaultOutboundForm(),
  tag,
  protocol: "freedom",
});

export const blackholeOutboundForm = (tag = "BLOCK"): OutboundForm => ({
  ...defaultOutboundForm(),
  tag,
  protocol: "blackhole",
  blackholeType: "none",
});

export const dnsOutboundForm = (tag = "dns-out"): OutboundForm => ({
  ...defaultOutboundForm(),
  tag,
  protocol: "dns",
  dnsNetwork: "udp",
});

export const warpOutboundForm = (): OutboundForm => ({
  ...defaultOutboundForm(),
  tag: "warp",
  protocol: "wireguard",
});

function parsePort(raw: string, fallback = 443): number {
  const n = parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 && n <= 65535 ? n : fallback;
}

function streamFromOutboundForm(f: OutboundForm): Record<string, unknown> | undefined {
  const needsStream = outboundSupportsStream(f.protocol);
  if (!needsStream) return undefined;
  if (f.network === "tcp" && f.security === "none" && !f.tcpHttpCamo) return undefined;

  const stream: Record<string, unknown> = { network: f.network };

  if (f.network === "tcp") {
    if (f.tcpHttpCamo) {
      stream.tcpSettings = {
        header: {
          type: "http",
          request: {
            path: [f.path || "/"],
            headers: f.hostHeader ? { Host: [f.hostHeader] } : {},
          },
        },
      };
    }
  } else if (f.network === "ws") {
    stream.wsSettings = {
      path: f.path || "/",
      headers: f.hostHeader ? { Host: f.hostHeader } : undefined,
    };
  } else if (f.network === "grpc") {
    stream.grpcSettings = {
      serviceName: f.path || "",
      multiMode: f.grpcMultiMode,
      authority: f.grpcAuthority || undefined,
    };
  } else if (f.network === "httpupgrade") {
    stream.httpupgradeSettings = { path: f.path || "/", host: f.hostHeader || undefined };
  } else if (f.network === "splithttp" || f.network === "xhttp") {
    const key = f.network === "xhttp" ? "xhttpSettings" : "splithttpSettings";
    stream[key] = {
      path: f.path || "/",
      host: f.hostHeader || undefined,
      mode: f.network === "xhttp" ? f.xhttpMode || "auto" : undefined,
    };
    stream.network = f.network === "xhttp" ? "xhttp" : "splithttp";
  } else if (f.network === "http" || f.network === "h2") {
    stream.network = "http";
    stream.httpSettings = { path: f.path || "/", host: f.hostHeader ? [f.hostHeader] : undefined };
  } else if (f.network === "kcp") {
    stream.kcpSettings = {
      mtu: 1350,
      tti: 50,
      uplinkCapacity: 5,
      downlinkCapacity: 20,
      seed: f.kcpSeed || undefined,
      header: { type: f.kcpHeader || "none" },
    };
  } else if (f.network === "quic") {
    stream.quicSettings = {
      security: f.security === "none" ? "none" : "tls",
      key: f.path || "",
      header: { type: f.kcpHeader || "none" },
    };
  }

  if (f.security === "tls") {
    stream.security = "tls";
    const alpn = f.alpn.split(",").map((s) => s.trim()).filter(Boolean);
    stream.tlsSettings = {
      serverName: f.sni || undefined,
      fingerprint: f.fingerprint || undefined,
      allowInsecure: f.allowInsecure || undefined,
      alpn: alpn.length ? alpn : undefined,
    };
  } else if (f.security === "reality") {
    stream.security = "reality";
    stream.realitySettings = {
      serverName: f.sni || undefined,
      fingerprint: f.fingerprint || "chrome",
      publicKey: f.realityPublicKey || undefined,
      shortId: f.realityShortId || undefined,
      spiderX: f.realitySpiderX || undefined,
    };
  }

  return stream;
}

function muxFromForm(f: OutboundForm): Record<string, unknown> | undefined {
  if (!f.muxEnabled || !outboundSupportsMux(f.protocol, f.flow, f.network)) return undefined;
  return {
    enabled: true,
    concurrency: parseInt(f.muxConcurrency, 10) || 8,
    xudpConcurrency: parseInt(f.muxXudpConcurrency, 10) || 16,
    xudpProxyUDP443: f.muxXudpProxyUDP443 || "reject",
  };
}

export function outboundSupportsStream(protocol: string): boolean {
  if (protocol === "hysteria") return true;
  return ["vless", "vmess", "trojan", "socks", "http"].includes(protocol);
}

export function outboundSupportsMux(protocol: string, flow: string, network: string): boolean {
  if (protocol === "vless" && flow.includes("vision")) return false;
  if (network === "xhttp") return false;
  return ["vless", "vmess", "trojan", "shadowsocks"].includes(protocol);
}

export function buildOutboundFromForm(f: OutboundForm): Record<string, unknown> {
  const ob: Record<string, unknown> = {
    tag: f.tag.trim(),
    protocol: f.protocol,
  };
  if (f.sendThrough.trim()) ob.sendThrough = f.sendThrough.trim();

  const port = parsePort(f.port);
  const addr = f.address.trim();

  if (f.protocol === "freedom") {
    const settings: Record<string, unknown> = { domainStrategy: f.freedomDomainStrategy || "AsIs" };
    if (f.freedomRedirect.trim()) settings.redirect = f.freedomRedirect.trim();
    if (f.freedomFragment) {
      settings.fragment = {
        packets: f.fragPackets || "tlshello",
        length: f.fragLength || "100-200",
        interval: f.fragInterval || "10-20",
      };
      if (f.fragMaxSplit.trim()) settings.fragment = { ...(settings.fragment as object), maxSplit: f.fragMaxSplit.trim() };
    }
    ob.settings = settings;
    return ob;
  }

  if (f.protocol === "blackhole") {
    ob.settings = f.blackholeType && f.blackholeType !== "" ? { response: { type: f.blackholeType } } : {};
    return ob;
  }

  if (f.protocol === "dns") {
    ob.settings = { network: f.dnsNetwork || "udp" };
    return ob;
  }

  if (f.protocol === "socks" || f.protocol === "http") {
    const server: Record<string, unknown> = { address: addr, port };
    if (f.user) server.users = [{ user: f.user, pass: f.pass }];
    ob.settings = {
      servers: [server],
      ...(f.protocol === "socks" ? { udp: f.socksUdp } : {}),
    };
    const stream = streamFromOutboundForm(f);
    if (stream) ob.streamSettings = stream;
    return ob;
  }

  if (f.protocol === "shadowsocks") {
    ob.settings = {
      servers: [{ address: addr, port, method: f.method, password: f.pass }],
      ...(f.ssUot ? { uot: true, UoTVersion: parseInt(f.ssUotVersion, 10) || 2 } : {}),
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
      user.encryption = f.encryption || "none";
      if (f.flow) user.flow = f.flow;
    } else {
      user.security = f.vmessSecurity || "auto";
    }
    const settings: Record<string, unknown> = { vnext: [{ address: addr, port, users: [user] }] };
    if (f.protocol === "vless" && f.reverseTag.trim()) {
      settings.reverse = { tag: f.reverseTag.trim() };
    }
    ob.settings = settings;
    const stream = streamFromOutboundForm(f);
    if (stream) ob.streamSettings = stream;
    return ob;
  }

  if (f.protocol === "wireguard" || f.protocol === "amneziawg") {
    const peer: Record<string, unknown> = {
      publicKey: f.wgPeerPublicKey.trim(),
      endpoint: f.wgEndpoint.trim(),
      allowedIPs: f.wgAllowedIPs.split(",").map((s) => s.trim()).filter(Boolean),
    };
    if (f.wgPeerPsk.trim()) peer.preSharedKey = f.wgPeerPsk.trim();
    const ka = parseInt(f.wgKeepAlive, 10);
    if (ka > 0) peer.keepAlive = ka;
    const settings: Record<string, unknown> = {
      secretKey: f.wgSecretKey.trim(),
      address: f.wgAddress.split(",").map((s) => s.trim()).filter(Boolean),
      peers: [peer],
    };
    const mtu = parseInt(f.wgMtu, 10);
    if (mtu > 0) settings.mtu = mtu;
    const workers = parseInt(f.wgWorkers, 10);
    if (workers > 0) settings.workers = workers;
    if (f.wgDomainStrategy && WIREGUARD_DOMAIN_STRATEGIES.includes(f.wgDomainStrategy as typeof WIREGUARD_DOMAIN_STRATEGIES[number])) {
      settings.domainStrategy = f.wgDomainStrategy;
    }
    if (f.wgNoKernelTun) settings.noKernelTun = true;
    const reserved = f.wgReserved.split(",").map((s) => parseInt(s.trim(), 10)).filter((n) => !Number.isNaN(n));
    if (reserved.length) settings.reserved = reserved;
    ob.protocol = "wireguard";
    ob.settings = settings;
    return ob;
  }

  if (f.protocol === "hysteria") {
    const alpn = f.alpn
      ? f.alpn.split(",").map((s) => s.trim()).filter(Boolean)
      : ["h3"];
    ob.settings = {
      version: 2,
      address: addr,
      port,
    };
    ob.streamSettings = {
      network: "hysteria",
      security: "tls",
      tlsSettings: {
        serverName: f.sni.trim() || addr || undefined,
        alpn,
        fingerprint: f.fingerprint && f.fingerprint !== "none" ? f.fingerprint : "chrome",
        allowInsecure: f.allowInsecure || undefined,
      },
      hysteriaSettings: {
        version: 2,
        auth: f.pass,
        ...(f.hyUp.trim() ? { up: f.hyUp.trim() } : {}),
        ...(f.hyDown.trim() ? { down: f.hyDown.trim() } : {}),
        ...(parseInt(f.hyUdpIdleTimeout, 10) > 0
          ? { udpIdleTimeout: parseInt(f.hyUdpIdleTimeout, 10) }
          : {}),
      },
    };
    return ob;
  }

  ob.settings = {};
  return ob;
}

export function outboundToForm(o: Record<string, unknown>): OutboundForm {
  const f = defaultOutboundForm();
  f.tag = String(o.tag || "");
  f.protocol = String(o.protocol || "freedom");
  f.sendThrough = String(o.sendThrough || "");

  const settings = (o.settings || {}) as Record<string, unknown>;
  const ss = (o.streamSettings || {}) as Record<string, unknown>;
  const mux = (o.mux || {}) as Record<string, unknown>;

  if (f.protocol === "freedom") {
    f.freedomDomainStrategy = String(settings.domainStrategy || "AsIs");
    f.freedomRedirect = String(settings.redirect || "");
    const frag = settings.fragment as Record<string, unknown> | undefined;
    if (frag && Object.keys(frag).length) {
      f.freedomFragment = true;
      f.fragPackets = String(frag.packets || "tlshello");
      f.fragLength = String(frag.length || "100-200");
      f.fragInterval = String(frag.interval || "10-20");
      f.fragMaxSplit = String(frag.maxSplit || "");
    }
  }
  if (f.protocol === "blackhole") {
    const resp = settings.response as Record<string, unknown> | undefined;
    f.blackholeType = String(resp?.type ?? "none");
  }
  if (f.protocol === "dns") {
    f.dnsNetwork = String(settings.network || "udp");
  }

  const servers = settings.servers as Record<string, unknown>[] | undefined;
  const vnext = settings.vnext as Record<string, unknown>[] | undefined;
  if (servers?.[0]) {
    const s0 = servers[0];
    f.address = String(s0.address || "");
    f.port = String(s0.port ?? "443");
    f.method = String(s0.method || SS_METHODS[0]);
    f.pass = String(s0.password || "");
    const users = s0.users as Record<string, unknown>[] | undefined;
    if (users?.[0]) {
      f.user = String(users[0].user || "");
      f.pass = String(users[0].pass || f.pass);
    }
    if (settings.uot) f.ssUot = true;
    if (settings.UoTVersion != null) f.ssUotVersion = String(settings.UoTVersion);
    if (settings.udp != null) f.socksUdp = !!settings.udp;
  }
  if (vnext?.[0]) {
    f.address = String(vnext[0].address || "");
    f.port = String(vnext[0].port ?? "443");
    const users = vnext[0].users as Record<string, unknown>[] | undefined;
    if (users?.[0]) {
      f.id = String(users[0].id || "");
      f.flow = String(users[0].flow || "");
      f.encryption = String(users[0].encryption ?? "none");
      f.vmessSecurity = String(users[0].security || "auto");
    }
  }
  /* flat vless settings (xray 26+) */
  if (f.protocol === "vless" && settings.address) {
    f.address = String(settings.address || f.address);
    f.port = String(settings.port ?? (f.port || "443"));
    f.id = String(settings.id || f.id);
    f.flow = String(settings.flow || f.flow);
    f.encryption = String(settings.encryption ?? f.encryption);
  }
  const reverse = (settings.reverse || o.reverse) as Record<string, unknown> | undefined;
  if (reverse?.tag) f.reverseTag = String(reverse.tag);
  if (f.protocol === "wireguard" || f.protocol === "amneziawg") {
    f.wgSecretKey = String(settings.secretKey || "");
    f.wgAddress = Array.isArray(settings.address) ? (settings.address as string[]).join(",") : "";
    f.wgMtu = settings.mtu != null ? String(settings.mtu) : "1420";
    f.wgWorkers = settings.workers != null ? String(settings.workers) : "2";
    f.wgDomainStrategy = String(settings.domainStrategy || "");
    f.wgNoKernelTun = !!settings.noKernelTun;
    f.wgReserved = Array.isArray(settings.reserved) ? (settings.reserved as number[]).join(",") : "";
    const peers = settings.peers as Record<string, unknown>[] | undefined;
    if (peers?.[0]) {
      f.wgPeerPublicKey = String(peers[0].publicKey || "");
      f.wgEndpoint = String(peers[0].endpoint || "");
      f.wgPeerPsk = String(peers[0].preSharedKey || "");
      f.wgKeepAlive = peers[0].keepAlive != null ? String(peers[0].keepAlive) : "0";
      f.wgAllowedIPs = Array.isArray(peers[0].allowedIPs) ? (peers[0].allowedIPs as string[]).join(",") : "0.0.0.0/0,::/0";
    }
    if (f.protocol === "wireguard" && /amnezia|awg/i.test(String(o.tag || ""))) {
      f.protocol = "amneziawg";
    }
  }
  if (f.protocol === "hysteria") {
    f.address = String(settings.address || "");
    f.port = String(settings.port ?? "443");
    const hs = (ss.hysteriaSettings || {}) as Record<string, unknown>;
    f.pass = String(hs.auth || "");
    f.hyUp = String(hs.up || "");
    f.hyDown = String(hs.down || "");
    f.hyUdpIdleTimeout = hs.udpIdleTimeout != null ? String(hs.udpIdleTimeout) : "60";
    if (!f.alpn) f.alpn = "h3";
    if (!f.security || f.security === "none") f.security = "tls";
  }

  f.network = String(ss.network || "tcp");
  if (f.network === "splithttp") f.network = "splithttp";
  f.security = String(ss.security || "none");
  const tls = (ss.tlsSettings || {}) as Record<string, unknown>;
  const reality = (ss.realitySettings || {}) as Record<string, unknown>;
  f.sni = String(tls.serverName || reality.serverName || "");
  f.fingerprint = String(tls.fingerprint || reality.fingerprint || "chrome");
  f.allowInsecure = !!tls.allowInsecure;
  f.alpn = Array.isArray(tls.alpn) ? (tls.alpn as string[]).join(",") : "";
  f.realityPublicKey = String(reality.publicKey || "");
  f.realityShortId = String(reality.shortId || "");
  f.realitySpiderX = String(reality.spiderX || "");

  const ws = ss.wsSettings as Record<string, unknown> | undefined;
  const grpc = ss.grpcSettings as Record<string, unknown> | undefined;
  const hu = ss.httpupgradeSettings as Record<string, unknown> | undefined;
  const xhttp = (ss.xhttpSettings || ss.splithttpSettings) as Record<string, unknown> | undefined;
  const tcp = ss.tcpSettings as Record<string, unknown> | undefined;
  const kcp = ss.kcpSettings as Record<string, unknown> | undefined;
  if (ws) {
    f.path = String(ws.path || "/");
    f.hostHeader = String((ws.headers as Record<string, unknown>)?.Host || "");
  } else if (grpc) {
    f.path = String(grpc.serviceName || "");
    f.grpcMultiMode = !!grpc.multiMode;
    f.grpcAuthority = String(grpc.authority || "");
  } else if (hu) {
    f.path = String(hu.path || "/");
    f.hostHeader = String(hu.host || "");
  } else if (xhttp) {
    f.path = String(xhttp.path || "/");
    f.hostHeader = String(xhttp.host || "");
    f.xhttpMode = String(xhttp.mode || "auto");
    if (ss.xhttpSettings) f.network = "xhttp";
  } else if (tcp) {
    const hdr = (tcp.header || {}) as Record<string, unknown>;
    if (hdr.type === "http") {
      f.tcpHttpCamo = true;
      const req = (hdr.request || {}) as Record<string, unknown>;
      f.path = String((req.path as string[])?.[0] || "/");
      f.hostHeader = String(((req.headers as Record<string, unknown>)?.Host as string[])?.[0] || "");
    }
    const kcpHdr = (kcp?.header || {}) as Record<string, unknown>;
    if (kcp) {
      f.kcpSeed = String(kcp.seed || "");
      f.kcpHeader = String(kcpHdr.type || "none");
    }
  }

  if (mux?.enabled) {
    f.muxEnabled = true;
    f.muxConcurrency = mux.concurrency != null ? String(mux.concurrency) : "8";
    f.muxXudpConcurrency = mux.xudpConcurrency != null ? String(mux.xudpConcurrency) : "16";
    f.muxXudpProxyUDP443 = String(mux.xudpProxyUDP443 || "reject");
  }

  const sockopt = ss.sockopt as Record<string, unknown> | undefined;
  if (sockopt && Object.keys(sockopt).length > 0) {
    f.sockoptsEnabled = true;
    if (sockopt.dialerProxy) f.dialerProxy = String(sockopt.dialerProxy);
  }

  return f;
}

/** Merge form-built outbound with raw JSON so advanced fields (noises, finalmask, etc.) survive form edits. */
export function mergeOutboundWithRaw(built: Record<string, unknown>, raw?: Record<string, unknown>): Record<string, unknown> {
  if (!raw) return built;
  const out = { ...built };
  for (const key of ["mux", "proxySettings", "sendThrough"]) {
    if (built[key] == null && raw[key] != null) out[key] = raw[key];
  }
  if (!built.mux && raw.mux) out.mux = raw.mux;
  const builtMux = muxFromForm(outboundToForm(built));
  if (builtMux) out.mux = builtMux;

  const mergeDeep = (target: Record<string, unknown>, source: Record<string, unknown>, path: string) => {
    if (path === "settings" && source.settings && typeof source.settings === "object") {
      const bs = (built.settings || {}) as Record<string, unknown>;
      const rs = source.settings as Record<string, unknown>;
      const merged = { ...rs, ...bs };
      for (const k of ["noises", "rules", "ipsBlocked"]) {
        if (rs[k] != null && bs[k] == null) merged[k] = rs[k];
      }
      out.settings = merged;
      return;
    }
    if (path === "streamSettings" && source.streamSettings && typeof source.streamSettings === "object") {
      out.streamSettings = { ...(source.streamSettings as object), ...(built.streamSettings as object || {}) };
      const ss = source.streamSettings as Record<string, unknown>;
      const bs = (built.streamSettings || {}) as Record<string, unknown>;
      if (ss.sockopt && !bs.sockopt) (out.streamSettings as Record<string, unknown>).sockopt = ss.sockopt;
      if (ss.finalmask && !bs.finalmask) (out.streamSettings as Record<string, unknown>).finalmask = ss.finalmask;
      return;
    }
  };
  mergeDeep(out, raw, "settings");
  mergeDeep(out, raw, "streamSettings");
  return out;
}

const VALID_WG_DOMAIN_STRATEGIES = new Set<string>(WIREGUARD_DOMAIN_STRATEGIES as unknown as string[]);

/** Xray wireguard outbound rejects DNS-style strategies like UseIPv4. */
export function sanitizeWireguardOutbound(ob: Record<string, unknown>): Record<string, unknown> {
  if (ob.protocol !== "wireguard") return ob;
  const settings = (ob.settings || {}) as Record<string, unknown>;
  const ds = String(settings.domainStrategy || "");
  if (ds && !VALID_WG_DOMAIN_STRATEGIES.has(ds)) {
    const next = { ...settings };
    delete next.domainStrategy;
    return { ...ob, settings: next };
  }
  return ob;
}

export function sanitizeConfigOutbounds(cfg: Record<string, unknown>): Record<string, unknown> {
  const outbounds = (cfg.outbounds || []) as Record<string, unknown>[];
  return { ...cfg, outbounds: outbounds.map(sanitizeWireguardOutbound) };
}

export function finalizeOutboundFromForm(f: OutboundForm, raw?: Record<string, unknown>): Record<string, unknown> {
  const built = buildOutboundFromForm(f);
  let merged = mergeOutboundWithRaw(built, raw);
  const mux = muxFromForm(f);
  if (mux) merged.mux = mux;
  else if (!f.muxEnabled) delete merged.mux;

  if (f.dialerProxy.trim() && f.sockoptsEnabled) {
    const ss = (merged.streamSettings as Record<string, unknown>) || {};
    const sockopt = (ss.sockopt as Record<string, unknown>) || {};
    sockopt.dialerProxy = f.dialerProxy.trim();
    ss.sockopt = sockopt;
    merged.streamSettings = ss;
  } else if (!f.sockoptsEnabled) {
    const ss = merged.streamSettings as Record<string, unknown> | undefined;
    const sockopt = ss?.sockopt as Record<string, unknown> | undefined;
    if (sockopt) {
      const next = { ...sockopt };
      delete next.dialerProxy;
      if (Object.keys(next).length === 0) delete (ss as Record<string, unknown>).sockopt;
      else (ss as Record<string, unknown>).sockopt = next;
    }
  } else {
    const ss = merged.streamSettings as Record<string, unknown> | undefined;
    const sockopt = ss?.sockopt as Record<string, unknown> | undefined;
    if (sockopt && "dialerProxy" in sockopt) {
      delete sockopt.dialerProxy;
      if (Object.keys(sockopt).length === 0) delete (ss as Record<string, unknown>).sockopt;
    }
  }
  return sanitizeWireguardOutbound(merged);
}

export function outboundSummary(o: Record<string, unknown>): { address: string; transport: string; extra: string } {
  const protocol = String(o.protocol || "");
  const settings = (o.settings || {}) as Record<string, unknown>;
  const ss = (o.streamSettings || {}) as Record<string, unknown>;
  let address = "—";
  const servers = settings.servers as Record<string, unknown>[] | undefined;
  const vnext = settings.vnext as Record<string, unknown>[] | undefined;
  if (protocol === "freedom") address = "DIRECT";
  else if (protocol === "blackhole") address = "BLOCK";
  else if (protocol === "dns") address = String(settings.network || "dns");
  else if (servers?.[0]) address = `${servers[0].address}:${servers[0].port}`;
  else if (vnext?.[0]) address = `${vnext[0].address}:${vnext[0].port}`;
  else if (protocol === "wireguard") {
    const peers = settings.peers as Record<string, unknown>[] | undefined;
    address = peers?.[0]?.endpoint ? String(peers[0].endpoint) : "wireguard";
  } else if (protocol === "hysteria") {
    address = `${settings.address || "?"}:${settings.port ?? "?"}`;
  }
  const net = String(
    ss.network ||
      (protocol === "hysteria" ? "hysteria" : protocol === "freedom" || protocol === "blackhole" ? "" : "tcp"),
  );
  const sec = ss.security ? `/${String(ss.security)}` : "";
  const transport = net ? `${net}${sec}` : "—";
  const mux = (o.mux as Record<string, unknown>)?.enabled ? "mux" : "";
  const send = o.sendThrough ? "bind" : "";
  const extra = [mux, send].filter(Boolean).join(" · ") || "—";
  return { address, transport, extra };
}

export function validateOutboundTag(tag: string, outbounds: Record<string, unknown>[], editIdx: number | null): string | null {
  const t = tag.trim();
  if (!t) return "empty";
  if (t.includes(",")) return "comma";
  const dup = outbounds.findIndex((o, i) => i !== editIdx && String(o.tag) === t);
  if (dup >= 0) return "duplicate";
  return null;
}

export function cloneOutbound(o: Record<string, unknown>): Record<string, unknown> {
  const copy = JSON.parse(JSON.stringify(o)) as Record<string, unknown>;
  const base = String(copy.tag || "out");
  copy.tag = `${base}-copy`;
  return copy;
}

export { FINGERPRINTS, VLESS_FLOWS, SS_METHODS, KCP_HEADERS };
