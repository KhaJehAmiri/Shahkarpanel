import { NXPANEL_INBOUND_KIND } from "./xrayHelpers";

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

export { NXPANEL_INBOUND_KIND as NXPANEL_WG_KIND };
