/** Prefer server-computed public URL (never 127.0.0.1). */

/** Detect API path prefix from a subscription URL pathname (sub/info/json/…). */
export function pathPrefixFromSubUrl(subUrl: string): string {
  if (!subUrl) return "sub";
  try {
    const base = typeof window !== "undefined" ? window.location.origin : "https://localhost";
    const u = new URL(stripSubUrlFragment(subUrl), base);
    const parts = u.pathname.replace(/^\/+|\/+$/g, "").split("/");
    return parts[0] || "sub";
  } catch {
    return "sub";
  }
}

/** Active path from ?path= / ?prefix= on the subscribe page, else fallback. */
export function pathPrefixFromLocation(fallback = "sub"): string {
  if (typeof window === "undefined") return fallback;
  try {
    const q = new URLSearchParams(window.location.search);
    for (const key of ["path", "prefix", "path_prefix"]) {
      const raw = (q.get(key) || "").trim().replace(/^\/+|\/+$/g, "");
      if (raw) return raw;
    }
  } catch {
    /* ignore */
  }
  return fallback;
}

export function resolvePublicSubUrl(
  info: { public_subscription_url?: string; subscription_url?: string } | null,
  token: string,
  pathPrefix?: string,
): string {
  const pub = info?.public_subscription_url?.trim();
  if (pub) return pub.endsWith("/") ? pub : `${pub}/`;

  const raw = info?.subscription_url?.trim();
  if (raw?.startsWith("http")) return raw.endsWith("/") ? raw : `${raw}/`;

  if (typeof window !== "undefined" && raw?.startsWith("/")) {
    const origin = window.location.origin;
    if (!origin.includes("127.0.0.1") && !origin.includes("localhost")) {
      return `${origin}${raw}${raw.endsWith("/") ? "" : "/"}`;
    }
  }

  if (typeof window !== "undefined" && token) {
    const origin = window.location.origin;
    if (!origin.includes("127.0.0.1") && !origin.includes("localhost")) {
      const prefix = (pathPrefix || pathPrefixFromLocation("sub")).replace(/^\/+|\/+$/g, "") || "sub";
      return `${origin}/${prefix}/${token}/`;
    }
  }

  return pub || raw || "";
}

/** Strip #fragment (used before /sing-box, /wireguard, etc.). */
export function stripSubUrlFragment(url: string): string {
  return (url || "").replace(/#.*$/, "");
}

/**
 * URL for VPN app import — includes #title with quota/expiry for v2rayNG (ignores HTTP headers).
 * Use only for deep links / "open in app", not for plain copy+paste import.
 */
export function resolveClientImportUrl(
  info: {
    client_subscription_url?: string;
    public_subscription_url?: string;
    subscription_url?: string;
    subscription_profile_title?: string;
  } | null,
  token: string,
  pathPrefix?: string,
): string {
  const client = info?.client_subscription_url?.trim();
  if (client) return client;

  const base = stripSubUrlFragment(resolvePublicSubUrl(info, token, pathPrefix)).replace(/\/?$/, "/");
  const title = info?.subscription_profile_title?.trim();
  if (base && title) {
    return `${base}#${encodeURIComponent(title)}`;
  }
  return base || resolvePublicSubUrl(info, token, pathPrefix);
}

export function resolveSingboxSubUrl(subUrl: string): string {
  if (!subUrl) return "";
  return stripSubUrlFragment(subUrl).replace(/\/?$/, "/sing-box");
}

export function resolveWgUrl(
  subUrl: string,
  variant: "plain" | "awg" | "xray_native" = "plain",
  nodeId?: number,
): string {
  if (!subUrl) return "";
  const base = stripSubUrlFragment(subUrl).replace(/\/?$/, "/wireguard");
  const path = nodeId != null ? `${base}/${nodeId}` : base;
  if (variant === "plain") return path;
  return `${path}?variant=${variant}`;
}

export function resolveHysteria2Url(subUrl: string, nodeId?: number): string {
  if (!subUrl) return "";
  const base = stripSubUrlFragment(subUrl).replace(/\/?$/, "/hysteria2");
  const path = nodeId != null ? `${base}/${nodeId}` : base;
  return path;
}

export function resolveTuicUrl(subUrl: string, nodeId?: number): string {
  if (!subUrl) return "";
  const base = stripSubUrlFragment(subUrl).replace(/\/?$/, "/tuic");
  const path = nodeId != null ? `${base}/${nodeId}` : base;
  return path;
}

export function resolveAnytlsUrl(subUrl: string, nodeId?: number): string {
  if (!subUrl) return "";
  const base = stripSubUrlFragment(subUrl).replace(/\/?$/, "/anytls");
  const path = nodeId != null ? `${base}/${nodeId}` : base;
  return path;
}

/** Browser-friendly setup page (/subscribe/?token=…&path=…) from any /{prefix}/{token}/ URL. */
export function resolveSubscribeBrowserUrl(subUrl: string): string {
  if (!subUrl) return "";
  const bare = stripSubUrlFragment(subUrl);
  try {
    const base = typeof window !== "undefined" ? window.location.origin : "https://localhost";
    const u = new URL(bare, base);
    const parts = u.pathname.replace(/^\/+|\/+$/g, "").split("/");
    const prefix = parts[0] || "";
    const token = parts[1] || "";
    if (token) {
      const qs = new URLSearchParams({ token });
      if (prefix && prefix !== "sub") qs.set("path", prefix);
      return `${u.origin}/subscribe/?${qs.toString()}`;
    }
    return subUrl;
  } catch {
    return subUrl;
  }
}
