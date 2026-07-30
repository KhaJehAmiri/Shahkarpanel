import {
  defaultInboundFormState,
  defaultSockoptSettings,
  defaultXhttpXmuxSettings,
  findProtocolDef,
  isKnownProtocol,
  type InboundFormState,
  type NetworkType,
  type ProtocolDefinition,
  type RealClientIpMode,
  type SniffDestOverride,
  type SSMethod,
  type TcpMaskEntry,
  type TLSCertificate,
  type TrojanFallback,
  type VLESSFallback,
} from "./types";
import { TLS_CIPHER_PRESETS } from "./types";

const SHAHKAR_INBOUND_KIND = "shahkarPanelKind";

function parseEchField(raw: unknown): string[] {
  if (typeof raw === "string" && raw.trim()) return [raw.trim()];
  if (Array.isArray(raw)) return raw.map((x) => String(x).trim()).filter(Boolean);
  return [];
}

function detectCipherPreset(cipherSuites: string): string {
  if (!cipherSuites.trim()) return "auto";
  const match = TLS_CIPHER_PRESETS.find((p) => p.id !== "auto" && p.value === cipherSuites.trim());
  return match?.id ?? "custom";
}

const KNOWN_SOCKOPT_KEYS = new Set([
  "acceptProxyProtocol",
  "tcpFastOpen",
  "mark",
  "tproxy",
  "tcpcongestion",
  "tcpCongestion",
  "tcpKeepAliveInterval",
  "tcpKeepAliveIdle",
  "tcpMaxSeg",
  "tcpUserTimeout",
  "tcpWindowClamp",
  "v6only",
  "trustedXForwardedFor",
  "domainStrategy",
  "penetrate",
]);

function str(v: unknown, fallback = ""): string {
  return v === undefined || v === null ? fallback : String(v);
}

function num(v: unknown, fallback = 0): number {
  const n = typeof v === "number" ? v : parseInt(String(v), 10);
  return Number.isFinite(n) ? n : fallback;
}

function headersToRecord(raw: unknown): Record<string, string[]> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: Record<string, string[]> = {};
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (Array.isArray(v)) out[k] = v.map(String);
    else if (v != null) out[k] = [String(v)];
  }
  return out;
}

function parseFallbacks(raw: unknown): VLESSFallback[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const fb = (item || {}) as Record<string, unknown>;
    return {
      dest: str(fb.dest),
      path: str(fb.path),
      xver: (num(fb.xver) as 0 | 1 | 2) || 0,
      alpn: str(fb.alpn),
      name: str(fb.name),
    };
  });
}

function xrayNetworkToForm(net: string): NetworkType {
  if (net === "tcp") return "raw";
  if (net === "kcp") return "mkcp";
  if (net === "splithttp") return "xhttp";
  if (net === "h2" || net === "h3") return "http";
  if (net === "quic") return "xhttp";
  if (["raw", "ws", "grpc", "xhttp", "httpupgrade", "mkcp", "quic", "http"].includes(net)) {
    return net as NetworkType;
  }
  return "raw";
}

function splitHostFromHeaders(raw: unknown): { host: string; extraHeaders: Record<string, string[]> } {
  const headers = headersToRecord(raw);
  const hostVals = headers.Host || [];
  const host = hostVals[0] || "";
  const extraHeaders = { ...headers };
  delete extraHeaders.Host;
  return { host, extraHeaders };
}

function parseXhttpFieldSlice(xh: Record<string, unknown>): InboundFormState["xhttpSettings"] {
  return {
    path: str(xh.path, "/"),
    host: str(xh.host),
    mode: (str(xh.mode, "auto") as InboundFormState["xhttpSettings"]["mode"]) || "auto",
    noSSEHeader: Boolean(xh.noSSEHeader),
    noGRPCHeader: Boolean(xh.noGRPCHeader),
    scMaxEachPostBytes: num(xh.scMaxEachPostBytes),
    scMaxBufferedPosts: num(xh.scMaxBufferedPosts),
    scMaxConcurrentPosts: num(xh.scMaxConcurrentPosts),
    scMinPostsIntervalMs: num(xh.scMinPostsIntervalMs),
    scStreamUpServerSecs: num(xh.scStreamUpServerSecs),
    serverMaxHeaderBytes: num(xh.serverMaxHeaderBytes),
    keepAlivePeriod: num(xh.keepAlivePeriod),
    xPaddingBytes: str(xh.xPaddingBytes),
    uplinkHTTPMethod: str(xh.uplinkHTTPMethod),
    xmux: defaultXhttpXmuxSettings(),
  };
}

function parseXhttpFields(xh: Record<string, unknown>): InboundFormState["xhttpSettings"] {
  const xmuxRaw = (xh.xmux || {}) as Record<string, unknown>;
  const base = parseXhttpFieldSlice(xh);
  return {
    ...base,
    xmux: {
      maxConcurrency: num(xmuxRaw.maxConcurrency),
      maxConnections: num(xmuxRaw.maxConnections),
      cMaxReuseTimes: num(xmuxRaw.cMaxReuseTimes),
      hMaxRequestTimes: num(xmuxRaw.hMaxRequestTimes),
      hMaxReusableSecs: num(xmuxRaw.hMaxReusableSecs),
      hKeepAlivePeriod: num(xmuxRaw.hKeepAlivePeriod),
    },
    downloadSettings: xh.downloadSettings
      ? (() => {
          const dl = parseXhttpFieldSlice((xh.downloadSettings || {}) as Record<string, unknown>);
          const { xmux: _xmux, downloadSettings: _dl, ...rest } = dl;
          return rest;
        })()
      : undefined,
  };
}

function parseTlsCertificates(raw: unknown): TLSCertificate[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const c = (item || {}) as Record<string, unknown>;
    const certArr = Array.isArray(c.certificate) ? (c.certificate as string[]) : [];
    const keyArr = Array.isArray(c.key) ? (c.key as string[]) : [];
    const pemMode = !!(certArr.length || keyArr.length);
    return {
      usage: (str(c.usage, "encipherment") as TLSCertificate["usage"]) || "encipherment",
      certificateFile: str(c.certificateFile),
      keyFile: str(c.keyFile),
      certificate: certArr,
      key: keyArr,
      ocspStapling: num(c.ocspStapling),
      buildChain: Boolean(c.buildChain),
      oneTimeLoading: Boolean(c.oneTimeLoading),
      pemMode,
    };
  });
}

function parseTcpMasks(raw: unknown): TcpMaskEntry[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const m = (item || {}) as Record<string, unknown>;
    const s = (m.settings || {}) as Record<string, unknown>;
    return {
      type: (str(m.type, "fragment") as TcpMaskEntry["type"]) || "fragment",
      settings: {
        packets: str(s.packets, "1-3"),
        lengths: Array.isArray(s.lengths) ? (s.lengths as unknown[]).map(String) : [],
        delays: Array.isArray(s.delays) ? (s.delays as unknown[]).map(String) : [],
        maxSplit: str(s.maxSplit),
      },
    };
  });
}

function parseSockopt(sock: Record<string, unknown>) {
  const base = defaultSockoptSettings();
  if (!sock || !Object.keys(sock).length) {
    return { ...base, enabled: false };
  }

  base.enabled = true;
  base.acceptProxyProtocol = Boolean(sock.acceptProxyProtocol);
  base.tcpFastOpen = Boolean(sock.tcpFastOpen);
  base.mark = sock.mark != null ? String(sock.mark) : "0";
  base.tproxy = str(sock.tproxy);
  base.tcpCongestion = str(sock.tcpcongestion || sock.tcpCongestion);
  base.tcpKeepAliveInterval = sock.tcpKeepAliveInterval != null ? String(sock.tcpKeepAliveInterval) : "0";
  base.tcpKeepAliveIdle = sock.tcpKeepAliveIdle != null ? String(sock.tcpKeepAliveIdle) : "0";
  base.tcpMaxSeg = sock.tcpMaxSeg != null ? String(sock.tcpMaxSeg) : "0";
  base.tcpUserTimeout = sock.tcpUserTimeout != null ? String(sock.tcpUserTimeout) : "0";
  base.tcpWindowClamp = sock.tcpWindowClamp != null ? String(sock.tcpWindowClamp) : "0";
  base.v6Only = Boolean(sock.v6only);
  base.penetrate = Boolean(sock.penetrate);
  base.domainStrategy = str(sock.domainStrategy);

  const trusted = sock.trustedXForwardedFor;
  if (Array.isArray(trusted) && trusted.some((x) => String(x).includes("cloudflare"))) {
    base.realClientIp = "cloudflare";
  } else if (base.penetrate || base.acceptProxyProtocol) {
    base.realClientIp = "proxy";
  } else {
    base.realClientIp = "direct";
    base.trustedXForwardedFor = Array.isArray(trusted) ? trusted.map(String).join(", ") : "";
  }

  const customOptions: Array<{ key: string; value: string }> = [];
  for (const [key, value] of Object.entries(sock)) {
    if (KNOWN_SOCKOPT_KEYS.has(key)) continue;
    customOptions.push({
      key,
      value: typeof value === "string" ? value : JSON.stringify(value),
    });
  }
  base.customOptions = customOptions;
  return base;
}

function parseStream(state: InboundFormState, ss: Record<string, unknown>) {
  const net = xrayNetworkToForm(str(ss.network, "tcp"));
  state.network = net;
  state.security = (str(ss.security, "none") as InboundFormState["security"]) || "none";

  const tcp = (ss.tcpSettings || {}) as Record<string, unknown>;
  const hdr = (tcp.header || {}) as Record<string, unknown>;
  const req = (hdr.request || {}) as Record<string, unknown>;
  const res = (hdr.response || {}) as Record<string, unknown>;
  const paths = req.path;
  state.rawSettings = {
    acceptProxyProtocol: Boolean(tcp.acceptProxyProtocol),
    httpObfuscation: str(hdr.type) === "http",
    request: {
      version: str(req.version, "1.1"),
      method: str(req.method, "GET"),
      path: Array.isArray(paths) ? str(paths[0], "/") : str(paths, "/"),
      headers: headersToRecord(req.headers),
    },
    response: {
      version: str(res.version, "1.1"),
      status: str(res.status, "200"),
      reason: str(res.reason, "OK"),
      headers: headersToRecord(res.headers),
    },
  };

  const ws = (ss.wsSettings || {}) as Record<string, unknown>;
  const wsHeaderSplit = splitHostFromHeaders(ws.headers);
  state.wsSettings = {
    path: str(ws.path, "/"),
    host: wsHeaderSplit.host || str(ws.host),
    extraHeaders: wsHeaderSplit.extraHeaders,
    heartbeatPeriod: num(ws.heartbeatPeriod),
    maxEarlyData: num(ws.maxEarlyData),
    earlyDataHeaderName: str(ws.earlyDataHeaderName),
    browserForwarding: Boolean(ws.browserForwarding),
    acceptProxyProtocol: Boolean(ws.acceptProxyProtocol),
  };

  const grpc = (ss.grpcSettings || {}) as Record<string, unknown>;
  state.grpcSettings = {
    serviceName: str(grpc.serviceName),
    authority: str(grpc.authority),
    userAgent: str(grpc.user_agent || grpc.userAgent),
    multiMode: Boolean(grpc.multiMode),
    idleTimeout: num(grpc.idle_timeout),
    healthCheckTimeout: num(grpc.health_check_timeout),
    permitWithoutStream: Boolean(grpc.permit_without_stream),
    initialWindowsSize: num(grpc.initial_windows_size),
  };

  const xh = (ss.xhttpSettings || ss.splithttpSettings || {}) as Record<string, unknown>;
  state.xhttpSettings = parseXhttpFields(xh);

  const hu = (ss.httpupgradeSettings || {}) as Record<string, unknown>;
  const huHeaderSplit = splitHostFromHeaders(hu.headers);
  state.httpupgradeSettings = {
    path: str(hu.path, "/"),
    host: huHeaderSplit.host || str(hu.host),
    extraHeaders: huHeaderSplit.extraHeaders,
    acceptProxyProtocol: Boolean(hu.acceptProxyProtocol),
  };

  const kcp = (ss.kcpSettings || {}) as Record<string, unknown>;
  const kcpHdr = (kcp.header || {}) as Record<string, unknown>;
  state.mkcpSettings = {
    mtu: num(kcp.mtu, 1350),
    tti: num(kcp.tti, 50),
    uplinkCapacity: num(kcp.uplinkCapacity, 5),
    downlinkCapacity: num(kcp.downlinkCapacity, 20),
    congestion: Boolean(kcp.congestion),
    readBufferSize: kcp.readBufferSize != null ? Math.round(num(kcp.readBufferSize) / (1024 * 1024)) || 2 : 2,
    writeBufferSize: kcp.writeBufferSize != null ? Math.round(num(kcp.writeBufferSize) / (1024 * 1024)) || 2 : 2,
    cwnd: num(kcp.cwnd),
    maxSendingWindow: num(kcp.maxSendingWindow),
    header: {
      type: (str(kcpHdr.type, "none") as InboundFormState["mkcpSettings"]["header"]["type"]) || "none",
      domain: str(kcpHdr.domain),
    },
    seed: str(kcp.seed),
    udpMasks: parseTcpMasks(kcp.masks),
  };

  const quic = (ss.quicSettings || {}) as Record<string, unknown>;
  const quicHdr = (quic.header || {}) as Record<string, unknown>;
  state.quicSettings = {
    security: (str(quic.security, "none") as InboundFormState["quicSettings"]["security"]) || "none",
    key: str(quic.key),
    headerType: (str(quicHdr.type, "none") as InboundFormState["quicSettings"]["headerType"]) || "none",
  };

  const rawNet = str(ss.network, "tcp").toLowerCase();
  if (rawNet === "quic") {
    const key = state.quicSettings.key.trim();
    const path = key ? (key.startsWith("/") ? key : `/${key}`) : "/";
    state.network = "xhttp";
    state.xhttpSettings = {
      ...state.xhttpSettings,
      path: path || state.xhttpSettings.path,
      mode: "stream-one",
    };
    if (state.security === "none") state.security = "tls";
    if (!state.tlsSettings.alpn.includes("h3")) {
      state.tlsSettings = {
        ...state.tlsSettings,
        alpn: ["h3", ...state.tlsSettings.alpn.filter((a) => a !== "h3")],
      };
    }
  }

  const httpT = (ss.httpSettings || {}) as Record<string, unknown>;
  state.httpTransportSettings = {
    path: str(httpT.path, "/"),
    host: Array.isArray(httpT.host) ? (httpT.host as string[]) : httpT.host ? [str(httpT.host)] : [],
  };

  if (state.protocol === "hysteria") {
    const hs = (ss.hysteriaSettings || {}) as Record<string, unknown>;
    const masq = (hs.masquerade || {}) as Record<string, unknown>;
    state.hysteria2.masquerade = {
      enabled: Object.keys(masq).length > 0,
      type: str(masq.type),
      url: str(masq.url),
      dir: str(masq.dir),
      rewriteHost: Boolean(masq.rewriteHost),
      insecure: Boolean(masq.insecure),
      content: str(masq.content),
      statusCode: num(masq.statusCode),
    };
  }

  state.sockoptSettings = parseSockopt((ss.sockopt || {}) as Record<string, unknown>);
  state.tcpMasks = parseTcpMasks(ss.noises);

  const tls = (ss.tlsSettings || ss.tls || {}) as Record<string, unknown>;
  const cipherSuites = str(tls.cipherSuites);
  state.tlsSettings = {
    serverName: str(tls.serverName),
    rejectUnknownSni: Boolean(tls.rejectUnknownSni),
    allowInsecure: Boolean(tls.allowInsecure),
    alpn: Array.isArray(tls.alpn) ? (tls.alpn as string[]) : [],
    minVersion: (str(tls.minVersion, "1.2") as InboundFormState["tlsSettings"]["minVersion"]) || "1.2",
    maxVersion: (str(tls.maxVersion, "1.3") as InboundFormState["tlsSettings"]["maxVersion"]) || "1.3",
    cipherSuites,
    cipherPreset: detectCipherPreset(cipherSuites),
    certificates: parseTlsCertificates(tls.certificates),
    disableSystemRoot: Boolean(tls.disableSystemRoot),
    enableSessionResumption: Boolean(tls.enableSessionResumption),
    fingerprint: str(tls.fingerprint),
    pinnedPeerCertificateChainSha256: Array.isArray(tls.pinnedPeerCertificateChainSha256)
      ? (tls.pinnedPeerCertificateChainSha256 as string[])
      : [],
    curvePreferences: Array.isArray(tls.curvePreferences) ? (tls.curvePreferences as string[]) : [],
    masterKeyLog: str(tls.masterKeyLog),
    verifyPeerCertByName: Array.isArray(tls.verifyPeerCertInSubjectAltName)
      ? (tls.verifyPeerCertInSubjectAltName as string[])
      : Array.isArray(tls.verifyPeerCertInNames)
        ? (tls.verifyPeerCertInNames as string[])
        : [],
    echEnabled: Boolean(
      parseEchField(tls.echServerKeys).length || parseEchField(tls.echConfigList).length,
    ),
    echServerKeys: parseEchField(tls.echServerKeys),
    echConfigList: parseEchField(tls.echConfigList),
  };

  const rs = (ss.realitySettings || {}) as Record<string, unknown>;
  const rsSet = (rs.settings || {}) as Record<string, unknown>;
  const up = (rs.limitFallbackUpload || {}) as Record<string, unknown>;
  const down = (rs.limitFallbackDownload || {}) as Record<string, unknown>;
  state.realitySettings = {
    show: Boolean(rs.show),
    target: str(rs.dest || rs.target),
    xver: num(rs.xver) as 0 | 1 | 2,
    serverNames: Array.isArray(rs.serverNames) ? (rs.serverNames as string[]) : [],
    privateKey: str(rs.privateKey),
    publicKey: str(rsSet.publicKey || rs.publicKey),
    fingerprint: str(rsSet.fingerprint || rs.fingerprint, "chrome"),
    spiderX: str(rsSet.spiderX || rs.spiderX || rs.SpiderX),
    minClientVer: str(rs.minClientVer),
    maxClientVer: str(rs.maxClientVer),
    maxTimeDiff: num(rs.maxTimeDiff),
    shortIds: Array.isArray(rs.shortIds) ? (rs.shortIds as string[]) : [],
    mldsa65Seed: str(rs.mldsa65Seed || rsSet.mldsa65Seed),
    mldsa65Verify: str(rs.mldsa65Verify || rsSet.mldsa65Verify || rs.mldsa65Seed || rsSet.mldsa65Seed),
    limitFallbackUpload: {
      afterBytes: num(up.afterBytes),
      bytesPerSec: num(up.bytesPerSec),
      burstBytesPerSec: num(up.burstBytesPerSec),
    },
    limitFallbackDownload: {
      afterBytes: num(down.afterBytes),
      bytesPerSec: num(down.bytesPerSec),
      burstBytesPerSec: num(down.burstBytesPerSec),
    },
  };
}

function parseProtocolSettings(state: InboundFormState, settings: Record<string, unknown>, proto: string) {
  switch (proto) {
    case "vless": {
      const seeds = settings.testSeed as number[] | undefined;
      state.vless = {
        decryption: str(settings.decryption, "none"),
        encryption: str(settings.encryption, "none"),
        keyGenType: settings.encryption && settings.encryption !== "none" ? "x25519" : "none",
        visionTestSeed1: Array.isArray(seeds) ? str(seeds[0], "900") : "900",
        visionTestSeed2: Array.isArray(seeds) ? str(seeds[1], "500") : "500",
        visionTestSeed3: Array.isArray(seeds) ? str(seeds[2], "900") : "900",
        visionTestSeed4: Array.isArray(seeds) ? str(seeds[3], "256") : "256",
        flow: "",
        fallbacks: parseFallbacks(settings.fallbacks),
      };
      break;
    }
    case "vmess": {
      const clients = Array.isArray(settings.clients) ? settings.clients : [];
      state.vmess.clients = clients.length
        ? clients.map((c) => {
            const u = (c || {}) as Record<string, unknown>;
            return {
              id: str(u.id),
              alterId: num(u.alterId),
              security: (str(u.security, "auto") as "auto" | "aes-128-gcm" | "chacha20-poly1305" | "none" | "zero") || "auto",
              level: num(u.level),
              email: str(u.email),
            };
          })
        : [{ id: "", alterId: 0, security: "auto", level: 0, email: "" }];
      break;
    }
    case "trojan": {
      const clients = Array.isArray(settings.clients) ? settings.clients : [];
      state.trojan.clients = clients.length
        ? clients.map((c) => {
            const u = (c || {}) as Record<string, unknown>;
            return { password: str(u.password), level: num(u.level), email: str(u.email) };
          })
        : [{ password: "", level: 0, email: "" }];
      state.trojan.fallbacks = parseFallbacks(settings.fallbacks) as TrojanFallback[];
      break;
    }
    case "shadowsocks":
      state.shadowsocks = {
        method: str(settings.method, "2022-blake3-aes-256-gcm") as SSMethod,
        password: str(settings.password),
        network: (str(settings.network, "tcp,udp") as InboundFormState["shadowsocks"]["network"]) || "tcp,udp",
        ivCheck: settings.ivCheck !== false,
      };
      break;
    case "http": {
      const accounts = Array.isArray(settings.accounts) ? settings.accounts : [];
      state.http = {
        timeout: num(settings.timeout, 300),
        allowTransparent: Boolean(settings.allowTransparent),
        userLevel: num(settings.userLevel),
        accounts: accounts.map((a) => {
          const ac = (a || {}) as Record<string, unknown>;
          return { user: str(ac.user), pass: str(ac.pass) };
        }),
      };
      break;
    }
    case "socks":
    case "mixed": {
      const accounts = Array.isArray(settings.accounts) ? settings.accounts : [];
      state.socks = {
        auth: (str(settings.auth, "noauth") as "noauth" | "password") || "noauth",
        accounts: accounts.map((a) => {
          const ac = (a || {}) as Record<string, unknown>;
          return { user: str(ac.user), pass: str(ac.pass) };
        }),
        udp: settings.udp !== false,
        ip: str(settings.ip, "127.0.0.1"),
        userLevel: num(settings.userLevel),
      };
      break;
    }
    case "wireguard":
    case "amneziawg": {
      const peers = Array.isArray(settings.peers) ? settings.peers : [];
      state.wireguard = {
        secretKey: str(settings.secretKey),
        mtu: num(settings.mtu, 1420),
        address: Array.isArray(settings.address) ? (settings.address as string[]) : [],
        dns: Array.isArray(settings.dns) ? (settings.dns as string[]) : [],
        noKernelTun: Boolean(settings.noKernelTun),
        domainStrategy: str(settings.domainStrategy),
        peers: peers.length
          ? peers.map((p) => {
              const peer = (p || {}) as Record<string, unknown>;
              return {
                publicKey: str(peer.publicKey),
                allowedIPs: Array.isArray(peer.allowedIPs) ? (peer.allowedIPs as string[]) : ["0.0.0.0/0"],
              };
            })
          : [{ publicKey: "", allowedIPs: ["0.0.0.0/0"] }],
      };
      if (proto === "amneziawg") {
        const extra = { ...settings };
        delete extra.secretKey;
        delete extra.peers;
        delete extra.mtu;
        delete extra.address;
        delete extra.dns;
        delete extra.noKernelTun;
        delete extra.domainStrategy;
        delete extra[SHAHKAR_INBOUND_KIND];
        state.amneziaExtraJson = JSON.stringify(extra, null, 2);
      }
      break;
    }
    case "hysteria": {
      const clients = Array.isArray(settings.clients) ? settings.clients : [];
      state.hysteria2 = {
        version: 2,
        users: clients.length
          ? clients.map((c) => {
              const u = (c || {}) as Record<string, unknown>;
              return { auth: str(u.auth || u.password), level: num(u.level), email: str(u.email) };
            })
          : [{ auth: "", level: 0, email: "" }],
        masquerade: state.hysteria2.masquerade,
      };
      break;
    }
    case "tun":
      state.tun = {
        name: str(settings.name, "xray0"),
        mtu: num(settings.mtu, 1500),
        gateway: Array.isArray(settings.gateway) ? (settings.gateway as string[]) : ["10.0.0.1/16"],
        dns: Array.isArray(settings.dns) ? (settings.dns as string[]) : ["1.1.1.1"],
        userLevel: num(settings.userLevel),
        autoSystemRoutingTable: Array.isArray(settings.autoSystemRoutingTable)
          ? (settings.autoSystemRoutingTable as string[])
          : ["0.0.0.0/0", "::/0"],
        autoOutboundsInterface: str(settings.autoOutboundsInterface, "auto"),
      };
      break;
    case "dokodemo-door": {
      const rewriteAddress = str(settings.rewriteAddress);
      if (rewriteAddress) {
        state.dokodemo = {
          address: "",
          port: 0,
          network: "tcp,udp",
          timeout: num(settings.timeout, 300),
          followRedirect: Boolean(settings.followRedirect),
          userLevel: num(settings.userLevel),
          tunnelRewriteEnabled: true,
          rewriteAddress,
          rewritePort: num(settings.rewritePort),
          allowedNetwork: (str(settings.allowedNetwork, "tcp,udp") as InboundFormState["dokodemo"]["allowedNetwork"]) || "tcp,udp",
          portMapJson: settings.portMap ? JSON.stringify(settings.portMap, null, 2) : "",
        };
      } else {
        state.dokodemo = {
          address: str(settings.address, "8.8.8.8"),
          port: num(settings.port, 53),
          network: (str(settings.network, "tcp,udp") as InboundFormState["dokodemo"]["network"]) || "tcp,udp",
          timeout: num(settings.timeout, 300),
          followRedirect: Boolean(settings.followRedirect),
          userLevel: num(settings.userLevel),
          tunnelRewriteEnabled: false,
          rewriteAddress: "",
          rewritePort: 0,
          allowedNetwork: "tcp,udp",
          portMapJson: "",
        };
      }
      break;
    }
    default:
      state.customSettings = { ...settings };
      break;
  }
}

function parseSniffing(state: InboundFormState, sniff: Record<string, unknown> | undefined) {
  if (!sniff) {
    state.sniffing.enabled = false;
    return;
  }
  state.sniffing = {
    enabled: sniff.enabled !== false,
    destOverride: Array.isArray(sniff.destOverride)
      ? (sniff.destOverride as string[])
          .map((item) => String(item).trim().toLowerCase())
          .filter((item): item is SniffDestOverride =>
            item === "http" || item === "tls" || item === "quic" || item === "fakedns",
          )
      : ["http", "tls", "quic"],
    metadataOnly: Boolean(sniff.metadataOnly),
    routeOnly: Boolean(sniff.routeOnly),
    excludedDomains: Array.isArray(sniff.domainsExcluded) ? (sniff.domainsExcluded as string[]) : [],
    excludedIps: Array.isArray(sniff.ipsExcluded) ? (sniff.ipsExcluded as string[]) : [],
  };
}

/** Map xray inbound JSON → wizard form state (for edit). */
export function parseInboundToFormState(
  inbound: Record<string, unknown>,
  protocols: ProtocolDefinition[] = [],
): InboundFormState {
  const state = defaultInboundFormState();
  const settings = (inbound.settings || {}) as Record<string, unknown>;
  const ss = (inbound.streamSettings || {}) as Record<string, unknown>;

  state.basics = {
    remark: str(inbound.tag),
    listen: typeof inbound.listen === "string" ? inbound.listen : "0.0.0.0",
    port: str(inbound.port),
  };

  let proto = str(inbound.protocol, "vless");
  if (
    proto === "wireguard" &&
    (settings[SHAHKAR_INBOUND_KIND] === "amneziawg" || /amnezia|awg/i.test(str(inbound.tag)))
  ) {
    proto = "amneziawg";
  }
  state.protocol = proto;

  if (isKnownProtocol(protocols, proto) || findProtocolDef(protocols, proto)) {
    parseProtocolSettings(state, settings, proto);
  } else {
    state.customSettings = { ...settings };
  }

  const def = findProtocolDef(protocols, proto);
  if (def?.hasStream || proto === "dokodemo-door" || proto === "hysteria") {
    parseStream(state, ss);
  }
  if (proto === "hysteria") {
    state.security = "tls";
  }
  if (proto === "shadowsocks" && state.security === "reality") {
    state.security = "none";
  }

  if (def?.hasSniffing) {
    parseSniffing(state, inbound.sniffing as Record<string, unknown> | undefined);
  }

  return state;
}
