/** Flatten per-protocol inbound tags into one sorted list. */
export function flattenUserInbounds(inbounds?: Record<string, string[]>): string[] {
  if (!inbounds) return [];
  const tags = new Set<string>();
  Object.values(inbounds).forEach((arr) => arr?.forEach((t) => tags.add(t)));
  return Array.from(tags).sort();
}

/** Infer migration source slug from username prefix. */
export function inferSourceSlug(username: string, knownSlugs: string[]): string | null {
  const sorted = [...knownSlugs].sort((a, b) => b.length - a.length);
  for (const slug of sorted) {
    if (username.startsWith(`${slug}_`)) return slug;
  }
  const i = username.indexOf("_");
  return i > 0 ? username.slice(0, i) : null;
}
