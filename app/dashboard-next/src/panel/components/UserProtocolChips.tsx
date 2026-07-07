import { FC } from "react";

const PROTO_LABEL: Record<string, string> = {
  vless: "VLESS",
  vmess: "VMess",
  trojan: "Trojan",
  shadowsocks: "Shadowsocks",
  wireguard: "WireGuard",
  amneziawg: "AmneziaWG",
  hysteria2: "Hysteria2",
  tuic: "TUIC",
  anytls: "AnyTLS",
};

const PROTO_ABBR: Record<string, string> = {
  vless: "VL",
  vmess: "VM",
  trojan: "TR",
  shadowsocks: "SS",
  wireguard: "WG",
  amneziawg: "AWG",
  hysteria2: "H2",
  tuic: "TC",
  anytls: "AT",
};

const PROTO_HUE: Record<string, string> = {
  vless: "#2ee0c4",
  vmess: "#6366f1",
  trojan: "#f59e0b",
  shadowsocks: "#38bdf8",
  wireguard: "#a78bfa",
  amneziawg: "#22d3ee",
  hysteria2: "#f472b6",
  tuic: "#34d399",
  anytls: "#a78bfa",
};

export const UserProtocolChips: FC<{ protos: string[]; maxVisible?: number }> = ({
  protos,
  maxVisible = 4,
}) => {
  if (!protos.length) return <span className="nx-faint">—</span>;

  const visible = protos.slice(0, maxVisible);
  const rest = protos.length - visible.length;
  const title = protos.map((p) => PROTO_LABEL[p] || p).join(", ");

  return (
    <div className="nx-user-proto-chips" title={title}>
      {visible.map((p) => (
        <span
          key={p}
          className="nx-user-proto-chip"
          style={{ "--proto-hue": PROTO_HUE[p] || "var(--nx-accent)" } as React.CSSProperties}
        >
          {PROTO_ABBR[p] || p.slice(0, 2).toUpperCase()}
        </span>
      ))}
      {rest > 0 ? <span className="nx-user-proto-more">+{rest}</span> : null}
    </div>
  );
};
