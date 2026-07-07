/** Proxy / share links must never be prefixed with the panel origin. */
const OPAQUE_URI_SCHEME = /^[a-z][a-z0-9+.-]*:\/\//i;

export function isShareOrAbsoluteUrl(url: string): boolean {
  const trimmed = url.trim();
  return /^https?:\/\//i.test(trimmed)
    || trimmed.startsWith("//")
    || OPAQUE_URI_SCHEME.test(trimmed);
}

/** Convert a panel-relative path into a fully qualified HTTP(S) URL. */
export function absoluteUrl(url: string | undefined | null): string {
  if (!url) return "";
  const trimmed = url.trim();
  if (!trimmed) return "";
  if (isShareOrAbsoluteUrl(trimmed)) return trimmed;
  if (typeof window === "undefined") return trimmed;
  const path = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  return `${window.location.origin}${path}`;
}
