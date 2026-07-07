/** Visual tokens for inbound protocol picker cards. */
export const INBOUND_PROTO_VIS: Record<string, { icon: string; hue: string; label: string }> = {
  vless: { icon: "⚡", hue: "#818cf8", label: "VLESS" },
  vmess: { icon: "🔷", hue: "#60a5fa", label: "VMess" },
  trojan: { icon: "🛡", hue: "#34d399", label: "Trojan" },
  shadowsocks: { icon: "🔐", hue: "#a78bfa", label: "Shadowsocks" },
  wireguard: { icon: "🔒", hue: "#22d3ee", label: "WireGuard" },
  amneziawg: { icon: "🌀", hue: "#2dd4bf", label: "AmneziaWG" },
  hysteria: { icon: "💨", hue: "#f472b6", label: "Hysteria2" },
  http: { icon: "🌐", hue: "#94a3b8", label: "HTTP" },
  socks: { icon: "🧦", hue: "#94a3b8", label: "SOCKS" },
  mixed: { icon: "🔀", hue: "#94a3b8", label: "Mixed" },
  tun: { icon: "📡", hue: "#64748b", label: "TUN" },
  "dokodemo-door": { icon: "🚪", hue: "#fbbf24", label: "Dokodemo" },
};
