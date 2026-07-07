// ── Protocol registry ──────────────────
export interface ProtocolDefinition {
  id: string;
  label: string;
  icon: string;
  category: "user" | "advanced";
  hasUsers: boolean;
  hasStream: boolean;
  hasSecurity: boolean;
  hasSniffing: boolean;
  description: string;
}

// ── Basics ─────────────────────────────
export interface InboundBasics {
  remark: string;
  listen: string;
  port: string;
}

// ── Shared user base ───────────────────
export interface BaseUser {
  email: string;
  level: number;
}

// ── VLESS ──────────────────────────────
export type VlessFlow = "" | "xtls-rprx-vision" | "xtls-rprx-vision-udp443";

export interface VLESSUser extends BaseUser {
  id: string;
  flow: VlessFlow;
}

export interface VLESSFallback {
  name: string;
  alpn: string;
  path: string;
  dest: string | number;
  xver: 0 | 1 | 2;
}

export interface VLESSSettings {
  decryption: string;
  encryption: string;
  keyGenType: string;
  visionTestSeed1: string;
  visionTestSeed2: string;
  visionTestSeed3: string;
  visionTestSeed4: string;
  flow: VlessFlow;
  fallbacks: VLESSFallback[];
}

// ── VMess ──────────────────────────────
export interface VMessUser extends BaseUser {
  id: string;
  alterId: number;
  security: "auto" | "aes-128-gcm" | "chacha20-poly1305" | "none" | "zero";
}

export interface VMessSettings {
  clients: VMessUser[];
}

// ── Trojan ─────────────────────────────
export interface TrojanUser extends BaseUser {
  password: string;
}

export interface TrojanFallback {
  name: string;
  alpn: string;
  path: string;
  dest: string | number;
  xver: 0 | 1 | 2;
}

export interface TrojanSettings {
  clients: TrojanUser[];
  fallbacks: TrojanFallback[];
}

// ── Shadowsocks ────────────────────────
export type SSMethod =
  | "aes-256-gcm"
  | "aes-128-gcm"
  | "chacha20-ietf-poly1305"
  | "2022-blake3-aes-128-gcm"
  | "2022-blake3-aes-256-gcm"
  | "2022-blake3-chacha20-poly1305";

export interface ShadowsocksSettings {
  method: SSMethod;
  password: string;
  network: "tcp" | "udp" | "tcp,udp";
  ivCheck: boolean;
}

// ── HTTP ───────────────────────────────
export interface HTTPAccount {
  user: string;
  pass: string;
}

export interface HTTPSettings {
  timeout: number;
  accounts: HTTPAccount[];
  allowTransparent: boolean;
  userLevel: number;
}

// ── Socks / Mixed ──────────────────────
export interface SocksAccount {
  user: string;
  pass: string;
}

export interface SocksSettings {
  auth: "noauth" | "password";
  accounts: SocksAccount[];
  udp: boolean;
  ip: string;
  userLevel: number;
}

// ── WireGuard ──────────────────────────
export interface WireGuardPeer {
  publicKey: string;
  allowedIPs: string[];
}

export interface WireGuardSettings {
  secretKey: string;
  peers: WireGuardPeer[];
  mtu: number;
  address: string[];
  dns: string[];
  noKernelTun: boolean;
  domainStrategy: string;
}

// ── Hysteria2 ──────────────────────────
export interface Hysteria2User extends BaseUser {
  auth: string;
}

export interface HysteriaMasqueradeSettings {
  enabled: boolean;
  type: string;
  url: string;
  dir: string;
  rewriteHost: boolean;
  insecure: boolean;
  content: string;
  statusCode: number;
}

export interface Hysteria2Settings {
  version: 2;
  users: Hysteria2User[];
  masquerade: HysteriaMasqueradeSettings;
}

// ── TUN ────────────────────────────────
export interface TUNSettings {
  name: string;
  mtu: number;
  gateway: string[];
  dns: string[];
  userLevel: number;
  autoSystemRoutingTable: string[];
  autoOutboundsInterface: string;
}

// ── Dokodemo ───────────────────────────
export interface DokodemoSettings {
  address: string;
  port: number;
  network: "tcp" | "udp" | "tcp,udp";
  timeout: number;
  followRedirect: boolean;
  userLevel: number;
  tunnelRewriteEnabled: boolean;
  rewriteAddress: string;
  rewritePort: number;
  allowedNetwork: "tcp" | "udp" | "tcp,udp";
  portMapJson: string;
}

// ── Transports ─────────────────────────
export type NetworkType = "raw" | "ws" | "grpc" | "xhttp" | "httpupgrade" | "mkcp" | "quic" | "http";

export interface RawHttpRequest {
  version: string;
  method: string;
  path: string;
  headers: Record<string, string[]>;
}

export interface RawHttpResponse {
  version: string;
  status: string;
  reason: string;
  headers: Record<string, string[]>;
}

export interface RawSettings {
  acceptProxyProtocol: boolean;
  httpObfuscation: boolean;
  request: RawHttpRequest;
  response: RawHttpResponse;
}

export type RealClientIpMode = "direct" | "cloudflare" | "proxy";

export interface SockoptSettings {
  enabled: boolean;
  realClientIp: RealClientIpMode;
  mark: string;
  tcpKeepAliveInterval: string;
  tcpKeepAliveIdle: string;
  tcpMaxSeg: string;
  tcpUserTimeout: string;
  tcpWindowClamp: string;
  acceptProxyProtocol: boolean;
  tcpFastOpen: boolean;
  penetrate: boolean;
  v6Only: boolean;
  tcpCongestion: string;
  tproxy: string;
  trustedXForwardedFor: string;
  domainStrategy: string;
  customOptions: Array<{ key: string; value: string }>;
}

export interface TcpMaskFragmentSettings {
  packets: string;
  lengths: string[];
  delays: string[];
  maxSplit: string;
}

export interface TcpMaskEntry {
  type: "fragment" | "noise";
  settings: TcpMaskFragmentSettings;
}

export interface WSSettings {
  path: string;
  host: string;
  extraHeaders: Record<string, string[]>;
  heartbeatPeriod: number;
  maxEarlyData: number;
  earlyDataHeaderName: string;
  browserForwarding: boolean;
  acceptProxyProtocol: boolean;
}

export interface GRPCSettings {
  serviceName: string;
  authority: string;
  userAgent: string;
  multiMode: boolean;
  idleTimeout: number;
  healthCheckTimeout: number;
  permitWithoutStream: boolean;
  initialWindowsSize: number;
}

export interface XHTTPXmuxSettings {
  maxConcurrency: number;
  maxConnections: number;
  cMaxReuseTimes: number;
  hMaxRequestTimes: number;
  hMaxReusableSecs: number;
  hKeepAlivePeriod: number;
}

export type XHTTPMode = "auto" | "stream-one" | "stream-up" | "packet-up";

export type XHTTPFieldSettings = {
  path: string;
  host: string;
  mode: XHTTPMode;
  noSSEHeader: boolean;
  noGRPCHeader: boolean;
  scMaxEachPostBytes: number;
  scMaxBufferedPosts: number;
  scMaxConcurrentPosts: number;
  scMinPostsIntervalMs: number;
  scStreamUpServerSecs: number;
  serverMaxHeaderBytes: number;
  keepAlivePeriod: number;
  xPaddingBytes: string;
  uplinkHTTPMethod: string;
};

export interface XHTTPSettings extends XHTTPFieldSettings {
  xmux: XHTTPXmuxSettings;
  downloadSettings?: Partial<XHTTPFieldSettings>;
}

export interface HTTPUpgradeSettings {
  path: string;
  host: string;
  extraHeaders: Record<string, string[]>;
  acceptProxyProtocol: boolean;
}

export type MKCPHeaderType = "none" | "srtp" | "utp" | "wechat-video" | "dtls" | "wireguard";

export interface MKCPSettings {
  mtu: number;
  tti: number;
  uplinkCapacity: number;
  downlinkCapacity: number;
  congestion: boolean;
  readBufferSize: number;
  writeBufferSize: number;
  cwnd: number;
  maxSendingWindow: number;
  header: {
    type: MKCPHeaderType;
    domain: string;
  };
  seed: string;
  udpMasks: TcpMaskEntry[];
}

export type QuicSecurity = "none" | "aes-128-gcm" | "chacha20-poly1305";

export interface QuicSettings {
  security: QuicSecurity;
  key: string;
  headerType: MKCPHeaderType;
}

export interface HttpTransportSettings {
  path: string;
  host: string[];
}

// ── TLS ────────────────────────────────
export interface TLSCertificate {
  usage: "encipherment" | "verify" | "issue";
  certificateFile: string;
  keyFile: string;
  certificate: string[];
  key: string[];
  ocspStapling: number;
  buildChain: boolean;
  oneTimeLoading: boolean;
  pemMode: boolean;
}

export interface TLSSettings {
  serverName: string;
  rejectUnknownSni: boolean;
  allowInsecure: boolean;
  alpn: string[];
  minVersion: "1.0" | "1.1" | "1.2" | "1.3";
  maxVersion: "1.0" | "1.1" | "1.2" | "1.3";
  cipherSuites: string;
  cipherPreset: string;
  certificates: TLSCertificate[];
  disableSystemRoot: boolean;
  enableSessionResumption: boolean;
  fingerprint: string;
  pinnedPeerCertificateChainSha256: string[];
  curvePreferences: string[];
  masterKeyLog: string;
  verifyPeerCertByName: string[];
  echEnabled: boolean;
  echServerKeys: string[];
  echConfigList: string[];
}

export const ALPN_OPTIONS = ["h3", "h2", "http/1.1", "http/1.0"] as const;

export const TLS_CIPHER_PRESETS: { id: string; label: string; value: string }[] = [
  { id: "auto", label: "Auto (Xray default)", value: "" },
  { id: "tls13", label: "TLS 1.3 modern", value: "TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384" },
  { id: "ecdhe", label: "ECDHE-ECDSA-AES128-GCM", value: "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256" },
  { id: "chrome", label: "Chrome-like", value: "TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256" },
];

export const TLS_CURVE_OPTIONS = ["X25519", "P-256", "P-384", "P-521"] as const;

// ── Reality ────────────────────────────
export interface RealityLimitFallback {
  afterBytes: number;
  bytesPerSec: number;
  burstBytesPerSec: number;
}

export interface RealitySettings {
  show: boolean;
  target: string;
  xver: 0 | 1 | 2;
  serverNames: string[];
  privateKey: string;
  publicKey: string;
  fingerprint: string;
  spiderX: string;
  minClientVer: string;
  maxClientVer: string;
  maxTimeDiff: number;
  shortIds: string[];
  mldsa65Seed: string;
  mldsa65Verify: string;
  limitFallbackUpload: RealityLimitFallback;
  limitFallbackDownload: RealityLimitFallback;
}

// ── Sniffing ───────────────────────────
export type SniffDestOverride = "http" | "tls" | "quic" | "fakedns";

export interface SniffingSettings {
  enabled: boolean;
  destOverride: SniffDestOverride[];
  metadataOnly: boolean;
  routeOnly: boolean;
  excludedDomains: string[];
  excludedIps: string[];
}

// ── Root form state ────────────────────
export type SecurityType = "none" | "tls" | "reality";

export type StepId = "basics" | "protocol" | "settings" | "stream" | "security" | "sniffing" | "review";

export interface InboundFormState {
  basics: InboundBasics;
  protocol: string;
  vless: VLESSSettings;
  vmess: VMessSettings;
  trojan: TrojanSettings;
  shadowsocks: ShadowsocksSettings;
  http: HTTPSettings;
  socks: SocksSettings;
  wireguard: WireGuardSettings;
  hysteria2: Hysteria2Settings;
  tun: TUNSettings;
  dokodemo: DokodemoSettings;
  amneziaExtraJson: string;
  customSettings: Record<string, unknown>;
  network: NetworkType;
  rawSettings: RawSettings;
  sockoptSettings: SockoptSettings;
  tcpMasks: TcpMaskEntry[];
  wsSettings: WSSettings;
  grpcSettings: GRPCSettings;
  xhttpSettings: XHTTPSettings;
  httpupgradeSettings: HTTPUpgradeSettings;
  mkcpSettings: MKCPSettings;
  quicSettings: QuicSettings;
  httpTransportSettings: HttpTransportSettings;
  security: SecurityType;
  tlsSettings: TLSSettings;
  realitySettings: RealitySettings;
  sniffing: SniffingSettings;
}

export const REALITY_COMPATIBLE_NETWORKS: NetworkType[] = ["raw", "xhttp", "grpc"];

export const TLS_FINGERPRINTS = [
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
] as const;

export const KEY_GEN_TYPES = [
  { value: "none", label: "None" },
  { value: "x25519", label: "X25519 (native)" },
  { value: "x25519-xorpub", label: "X25519 (xorpub)" },
  { value: "x25519-random", label: "X25519 (random)" },
  { value: "mlkem768", label: "ML-KEM-768 (native)" },
  { value: "mlkem768-xorpub", label: "ML-KEM-768 (xorpub)" },
  { value: "mlkem768-random", label: "ML-KEM-768 (random)" },
] as const;

export const VLESS_FLOWS = ["", "xtls-rprx-vision", "xtls-rprx-vision-udp443"] as const;

export const SS_METHODS: SSMethod[] = [
  "aes-256-gcm",
  "aes-128-gcm",
  "chacha20-ietf-poly1305",
  "2022-blake3-aes-128-gcm",
  "2022-blake3-aes-256-gcm",
  "2022-blake3-chacha20-poly1305",
];

export const VMESS_SECURITY_OPTIONS = [
  "auto",
  "aes-128-gcm",
  "chacha20-poly1305",
  "none",
  "zero",
] as const;

export const MKCP_HEADER_TYPES = [
  "none",
  "srtp",
  "utp",
  "wechat-video",
  "dtls",
  "wireguard",
] as const;

export const SOCKOPT_REAL_IP = [
  { value: "direct", label: "Off / direct" },
  { value: "cloudflare", label: "Cloudflare CDN" },
  { value: "proxy", label: "L4 relay / Spectrum (PROXY)" },
] as const;

export const TPROXY_MODES = ["", "off", "redirect", "tproxy"] as const;
export const TCP_CONGESTION = ["", "bbr", "cubic", "reno"] as const;
export const DOMAIN_STRATEGIES = ["AsIs", "IPIfNonMatch", "IPOnDemand"] as const;
export const TCP_MASK_TYPES = ["fragment", "noise"] as const;

export function defaultXhttpXmuxSettings(): XHTTPXmuxSettings {
  return {
    maxConcurrency: 0,
    maxConnections: 0,
    cMaxReuseTimes: 0,
    hMaxRequestTimes: 0,
    hMaxReusableSecs: 0,
    hKeepAlivePeriod: 0,
  };
}

export function defaultHysteriaMasquerade(): HysteriaMasqueradeSettings {
  return {
    enabled: false,
    type: "",
    url: "",
    dir: "",
    rewriteHost: false,
    insecure: false,
    content: "",
    statusCode: 0,
  };
}

export function defaultQuicSettings(): QuicSettings {
  return { security: "none", key: "", headerType: "none" };
}

export function defaultHttpTransportSettings(): HttpTransportSettings {
  return { path: "/", host: [] };
}

export function defaultSockoptSettings(): SockoptSettings {
  return {
    enabled: false,
    realClientIp: "direct",
    mark: "0",
    tcpKeepAliveInterval: "0",
    tcpKeepAliveIdle: "0",
    tcpMaxSeg: "0",
    tcpUserTimeout: "0",
    tcpWindowClamp: "0",
    acceptProxyProtocol: false,
    tcpFastOpen: false,
    penetrate: false,
    v6Only: false,
    tcpCongestion: "",
    tproxy: "",
    trustedXForwardedFor: "",
    domainStrategy: "",
    customOptions: [],
  };
}

export function emptyTcpMask(): TcpMaskEntry {
  return {
    type: "fragment",
    settings: {
      packets: "1-3",
      lengths: ["100-200"],
      delays: [],
      maxSplit: "",
    },
  };
}

export const SNIFF_OPTIONS: SniffDestOverride[] = [
  "http",
  "tls",
  "quic",
  "fakedns",
];

export const STEP_LABELS: Record<StepId, string> = {
  basics: "Basics",
  protocol: "Protocol",
  settings: "Settings",
  stream: "Stream",
  security: "Security",
  sniffing: "Sniffing",
  review: "Review",
};

export function defaultInboundFormState(): InboundFormState {
  return {
    basics: { remark: "", listen: "0.0.0.0", port: "443" },
    protocol: "vless",
    vless: {
      decryption: "none",
      encryption: "none",
      keyGenType: "none",
      visionTestSeed1: "900",
      visionTestSeed2: "500",
      visionTestSeed3: "900",
      visionTestSeed4: "256",
      flow: "",
      fallbacks: [],
    },
    vmess: {
      clients: [{ id: "", alterId: 0, security: "auto", level: 0, email: "" }],
    },
    trojan: {
      clients: [{ password: "", level: 0, email: "" }],
      fallbacks: [],
    },
    shadowsocks: {
      method: "2022-blake3-aes-256-gcm",
      password: "",
      network: "tcp,udp",
      ivCheck: false,
    },
    http: { timeout: 300, accounts: [], allowTransparent: false, userLevel: 0 },
    socks: { auth: "noauth", accounts: [], udp: true, ip: "127.0.0.1", userLevel: 0 },
    wireguard: {
      secretKey: "",
      peers: [{ publicKey: "", allowedIPs: ["0.0.0.0/0"] }],
      mtu: 1420,
      address: [],
      dns: [],
      noKernelTun: false,
      domainStrategy: "",
    },
    hysteria2: {
      version: 2,
      users: [{ auth: "", level: 0, email: "" }],
      masquerade: defaultHysteriaMasquerade(),
    },
    tun: {
      name: "xray0",
      mtu: 1500,
      gateway: ["10.0.0.1/16"],
      dns: ["1.1.1.1"],
      userLevel: 0,
      autoSystemRoutingTable: ["0.0.0.0/0", "::/0"],
      autoOutboundsInterface: "auto",
    },
    dokodemo: {
      address: "8.8.8.8",
      port: 53,
      network: "tcp,udp",
      timeout: 300,
      followRedirect: false,
      userLevel: 0,
      tunnelRewriteEnabled: false,
      rewriteAddress: "",
      rewritePort: 0,
      allowedNetwork: "tcp,udp",
      portMapJson: "",
    },
    amneziaExtraJson: "{}",
    customSettings: {},
    network: "raw",
    rawSettings: {
      acceptProxyProtocol: false,
      httpObfuscation: false,
      request: { version: "1.1", method: "GET", path: "/", headers: {} },
      response: { version: "1.1", status: "200", reason: "OK", headers: {} },
    },
    sockoptSettings: defaultSockoptSettings(),
    tcpMasks: [],
    wsSettings: {
      path: "/",
      host: "",
      extraHeaders: {},
      heartbeatPeriod: 0,
      maxEarlyData: 0,
      earlyDataHeaderName: "",
      browserForwarding: false,
      acceptProxyProtocol: false,
    },
    grpcSettings: {
      serviceName: "",
      authority: "",
      userAgent: "",
      multiMode: false,
      idleTimeout: 0,
      healthCheckTimeout: 0,
      permitWithoutStream: false,
      initialWindowsSize: 0,
    },
    xhttpSettings: {
      path: "/",
      host: "",
      mode: "auto",
      noSSEHeader: false,
      noGRPCHeader: false,
      scMaxEachPostBytes: 0,
      scMaxBufferedPosts: 0,
      scMaxConcurrentPosts: 0,
      scMinPostsIntervalMs: 0,
      scStreamUpServerSecs: 0,
      serverMaxHeaderBytes: 0,
      keepAlivePeriod: 0,
      xPaddingBytes: "",
      uplinkHTTPMethod: "",
      xmux: defaultXhttpXmuxSettings(),
    },
    httpupgradeSettings: { path: "/", host: "", extraHeaders: {}, acceptProxyProtocol: false },
    mkcpSettings: {
      mtu: 1350,
      tti: 50,
      uplinkCapacity: 5,
      downlinkCapacity: 20,
      congestion: false,
      readBufferSize: 2,
      writeBufferSize: 2,
      cwnd: 0,
      maxSendingWindow: 0,
      header: { type: "none", domain: "" },
      seed: "",
      udpMasks: [],
    },
    quicSettings: defaultQuicSettings(),
    httpTransportSettings: defaultHttpTransportSettings(),
    security: "none",
    tlsSettings: {
      serverName: "",
      rejectUnknownSni: false,
      allowInsecure: false,
      alpn: ["h2", "http/1.1"],
      minVersion: "1.2",
      maxVersion: "1.3",
      cipherSuites: "",
      cipherPreset: "auto",
      certificates: [],
      disableSystemRoot: false,
      enableSessionResumption: false,
      fingerprint: "chrome",
      pinnedPeerCertificateChainSha256: [],
      curvePreferences: [],
      masterKeyLog: "",
      verifyPeerCertByName: [],
      echEnabled: false,
      echServerKeys: [],
      echConfigList: [],
    },
    realitySettings: {
      show: false,
      target: "www.cloudflare.com:443",
      xver: 0,
      serverNames: ["www.cloudflare.com"],
      privateKey: "",
      publicKey: "",
      fingerprint: "chrome",
      spiderX: "",
      minClientVer: "",
      maxClientVer: "",
      maxTimeDiff: 0,
      shortIds: [],
      mldsa65Seed: "",
      mldsa65Verify: "",
      limitFallbackUpload: { afterBytes: 0, bytesPerSec: 0, burstBytesPerSec: 0 },
      limitFallbackDownload: { afterBytes: 0, bytesPerSec: 0, burstBytesPerSec: 0 },
    },
    sniffing: {
      enabled: false,
      destOverride: ["http", "tls", "quic"],
      metadataOnly: false,
      routeOnly: false,
      excludedDomains: [],
      excludedIps: [],
    },
  };
}

export function getActiveSteps(def: ProtocolDefinition | undefined): StepId[] {
  const steps: StepId[] = ["basics", "protocol", "settings"];
  if (def?.hasStream) steps.push("stream");
  if (def?.hasSecurity) steps.push("security");
  if (def?.hasSniffing) steps.push("sniffing");
  steps.push("review");
  return steps;
}

export function findProtocolDef(
  protocols: ProtocolDefinition[],
  id: string,
): ProtocolDefinition | undefined {
  return protocols.find((p) => p.id === id);
}

export function isKnownProtocol(protocols: ProtocolDefinition[], id: string): boolean {
  return protocols.some((p) => p.id === id);
}
