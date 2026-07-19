export interface SubscriptionEndpointRow {
  id: number;
  slug: string;
  host: string | null;
  path_prefix: string;
  public_base_url: string;
  listen_port: number | null;
  inbound_tag: string | null;
  export_mode: string;
  format_default: string | null;
  legacy_panel_id: string | null;
  enabled: boolean;
}

export type EndpointChannel = "main" | "json" | "clash";

export interface SubscriptionEndpointGroup {
  key: string;
  label: string;
  kind: "panel" | "default" | "inbound" | "other";
  main: SubscriptionEndpointRow | null;
  json: SubscriptionEndpointRow | null;
  clash: SubscriptionEndpointRow | null;
  /** lone rows that are not part of a main/json/clash trio */
  extras: SubscriptionEndpointRow[];
}

export function endpointChannel(ep: SubscriptionEndpointRow): EndpointChannel | "other" {
  if (ep.format_default === "v2ray-json" || ep.slug.endsWith("-json")) return "json";
  if (ep.format_default === "clash-meta" || ep.slug.endsWith("-clash")) return "clash";
  if (ep.slug.endsWith("-json") || ep.slug.endsWith("-clash")) return "other";
  return "main";
}

/** Group p1 + p1-json + p1-clash (and similar) into one panel card. */
export function groupSubscriptionEndpoints(rows: SubscriptionEndpointRow[]): SubscriptionEndpointGroup[] {
  const byKey = new Map<string, SubscriptionEndpointGroup>();

  const ensure = (key: string, label: string, kind: SubscriptionEndpointGroup["kind"]) => {
    let g = byKey.get(key);
    if (!g) {
      g = { key, label, kind, main: null, json: null, clash: null, extras: [] };
      byKey.set(key, g);
    }
    return g;
  };

  for (const ep of rows) {
    if (ep.slug === "default") {
      const g = ensure("default", "default", "default");
      g.main = ep;
      continue;
    }
    if (ep.inbound_tag) {
      const g = ensure(`inbound:${ep.inbound_tag}`, ep.inbound_tag, "inbound");
      const ch = endpointChannel(ep);
      if (ch === "main") g.main = ep;
      else if (ch === "json") g.json = ep;
      else if (ch === "clash") g.clash = ep;
      else g.extras.push(ep);
      continue;
    }

    let base = ep.slug;
    if (base.endsWith("-json")) base = base.slice(0, -5);
    else if (base.endsWith("-clash")) base = base.slice(0, -6);

    const panelLike = /^(p\d+|panel[-_]?\w+)$/i.test(base) || !!ep.legacy_panel_id;
    const g = ensure(base, base, panelLike ? "panel" : "other");
    const ch = endpointChannel(ep);
    if (ch === "main" && (ep.slug === base || !ep.slug.includes("-"))) g.main = ep;
    else if (ch === "json") g.json = ep;
    else if (ch === "clash") g.clash = ep;
    else if (ch === "main") g.main = ep;
    else g.extras.push(ep);
  }

  const orderRank = (g: SubscriptionEndpointGroup) => {
    if (g.kind === "default") return 0;
    if (g.kind === "panel") {
      const m = g.key.match(/^p(\d+)$/i);
      return m ? 100 + Number(m[1]) : 200;
    }
    if (g.kind === "inbound") return 500;
    return 900;
  };

  return Array.from(byKey.values()).sort((a, b) => {
    const d = orderRank(a) - orderRank(b);
    return d !== 0 ? d : a.label.localeCompare(b.label);
  });
}

export function groupPrimary(g: SubscriptionEndpointGroup): SubscriptionEndpointRow | null {
  return g.main || g.json || g.clash || g.extras[0] || null;
}
