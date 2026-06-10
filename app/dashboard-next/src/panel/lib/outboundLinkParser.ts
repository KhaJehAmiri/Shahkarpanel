/** Parse share links (vless/vmess/trojan/ss/…) into Xray outbound objects — 3x-ui parity. */

type StreamBuild = {
  network: string;
  security: string;
  sni: string;
  alpn: string;
  fingerprint: string;
  allowInsecure: boolean;
  path: string;
  hostHeader: string;
  tcpHttpCamo: boolean;
  kcpSeed: string;
  kcpHeader: string;
  grpcMultiMode: boolean;
  grpcAuthority: string;
  xhttpMode: string;
  realityPublicKey: string;
  realityShortId: string;
  realitySpiderX: string;
};

function b64Decode(raw: string): string {
  const s = raw.replace(/-/g, "+").replace(/_/g, "/");
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  return atob(s + pad);
}

function decodeRemark(hash: string): string {
  if (!hash) return "";
  try {
    return decodeURIComponent(hash.replace(/^#/, ""));
  } catch {
    return hash.replace(/^#/, "");
  }
}

function defaultTag(protocol: string, port: number): string {
  return `out-${protocol}-${port}`;
}

function buildStreamSettings(s: StreamBuild): Record<string, unknown> | undefined {
  const stream: Record<string, unknown> = { network: s.network };
  const needsStream =
    s.network !== "tcp" || s.security !== "none" || s.tcpHttpCamo
    || s.path || s.hostHeader;

  if (!needsStream && s.security === "none") return undefined;

  if (s.network === "tcp" && s.tcpHttpCamo) {
    stream.tcpSettings = {
      header: {
        type: "http",
        request: {
          path: [s.path || "/"],
          headers: s.hostHeader ? { Host: [s.hostHeader] } : {},
        },
      },
    };
  } else if (s.network === "ws") {
    stream.wsSettings = {
      path: s.path || "/",
      headers: s.hostHeader ? { Host: s.hostHeader } : undefined,
    };
  } else if (s.network === "grpc") {
    stream.grpcSettings = {
      serviceName: s.path || "",
      multiMode: s.grpcMultiMode,
      authority: s.grpcAuthority || undefined,
    };
  } else if (s.network === "httpupgrade") {
    stream.httpupgradeSettings = { path: s.path || "/", host: s.hostHeader || undefined };
  } else if (s.network === "xhttp" || s.network === "splithttp") {
    const key = s.network === "xhttp" ? "xhttpSettings" : "splithttpSettings";
    stream[key] = {
      path: s.path || "/",
      host: s.hostHeader || undefined,
      ...(s.network === "xhttp" ? { mode: s.xhttpMode || "auto" } : {}),
    };
    if (s.network === "xhttp") stream.network = "xhttp";
  } else if (s.network === "kcp") {
    stream.kcpSettings = {
      seed: s.kcpSeed || undefined,
      header: { type: s.kcpHeader || "none" },
    };
  }

  if (s.security === "tls") {
    stream.security = "tls";
    const alpn = s.alpn.split(",").map((x) => x.trim()).filter(Boolean);
    stream.tlsSettings = {
      serverName: s.sni || undefined,
      fingerprint: s.fingerprint && s.fingerprint !== "none" ? s.fingerprint : undefined,
      allowInsecure: s.allowInsecure || undefined,
      alpn: alpn.length ? alpn : undefined,
    };
  } else if (s.security === "reality") {
    stream.security = "reality";
    stream.realitySettings = {
      serverName: s.sni || undefined,
      fingerprint: s.fingerprint || "chrome",
      publicKey: s.realityPublicKey || undefined,
      shortId: s.realityShortId || undefined,
      spiderX: s.realitySpiderX || undefined,
    };
  }

  return stream;
}

function streamFromParams(params: URLSearchParams, link: string): StreamBuild {
  let type = params.get("type") ?? "tcp";
  if (type === "none") type = "tcp";
  const security = params.get("security") ?? "none";
  const headerType = params.get("headerType") ?? "none";
  const host = params.get("host") ?? "";
  const path = params.get("path") ?? params.get("serviceName") ?? "";

  const s: StreamBuild = {
    network: type,
    security,
    sni: params.get("sni") ?? "",
    alpn: params.get("alpn") ?? "",
    fingerprint: params.get("fp") ?? "chrome",
    allowInsecure: params.get("allowInsecure") === "1" || params.get("insecure") === "1",
    path: path || (type === "grpc" ? params.get("serviceName") ?? "" : "/"),
    hostHeader: host,
    tcpHttpCamo: type === "tcp" && headerType === "http",
    kcpSeed: type === "kcp" ? (path || "") : "",
    kcpHeader: headerType,
    grpcMultiMode: params.get("mode") === "multi",
    grpcAuthority: params.get("authority") ?? "",
    xhttpMode: params.get("mode") ?? "auto",
    realityPublicKey: params.get("pbk") ?? "",
    realityShortId: params.get("sid") ?? "",
    realitySpiderX: params.get("spx") ?? "",
  };

  if (type === "tcp" && !s.tcpHttpCamo) {
    s.path = path || "/";
  }

  return s;
}

function parseParamLink(link: string): Record<string, unknown> | null {
  let url: URL;
  try {
    url = new URL(link);
  } catch {
    return null;
  }

  const regex = /([^@]+):\/\/([^@]+)@(.+):(\d+)(.*)$/;
  const match = link.match(regex);
  if (!match) return null;

  const [, schemeRaw, userData, address, portStr] = match;
  let protocol = schemeRaw.toLowerCase();
  const port = parseInt(portStr, 10);
  if (!Number.isFinite(port)) return null;

  const params = url.searchParams;
  const stream = buildStreamSettings(streamFromParams(params, link));
  const remark = decodeRemark(url.hash);
  const tag = remark || defaultTag(protocol, port);

  let ob: Record<string, unknown> = { tag, protocol: protocol === "ss" ? "shadowsocks" : protocol };

  if (protocol === "vless") {
    ob.settings = {
      vnext: [{
        address,
        port,
        users: [{
          id: userData,
          encryption: params.get("encryption") ?? "none",
          ...(params.get("flow") ? { flow: params.get("flow") } : {}),
        }],
      }],
    };
  } else if (protocol === "trojan") {
    ob.settings = { servers: [{ address, port, password: userData }] };
  } else if (protocol === "ss") {
    protocol = "shadowsocks";
    ob.protocol = "shadowsocks";
    let method: string;
    let password: string;
    try {
      const decoded = b64Decode(userData);
      if (decoded.includes(":")) {
        [method, password] = decoded.split(":", 2);
      } else {
        return null;
      }
    } catch {
      const plain = decodeURIComponent(userData);
      const idx = plain.indexOf(":");
      if (idx < 0) return null;
      method = plain.slice(0, idx);
      password = plain.slice(idx + 1);
    }
    ob.settings = { servers: [{ address, port, method, password }] };
  } else {
    return null;
  }

  if (stream) ob.streamSettings = stream;
  return ob;
}

function parseVmessLink(link: string): Record<string, unknown> | null {
  const raw = link.slice("vmess://".length);
  let json: Record<string, unknown>;
  try {
    json = JSON.parse(b64Decode(raw));
  } catch {
    return null;
  }

  const port = parseInt(String(json.port ?? "443"), 10);
  const tag = String(json.ps || json.remark || defaultTag("vmess", port));
  const net = String(json.net || "tcp");
  const headerType = String(json.type || "none");

  const stream = buildStreamSettings({
    network: net,
    security: json.tls === "tls" ? "tls" : json.tls === "reality" ? "reality" : "none",
    sni: String(json.sni || ""),
    alpn: String(json.alpn || ""),
    fingerprint: String(json.fp || "chrome"),
    allowInsecure: json.allowInsecure === "1" || json.allowInsecure === 1,
    path: String(json.path || "/"),
    hostHeader: String(json.host || ""),
    tcpHttpCamo: net === "tcp" && headerType === "http",
    kcpSeed: net === "kcp" ? String(json.path || "") : "",
    kcpHeader: headerType,
    grpcMultiMode: headerType === "multi",
    grpcAuthority: String(json.authority || ""),
    xhttpMode: String(json.mode || "auto"),
    realityPublicKey: String(json.pbk || ""),
    realityShortId: String(json.sid || ""),
    realitySpiderX: String(json.spx || ""),
  });

  const ob: Record<string, unknown> = {
    tag,
    protocol: "vmess",
    settings: {
      vnext: [{
        address: String(json.add || ""),
        port,
        users: [{
          id: String(json.id || ""),
          security: String(json.scy || json.security || "auto"),
        }],
      }],
    },
  };
  if (stream) ob.streamSettings = stream;
  return ob;
}

function parseHysteria2Link(link: string): Record<string, unknown> | null {
  try {
    const raw = link.replace(/^hysteria2:\/\//i, "").replace(/^hy2:\/\//i, "");
    const hashIdx = raw.indexOf("#");
    const remark = hashIdx >= 0 ? decodeRemark(raw.slice(hashIdx)) : "";
    const body = hashIdx >= 0 ? raw.slice(0, hashIdx) : raw;
    const qIdx = body.indexOf("?");
    const query = qIdx >= 0 ? new URLSearchParams(body.slice(qIdx + 1)) : new URLSearchParams();
    const hostPart = qIdx >= 0 ? body.slice(0, qIdx) : body;
    let auth = "";
    let hostPort = hostPart;
    if (hostPart.includes("@")) {
      const at = hostPart.lastIndexOf("@");
      auth = decodeURIComponent(hostPart.slice(0, at));
      hostPort = hostPart.slice(at + 1);
    }
    const lastColon = hostPort.lastIndexOf(":");
    const address = lastColon > 0 ? hostPort.slice(0, lastColon) : hostPort;
    const port = lastColon > 0 ? parseInt(hostPort.slice(lastColon + 1), 10) : 443;
    const sni = query.get("sni") || query.get("peer") || address;
    const insecure = query.get("insecure") === "1" || query.get("allowInsecure") === "1";
    const up = query.get("up") || query.get("upmbps") || "";
    const down = query.get("down") || query.get("downmbps") || "";
    const tag = remark.trim() || defaultTag("hysteria", port);
    const alpn = query.get("alpn") || "h3";

    return {
      tag,
      protocol: "hysteria",
      settings: { version: 2, address, port: port || 443 },
      streamSettings: {
        network: "hysteria",
        security: "tls",
        tlsSettings: {
          serverName: sni,
          alpn: alpn.split(",").map((s) => s.trim()).filter(Boolean),
          allowInsecure: insecure || undefined,
          fingerprint: query.get("fp") || query.get("fingerprint") || "chrome",
        },
        hysteriaSettings: {
          version: 2,
          auth,
          ...(up ? { up: up.includes("mbps") ? up : `${up} mbps` } : {}),
          ...(down ? { down: down.includes("mbps") ? down : `${down} mbps` } : {}),
        },
      },
    };
  } catch {
    return null;
  }
}

/** Parse a share link into a Xray outbound object. Returns null if unsupported/invalid. */
export function parseOutboundShareLink(link: string): Record<string, unknown> | null {
  const trimmed = link.trim();
  if (!trimmed) return null;

  const scheme = trimmed.split("://")[0]?.toLowerCase();
  if (scheme === "vmess") return parseVmessLink(trimmed);
  if (scheme === "hysteria2" || scheme === "hy2") return parseHysteria2Link(trimmed);
  if (scheme === "vless" || scheme === "trojan" || scheme === "ss" || scheme === "shadowsocks") {
    return parseParamLink(trimmed.replace(/^shadowsocks:\/\//, "ss://"));
  }

  return null;
}

export const OUTBOUND_LINK_PLACEHOLDER =
  "vmess://  vless://  trojan://  ss://  hysteria2://  wireguard://";
