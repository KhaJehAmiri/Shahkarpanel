/** Prefer server-computed public URL (never 127.0.0.1). */
export function resolvePublicSubUrl(
  info: { public_subscription_url?: string; subscription_url?: string } | null,
  token: string,
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
      return `${origin}/sub/${token}/`;
    }
  }

  return pub || raw || "";
}

export function resolveWgUrl(subUrl: string): string {
  if (!subUrl) return "";
  return subUrl.replace(/\/?$/, "/wireguard");
}
