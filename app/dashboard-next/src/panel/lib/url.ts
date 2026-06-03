// Convert a possibly-relative subscription/config URL into a fully qualified one
// using the panel's own origin. The backend returns "/sub/<token>" when no
// public prefix is configured, which can't be opened on its own.
export function absoluteUrl(url: string | undefined | null): string {
  if (!url) return "";
  const trimmed = url.trim();
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (typeof window === "undefined") return trimmed;
  if (trimmed.startsWith("//")) return `${window.location.protocol}${trimmed}`;
  const path = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  return `${window.location.origin}${path}`;
}
