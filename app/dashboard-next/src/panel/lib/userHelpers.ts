import { InboundsByProtocol, NodeItem } from "../api/types";
import { NXPANEL_INBOUND_KIND } from "./xrayHelpers";

const USERNAME_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789";

/** Random 8-char username (same style as bulk create). */
export function generateRandomUsername(length = 8): string {
  return Array.from(
    { length },
    () => USERNAME_ALPHABET[Math.floor(Math.random() * USERNAME_ALPHABET.length)],
  ).join("");
}

type WgSettings = {
  address?: string | null;
  awg_address?: string | null;
  nexusPanelKind?: string;
};

/** UI protocol badges for a user row (wireguard proxy may represent AWG). */
export function userWgStackLabels(settings: WgSettings | undefined): string[] {
  const s = settings || {};
  const kind = s.nexusPanelKind;
  if (kind === "both") return ["wireguard", "amneziawg"];
  if (kind === "amneziawg") return ["amneziawg"];
  if (kind === "wireguard") return ["wireguard"];

  const awg = !!s.awg_address;
  const plain = !!s.address;
  if (awg && plain) return ["wireguard", "amneziawg"];
  if (awg) return ["amneziawg"];
  return ["wireguard"];
}

export function userDisplayProtocols(proxies: Record<string, unknown> | undefined | null): string[] {
  if (!proxies) return [];
  const out: string[] = [];
  for (const key of Object.keys(proxies)) {
    if (key === "wireguard") {
      out.push(...userWgStackLabels(proxies.wireguard as WgSettings));
    } else {
      out.push(key);
    }
  }
  return out;
}

export function wgKindForSubmit(wireguardOn: boolean, amneziaOn: boolean): string | undefined {
  if (wireguardOn && amneziaOn) return "both";
  if (amneziaOn) return "amneziawg";
  if (wireguardOn) return "wireguard";
  return undefined;
}

/** True when the panel can assign users on this protocol (Xray inbound or native node). */
export function protocolAssignable(
  proto: string,
  inbounds: InboundsByProtocol | undefined,
  nodes: NodeItem[] | undefined,
): boolean {
  const nodeList = nodes || [];
  switch (proto) {
    case "wireguard":
      return (inbounds?.wireguard?.length || 0) > 0
        || nodeList.some((n) => n.core_kind === "wireguard" && n.wireguard?.plain_enabled !== false);
    case "amneziawg":
      return (inbounds?.amneziawg?.length || 0) > 0
        || nodeList.some((n) => n.core_kind === "wireguard" && !!n.wireguard?.awg_enabled);
    case "hysteria2":
      return nodeList.some((n) => !!n.singbox?.hysteria2_enabled);
    case "tuic":
      return nodeList.some((n) => !!n.singbox?.tuic_enabled);
    case "anytls":
      return nodeList.some((n) => !!n.singbox?.anytls_enabled);
    default:
      return (inbounds?.[proto]?.length || 0) > 0;
  }
}

export { NXPANEL_INBOUND_KIND as NXPANEL_WG_KIND };

export type SsInboundMeta = { tag: string; ss_method?: string | null };

export function isSs2022Method(method: string): boolean {
  return method.startsWith("2022-blake3");
}

/** Legacy vs SS-2022 family must match between user proxy and inbound. */
export function inboundMatchesSsMethod(
  inboundMethod: string | null | undefined,
  userMethod: string,
): boolean {
  return isSs2022Method(inboundMethod || "") === isSs2022Method(userMethod);
}

export function ssMethodFromInbound(ib: { ss_method?: string | null }): string {
  const m = (ib.ss_method || "").trim();
  return m || "chacha20-ietf-poly1305";
}

/** Cipher comes from the first selected SS inbound (inbound is source of truth). */
export function deriveSsMethodFromInbounds(
  tags: string[],
  inboundList: SsInboundMeta[],
): string | null {
  const first = inboundList.find((ib) => tags.includes(ib.tag));
  return first ? ssMethodFromInbound(first) : null;
}

export function defaultSsInboundTags(inboundList: SsInboundMeta[]): string[] {
  const first = inboundList[0];
  return first ? [first.tag] : [];
}

export function defaultProtoInboundTags(
  proto: string,
  inbounds: InboundsByProtocol | undefined,
): string[] {
  if (proto === "amneziawg") return inbounds?.amneziawg?.map((i) => i.tag) || [];
  if (proto === "shadowsocks") return defaultSsInboundTags(inbounds?.shadowsocks || []);
  return inbounds?.[proto]?.map((i) => i.tag) || [];
}

export function toggleSsInboundTag(
  tags: string[],
  tag: string,
  inboundList: SsInboundMeta[],
): string[] {
  if (tags.includes(tag)) return tags.filter((t) => t !== tag);
  const ib = inboundList.find((i) => i.tag === tag);
  if (!ib) return tags;
  if (!tags.length) return [tag];
  const ref = ssMethodFromInbound(inboundList.find((i) => i.tag === tags[0]) || ib);
  if (!inboundMatchesSsMethod(ib.ss_method, ref)) return tags;
  return [...tags, tag];
}
