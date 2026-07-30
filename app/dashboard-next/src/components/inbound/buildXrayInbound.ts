import type {
  InboundFormState,
  NetworkType,
  ProtocolDefinition,
  SockoptSettings,
  TLSCertificate,
  TcpMaskEntry,
  VLESSFallback,
  TrojanFallback,
  XHTTPFieldSettings,
  XHTTPXmuxSettings,
} from "./types";
import { findProtocolDef } from "./types";

const SHAHKAR_INBOUND_KIND = "shahkarPanelKind";

function omitEmpty<T extends Record<string, unknown>>(obj: T): T {
  const out = { ...obj };
  for (const k of Object.keys(out)) {
    const v = out[k];
    if (v === "" || v === undefined || v === null) delete out[k];
    if (Array.isArray(v) && v.length === 0) delete out[k];
  }
  return out;
}

function ensureStreamOneH3Tls(stream: Record<string, unknown>): void {
  const xh = stream.xhttpSettings as Record<string, unknown> | undefined;
  if (stream.network !== "xhttp" || xh?.mode !== "stream-one") return;

  if (stream.security !== "tls" && stream.security !== "reality") {
    stream.security = "tls";
  }
  if (stream.security !== "tls") return;

  const tls = { ...((stream.tlsSettings || {}) as Record<string, unknown>) };
  const alpn = Array.isArray(tls.alpn) ? (tls.alpn as string[]) : [];
  if (!alpn.includes("h3")) {
    tls.alpn = ["h3", ...alpn.filter((a) => a !== "h3")];
    stream.tlsSettings = tls;
  }
}

function networkToXray(network: NetworkType): string {
  if (network === "raw") return "tcp";
  if (network === "mkcp") return "kcp";
  return network;
}

function parsePort(port: string): number | string {
  const s = port.trim();
  if (/^\d+$/.test(s)) return parseInt(s, 10);
  return s;
}

function numOrUndef(s: string): number | undefined {
  const t = s.trim();
  if (!t) return undefined;
  const n = parseInt(t, 10);
  return Number.isFinite(n) ? n : undefined;
}

function splitCsv(s: string): string[] {
  return s.split(",").map((x) => x.trim()).filter(Boolean);
}

function buildSockopt(s: SockoptSettings): Record<string, unknown> | undefined {
  if (!s.enabled) return undefined;

  const sock: Record<string, unknown> = {};
  if (s.acceptProxyProtocol) sock.acceptProxyProtocol = true;
  if (s.tcpFastOpen) sock.tcpFastOpen = true;
  const mark = numOrUndef(s.mark);
  if (mark !== undefined) sock.mark = mark;
  if (s.tproxy.trim() && s.tproxy !== "off") sock.tproxy = s.tproxy.trim();
  if (s.tcpCongestion.trim()) sock.tcpcongestion = s.tcpCongestion.trim();
  const kai = numOrUndef(s.tcpKeepAliveInterval);
  if (kai !== undefined) sock.tcpKeepAliveInterval = kai;
  const kad = numOrUndef(s.tcpKeepAliveIdle);
  if (kad !== undefined) sock.tcpKeepAliveIdle = kad;
  const maxSeg = numOrUndef(s.tcpMaxSeg);
  if (maxSeg !== undefined) sock.tcpMaxSeg = maxSeg;
  const userTimeout = numOrUndef(s.tcpUserTimeout);
  if (userTimeout !== undefined) sock.tcpUserTimeout = userTimeout;
  const windowClamp = numOrUndef(s.tcpWindowClamp);
  if (windowClamp !== undefined) sock.tcpWindowClamp = windowClamp;
  if (s.v6Only) sock.v6only = true;

  if (s.realClientIp === "cloudflare") {
    sock.trustedXForwardedFor = ["geoip:cloudflare"];
  } else if (s.realClientIp === "proxy") {
    sock.penetrate = true;
  } else {
    const trusted = splitCsv(s.trustedXForwardedFor);
    if (trusted.length) sock.trustedXForwardedFor = trusted;
  }

  if (s.domainStrategy.trim()) sock.domainStrategy = s.domainStrategy.trim();
  if (s.penetrate) sock.penetrate = true;

  for (const opt of s.customOptions) {
    const key = opt.key.trim();
    if (!key) continue;
    const raw = opt.value.trim();
    if (!raw) continue;
    if (raw === "true") sock[key] = true;
    else if (raw === "false") sock[key] = false;
    else if (/^-?\d+$/.test(raw)) sock[key] = parseInt(raw, 10);
    else {
      try {
        sock[key] = JSON.parse(raw) as unknown;
      } catch {
        sock[key] = raw;
      }
    }
  }

  return Object.keys(sock).length ? sock : undefined;
}

function buildTcpMasks(masks: TcpMaskEntry[]): unknown[] | undefined {
  if (!masks.length) return undefined;
  return masks.map((m) => ({
    type: m.type,
    settings: omitEmpty({
      packets: m.settings.packets.trim() || undefined,
      lengths: m.settings.lengths.map((x) => x.trim()).filter(Boolean),
      delays: m.settings.delays.map((x) => x.trim()).filter(Boolean),
      maxSplit: m.settings.maxSplit.trim() || undefined,
    }),
  }));
}

function buildFallbacks(fallbacks: VLESSFallback[] | TrojanFallback[]): unknown[] {
  return fallbacks
    .filter((f) => String(f.dest).trim())
    .map((f) =>
      omitEmpty({
        name: f.name || undefined,
        alpn: f.alpn || undefined,
        path: f.path || undefined,
        dest: f.dest,
        xver: f.xver || undefined,
      }),
    );
}

function buildTlsSettings(state: InboundFormState): Record<string, unknown> {
  const t = state.tlsSettings;
  const certs = t.certificates
    .map((c: TLSCertificate) => {
      const cert: Record<string, unknown> = { usage: c.usage };
      if (!c.pemMode && c.certificateFile && c.keyFile) {
        cert.certificateFile = c.certificateFile;
        cert.keyFile = c.keyFile;
      } else if (c.certificate.some(Boolean) && c.key.some(Boolean)) {
        cert.certificate = c.certificate.filter(Boolean);
        cert.key = c.key.filter(Boolean);
      }
      if (c.ocspStapling) cert.ocspStapling = c.ocspStapling;
      if (c.buildChain) cert.buildChain = c.buildChain;
      if (c.oneTimeLoading) cert.oneTimeLoading = true;
      return cert;
    })
    .filter((c) => Object.keys(c).length > 1);

  return omitEmpty({
    serverName: t.serverName || undefined,
    rejectUnknownSni: t.rejectUnknownSni || undefined,
    allowInsecure: t.allowInsecure || undefined,
    alpn: t.alpn.length ? t.alpn : undefined,
    minVersion: t.minVersion,
    maxVersion: t.maxVersion,
    cipherSuites: t.cipherSuites || undefined,
    certificates: certs.length ? certs : undefined,
    disableSystemRoot: t.disableSystemRoot || undefined,
    enableSessionResumption: t.enableSessionResumption || undefined,
    fingerprint: t.fingerprint || undefined,
    pinnedPeerCertificateChainSha256: t.pinnedPeerCertificateChainSha256.length
      ? t.pinnedPeerCertificateChainSha256
      : undefined,
    curvePreferences: t.curvePreferences.length ? t.curvePreferences : undefined,
    masterKeyLog: t.masterKeyLog.trim() || undefined,
    verifyPeerCertInSubjectAltName: t.verifyPeerCertByName.length ? t.verifyPeerCertByName : undefined,
    echServerKeys:
      t.echEnabled && t.echServerKeys.some(Boolean) ? t.echServerKeys.filter(Boolean)[0] : undefined,
    echConfigList:
      t.echEnabled && t.echConfigList.some(Boolean) ? t.echConfigList.filter(Boolean)[0] : undefined,
  });
}

function buildRealitySettings(state: InboundFormState): Record<string, unknown> {
  const r = state.realitySettings;
  const target =
    r.target.trim() ||
    (r.serverNames[0] ? `${r.serverNames[0]}:443` : "www.cloudflare.com:443");
  const out: Record<string, unknown> = omitEmpty({
    show: r.show || undefined,
    xver: r.xver || undefined,
    serverNames: r.serverNames.length ? r.serverNames : undefined,
    privateKey: r.privateKey,
    minClientVer: r.minClientVer || undefined,
    maxClientVer: r.maxClientVer || undefined,
    maxTimeDiff: r.maxTimeDiff || undefined,
    shortIds: r.shortIds.length ? r.shortIds : undefined,
    mldsa65Verify: r.mldsa65Verify.trim() || r.mldsa65Seed.trim() || undefined,
    settings: omitEmpty({
      publicKey: r.publicKey || undefined,
      fingerprint: r.fingerprint || undefined,
      spiderX: r.spiderX || undefined,
      mldsa65Seed: r.mldsa65Seed.trim() || undefined,
    }),
  });
  const up = r.limitFallbackUpload;
  const down = r.limitFallbackDownload;
  if (up.afterBytes || up.bytesPerSec || up.burstBytesPerSec) out.limitFallbackUpload = up;
  if (down.afterBytes || down.bytesPerSec || down.burstBytesPerSec) out.limitFallbackDownload = down;
  out.target = target;
  return out;
}

function buildXhttpXmux(x: XHTTPXmuxSettings): Record<string, unknown> | undefined {
  const xmux = omitEmpty({
    maxConcurrency: x.maxConcurrency || undefined,
    maxConnections: x.maxConnections || undefined,
    cMaxReuseTimes: x.cMaxReuseTimes || undefined,
    hMaxRequestTimes: x.hMaxRequestTimes || undefined,
    hMaxReusableSecs: x.hMaxReusableSecs || undefined,
    hKeepAlivePeriod: x.hKeepAlivePeriod || undefined,
  });
  return Object.keys(xmux).length ? xmux : undefined;
}

function buildStreamHeaders(
  host: string,
  extraHeaders: Record<string, string[]>,
): Record<string, string> | undefined {
  const headers: Record<string, string> = {};
  for (const [key, vals] of Object.entries(extraHeaders)) {
    const k = key.trim();
    const v = vals.map((x) => x.trim()).find(Boolean);
    if (k && v) headers[k] = v;
  }
  if (host.trim()) headers.Host = host.trim();
  return Object.keys(headers).length ? headers : undefined;
}

function buildXhttpFields(x: XHTTPFieldSettings): Record<string, unknown> {
  return omitEmpty({
    path: x.path,
    host: x.host || undefined,
    mode: x.mode !== "auto" ? x.mode : undefined,
    noSSEHeader: x.noSSEHeader || undefined,
    noGRPCHeader: x.noGRPCHeader || undefined,
    scMaxEachPostBytes: x.scMaxEachPostBytes || undefined,
    scMaxBufferedPosts: x.scMaxBufferedPosts || undefined,
    scMaxConcurrentPosts: x.scMaxConcurrentPosts || undefined,
    scMinPostsIntervalMs: x.scMinPostsIntervalMs || undefined,
    scStreamUpServerSecs: x.scStreamUpServerSecs || undefined,
    serverMaxHeaderBytes: x.serverMaxHeaderBytes || undefined,
    keepAlivePeriod: x.keepAlivePeriod || undefined,
    xPaddingBytes: x.xPaddingBytes || undefined,
    uplinkHTTPMethod: x.uplinkHTTPMethod.trim() || undefined,
  });
}

function buildHysteriaMasquerade(state: InboundFormState): Record<string, unknown> | undefined {
  const m = state.hysteria2.masquerade;
  if (!m.enabled) return undefined;
  return omitEmpty({
    type: m.type.trim() || undefined,
    url: m.url.trim() || undefined,
    dir: m.dir.trim() || undefined,
    rewriteHost: m.rewriteHost || undefined,
    insecure: m.insecure || undefined,
    content: m.content.trim() || undefined,
    statusCode: m.statusCode || undefined,
  });
}

function buildProtocolSettings(
  state: InboundFormState,
  protocols: ProtocolDefinition[],
): Record<string, unknown> {
  const proto = state.protocol;
  const def = findProtocolDef(protocols, proto);

  if (def && !["vless", "vmess", "trojan", "shadowsocks", "http", "socks", "mixed", "wireguard", "hysteria", "amneziawg", "tun", "dokodemo-door"].includes(proto)) {
    return { ...state.customSettings };
  }

  switch (proto) {
    case "vless": {
      const v = state.vless;
      const fallbacks = buildFallbacks(v.fallbacks);
      const settings: Record<string, unknown> = {
        clients: [],
        decryption: v.decryption || "none",
      };
      if (v.encryption && v.encryption !== "none") settings.encryption = v.encryption;
      const seeds = [v.visionTestSeed1, v.visionTestSeed2, v.visionTestSeed3, v.visionTestSeed4]
        .map((s) => parseInt(s, 10))
        .filter((n) => Number.isFinite(n));
      if (seeds.length === 4) settings.testSeed = seeds;
      if (fallbacks.length) settings.fallbacks = fallbacks;
      return settings;
    }
    case "vmess": {
      const clients = state.vmess.clients
        .filter((u) => u.id.trim())
        .map((u) =>
          omitEmpty({
            id: u.id.trim(),
            alterId: u.alterId,
            security: u.security,
            level: u.level,
            email: u.email || undefined,
          }),
        );
      return { clients };
    }
    case "trojan": {
      const clients = state.trojan.clients
        .filter((u) => u.password.trim())
        .map((u) =>
          omitEmpty({
            password: u.password,
            level: u.level,
            email: u.email || undefined,
          }),
        );
      const fallbacks = buildFallbacks(state.trojan.fallbacks);
      return omitEmpty({ clients, fallbacks: fallbacks.length ? fallbacks : undefined });
    }
    case "shadowsocks": {
      const ss = state.shadowsocks;
      if (ss.method.startsWith("2022-blake3")) {
        return omitEmpty({
          method: ss.method,
          password: ss.password,
          network: ss.network,
          ivCheck: ss.ivCheck || undefined,
        });
      }
      return omitEmpty({
        method: ss.method,
        network: ss.network,
        ivCheck: ss.ivCheck || undefined,
      });
    }
    case "http": {
      const h = state.http;
      const accounts = h.accounts
        .filter((a) => a.user.trim())
        .map((a) => ({ user: a.user, pass: a.pass }));
      return omitEmpty({
        timeout: h.timeout,
        allowTransparent: h.allowTransparent || undefined,
        userLevel: h.userLevel || undefined,
        accounts: accounts.length ? accounts : [],
      });
    }
    case "socks":
    case "mixed": {
      const s = state.socks;
      const accounts = s.accounts
        .filter((a) => a.user.trim())
        .map((a) => ({ user: a.user, pass: a.pass }));
      return omitEmpty({
        auth: s.auth,
        accounts: s.auth === "password" && accounts.length ? accounts : [],
        udp: s.udp,
        ip: s.udp && s.ip ? s.ip : undefined,
        userLevel: s.userLevel || undefined,
      });
    }
    case "wireguard":
    case "amneziawg": {
      const wg = state.wireguard;
      const peers = wg.peers
        .filter((p) => p.publicKey.trim())
        .map((p) => ({
          publicKey: p.publicKey.trim(),
          allowedIPs: p.allowedIPs.length ? p.allowedIPs : ["0.0.0.0/0"],
        }));
      const settings: Record<string, unknown> = omitEmpty({
        secretKey: wg.secretKey.trim(),
        mtu: wg.mtu,
        peers,
        address: wg.address.length ? wg.address : undefined,
        dns: wg.dns.length ? wg.dns : undefined,
        noKernelTun: wg.noKernelTun || undefined,
        domainStrategy: wg.domainStrategy.trim() || undefined,
      });
      if (proto === "amneziawg") {
        settings[SHAHKAR_INBOUND_KIND] = "amneziawg";
        try {
          const extra = JSON.parse(state.amneziaExtraJson) as Record<string, unknown>;
          Object.assign(settings, extra);
        } catch {
          /* ignore invalid extra json at build */
        }
      }
      return settings;
    }
    case "hysteria": {
      const users = state.hysteria2.users
        .filter((u) => u.auth.trim())
        .map((u) =>
          omitEmpty({ auth: u.auth, level: u.level, email: u.email || undefined }),
        );
      return { version: 2, clients: users };
    }
    case "tun": {
      const t = state.tun;
      return omitEmpty({
        name: t.name,
        mtu: t.mtu,
        gateway: t.gateway.length ? t.gateway : undefined,
        dns: t.dns.length ? t.dns : undefined,
        userLevel: t.userLevel,
        autoSystemRoutingTable: t.autoSystemRoutingTable.length
          ? t.autoSystemRoutingTable
          : undefined,
        autoOutboundsInterface: t.autoOutboundsInterface || undefined,
      });
    }
    case "dokodemo-door": {
      const d = state.dokodemo;
      if (d.tunnelRewriteEnabled && d.rewriteAddress.trim()) {
        let portMap: Record<string, unknown> | undefined;
        if (d.portMapJson.trim()) {
          try {
            portMap = JSON.parse(d.portMapJson) as Record<string, unknown>;
          } catch {
            portMap = undefined;
          }
        }
        return omitEmpty({
          rewriteAddress: d.rewriteAddress.trim(),
          rewritePort: d.rewritePort,
          allowedNetwork: d.allowedNetwork,
          portMap,
          timeout: d.timeout,
          followRedirect: d.followRedirect || undefined,
          userLevel: d.userLevel || undefined,
        });
      }
      return omitEmpty({
        address: d.address,
        port: d.port,
        network: d.network,
        timeout: d.timeout,
        followRedirect: d.followRedirect || undefined,
        userLevel: d.userLevel || undefined,
      });
    }
    default:
      return { ...state.customSettings };
  }
}

function buildStreamSettings(
  state: InboundFormState,
  def: ProtocolDefinition | undefined,
): Record<string, unknown> | undefined {
  if (!def?.hasStream) return undefined;

  const network = state.network;
  const xrayNet = networkToXray(network);
  const stream: Record<string, unknown> = {
    network: xrayNet,
    security: state.security,
  };

  if (network === "raw") {
    const raw = state.rawSettings;
    const tcp: Record<string, unknown> = {
      acceptProxyProtocol: raw.acceptProxyProtocol || undefined,
    };
    if (raw.httpObfuscation) {
      tcp.header = omitEmpty({
        type: "http",
        request: {
          version: raw.request.version || "1.1",
          method: raw.request.method || "GET",
          path: [raw.request.path || "/"],
          headers: Object.keys(raw.request.headers).length ? raw.request.headers : undefined,
        },
        response: {
          version: raw.response.version || "1.1",
          status: raw.response.status || "200",
          reason: raw.response.reason || "OK",
          headers: Object.keys(raw.response.headers).length ? raw.response.headers : undefined,
        },
      });
    } else {
      tcp.header = { type: "none" };
    }
    stream.tcpSettings = tcp;
  } else if (network === "ws") {
    const ws = state.wsSettings;
    stream.wsSettings = omitEmpty({
      path: ws.path,
      headers: buildStreamHeaders(ws.host, ws.extraHeaders),
      acceptProxyProtocol: ws.acceptProxyProtocol || undefined,
      heartbeatPeriod: ws.heartbeatPeriod || undefined,
      maxEarlyData: ws.maxEarlyData || undefined,
      earlyDataHeaderName: ws.earlyDataHeaderName || undefined,
      browserForwarding: ws.browserForwarding || undefined,
    });
  } else if (network === "grpc") {
    const g = state.grpcSettings;
    stream.grpcSettings = omitEmpty({
      serviceName: g.serviceName,
      authority: g.authority.trim() || undefined,
      user_agent: g.userAgent.trim() || undefined,
      multiMode: g.multiMode || undefined,
      idle_timeout: g.idleTimeout || undefined,
      health_check_timeout: g.healthCheckTimeout || undefined,
      permit_without_stream: g.permitWithoutStream || undefined,
      initial_windows_size: g.initialWindowsSize || undefined,
    });
  } else if (network === "xhttp") {
    const x = state.xhttpSettings;
    const xmux = buildXhttpXmux(x.xmux);
    const dl = x.downloadSettings ? buildXhttpFields(x.downloadSettings as XHTTPFieldSettings) : undefined;
    stream.xhttpSettings = omitEmpty({
      ...buildXhttpFields(x),
      xmux,
      downloadSettings: dl && Object.keys(dl).length ? dl : undefined,
    });
  } else if (network === "httpupgrade") {
    const h = state.httpupgradeSettings;
    stream.httpupgradeSettings = omitEmpty({
      path: h.path,
      host: h.host || undefined,
      headers: buildStreamHeaders(h.host, h.extraHeaders),
      acceptProxyProtocol: h.acceptProxyProtocol || undefined,
    });
  } else if (network === "mkcp") {
    const k = state.mkcpSettings;
    const kcp: Record<string, unknown> = omitEmpty({
      mtu: k.mtu,
      tti: k.tti,
      uplinkCapacity: k.uplinkCapacity,
      downlinkCapacity: k.downlinkCapacity,
      congestion: k.congestion || undefined,
      readBufferSize: k.readBufferSize * 1024 * 1024,
      writeBufferSize: k.writeBufferSize * 1024 * 1024,
      cwnd: k.cwnd || undefined,
      maxSendingWindow: k.maxSendingWindow || undefined,
      header: omitEmpty({
        type: k.header.type,
        domain: k.header.domain.trim() || undefined,
      }),
      seed: k.seed || undefined,
    });
    const udpMasks = buildTcpMasks(k.udpMasks);
    if (udpMasks) kcp.masks = udpMasks;
    stream.kcpSettings = kcp;
  } else if (network === "quic") {
    const q = state.quicSettings;
    const key = q.key.trim();
    const path = key ? (key.startsWith("/") ? key : `/${key}`) : "/";
    stream.network = "xhttp";
    stream.xhttpSettings = omitEmpty({
      path,
      mode: "stream-one",
    });
  } else if (network === "http") {
    const h = state.httpTransportSettings;
    stream.httpSettings = omitEmpty({
      path: h.path,
      host: h.host.length ? h.host : undefined,
    });
  }

  const sockopt = buildSockopt(state.sockoptSettings);
  if (sockopt) stream.sockopt = sockopt;

  const noises = buildTcpMasks(state.tcpMasks);
  if (noises) stream.noises = noises;

  if (state.protocol === "hysteria") {
    stream.network = "hysteria";
    stream.security = "tls";
    const masquerade = buildHysteriaMasquerade(state);
    stream.hysteriaSettings = omitEmpty({
      version: 2,
      masquerade,
    });
  }

  if (state.security === "tls") {
    stream.tlsSettings = buildTlsSettings(state);
  } else if (state.security === "reality") {
    stream.realitySettings = buildRealitySettings(state);
  }

  ensureStreamOneH3Tls(stream);

  return stream;
}

const SNIFF_DEST_OVERRIDE_ALLOWED = new Set(["http", "tls", "quic", "fakedns"]);

function buildSniffing(state: InboundFormState): Record<string, unknown> | undefined {
  const s = state.sniffing;
  if (!s.enabled) return undefined;
  const destOverride = s.destOverride.filter((item) => SNIFF_DEST_OVERRIDE_ALLOWED.has(item));
  return omitEmpty({
    enabled: true,
    destOverride: destOverride.length ? destOverride : undefined,
    metadataOnly: s.metadataOnly || undefined,
    routeOnly: s.routeOnly || undefined,
    domainsExcluded: s.excludedDomains.length ? s.excludedDomains : undefined,
    ipsExcluded: s.excludedIps.length ? s.excludedIps : undefined,
  });
}

/** Build xray-core InboundObject JSON from form state. */
export function buildXrayInbound(
  state: InboundFormState,
  protocols: ProtocolDefinition[],
): Record<string, unknown> {
  const def = findProtocolDef(protocols, state.protocol);
  const xrayProtocol =
    state.protocol === "amneziawg" ? "wireguard" : state.protocol;

  const inbound: Record<string, unknown> = {
    tag: state.basics.remark.trim(),
    protocol: xrayProtocol,
    settings: buildProtocolSettings(state, protocols),
  };

  if (state.protocol !== "tun") {
    inbound.listen = state.basics.listen.trim() || "0.0.0.0";
    inbound.port = parsePort(state.basics.port);
  }

  const stream = buildStreamSettings(state, def);
  if (stream && def?.hasStream) {
    inbound.streamSettings = stream;
  } else if (state.protocol === "hysteria") {
    inbound.streamSettings = stream;
  }

  if (def?.hasSniffing) {
    const sniffing = buildSniffing(state);
    if (sniffing) inbound.sniffing = sniffing;
  }

  if (state.protocol === "shadowsocks" && inbound.streamSettings) {
    const ssStream = inbound.streamSettings as Record<string, unknown>;
    if (ssStream.security === "reality") {
      ssStream.security = "none";
      delete ssStream.realitySettings;
    }
  }

  if (
    state.protocol === "wireguard" ||
    state.protocol === "amneziawg" ||
    state.protocol === "tun"
  ) {
    delete inbound.streamSettings;
    if (state.protocol === "tun" || state.protocol === "wireguard" || state.protocol === "amneziawg") {
      delete inbound.sniffing;
    }
  }

  return inbound;
}
