/** Sentinel tags for native (non-Xray) products in the Hosts UI. */
export const NATIVE_HOST_LABELS: Record<string, string> = {
  "__native:wireguard": "WireGuard",
  "__native:amneziawg": "AmneziaWG",
  "__native:hysteria2": "Hysteria2",
  "__native:tuic": "TUIC",
};

export function hostTagLabel(tag: string): string {
  return NATIVE_HOST_LABELS[tag] || tag;
}

export function isNativeHostTag(tag: string): boolean {
  return tag.startsWith("__native:");
}

export interface HostRecord {
  remark: string;
  address: string;
  port: number | null;
  sni: string;
  host: string;
  path: string;
  security: string;
  alpn: string;
  fingerprint: string;
  allowinsecure: boolean;
  is_disabled: boolean;
  mux_enable: boolean;
  fragment_setting: string;
  noise_setting: string;
  random_user_agent: boolean;
  use_sni_as_host: boolean;
  sort_order?: number;
  override_sni_from_address?: boolean;
  keep_sni_blank?: boolean;
  pinned_peer_cert_sha256?: string;
  verify_peer_cert_by_name?: string;
  ech_config_list?: string;
  mux_params?: string;
  sockopt_params?: string;
  final_mask?: string;
  vless_route?: string;
  exclude_from_sub_types?: string;
  mihomo_ip_version?: string;
  external_proxy?: string;
  node_ids?: string;
  /** Region preset code (nl, de, …) — used for {REGION_FLAG} without a node. */
  region?: string;
}

export type HostRowRef = { tag: string; index: number; host: HostRecord };

export function emptyHost(tag?: string): HostRecord {
  return {
    remark: "{REGION_FLAG} {REGION_NAME} · {PROTOCOL}",
    address: tag && isNativeHostTag(tag) ? "{NODE_IP}" : "{SERVER_IP}",
    port: null,
    sni: "",
    host: "",
    path: "",
    security: "inbound_default",
    alpn: "",
    fingerprint: "",
    allowinsecure: false,
    is_disabled: false,
    mux_enable: false,
    fragment_setting: "",
    noise_setting: "",
    random_user_agent: false,
    use_sni_as_host: false,
    sort_order: 0,
    override_sni_from_address: false,
    keep_sni_blank: false,
    pinned_peer_cert_sha256: "",
    verify_peer_cert_by_name: "",
    ech_config_list: "",
    mux_params: "",
    sockopt_params: "",
    final_mask: "",
    vless_route: "",
    exclude_from_sub_types: "",
    mihomo_ip_version: "",
    external_proxy: "",
    node_ids: "",
    region: "",
  };
}

export function cloneHosts(src: Record<string, HostRecord[]>): Record<string, HostRecord[]> {
  return JSON.parse(JSON.stringify(src)) as Record<string, HostRecord[]>;
}

/**
 * Stamp `sort_order` onto every host to match its current array position.
 * The backend (`crud.get_hosts`) returns hosts sorted by `(sort_order, id)`,
 * so persisting the visible order requires writing sort_order explicitly —
 * otherwise reorder/move actions revert on reload.
 */
export function reindexSortOrder(
  hosts: Record<string, HostRecord[]>,
): Record<string, HostRecord[]> {
  const out: Record<string, HostRecord[]> = {};
  for (const tag of Object.keys(hosts)) {
    out[tag] = (hosts[tag] || []).map((host, index) => ({
      ...host,
      sort_order: index,
    }));
  }
  return out;
}

export function flattenHosts(hosts: Record<string, HostRecord[]>): HostRowRef[] {
  const rows: HostRowRef[] = [];
  for (const tag of Object.keys(hosts).sort()) {
    (hosts[tag] || []).forEach((host, index) => rows.push({ tag, index, host }));
  }
  return rows;
}

export function formatEndpoint(h: HostRecord): string {
  const addr = (h.address || "").trim() || "—";
  const port = h.port != null && h.port > 0 ? `:${h.port}` : "";
  return `${addr}${port}`;
}
