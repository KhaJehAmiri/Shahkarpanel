// Formatting helpers for the public subscription page.

export function bytes(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined) return "∞";
  if (n === 0) return "0 B";
  const k = 1024;
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const i = Math.min(Math.floor(Math.log(Math.abs(n)) / Math.log(k)), units.length - 1);
  return `${(n / Math.pow(k, i)).toFixed(digits)} ${units[i]}`;
}

export function formatDate(value: number | string | null | undefined): string {
  if (!value) return "—";
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (isNaN(d.getTime())) return "—";
  try {
    return new Intl.DateTimeFormat("fa-IR", {
      year: "numeric",
      month: "short",
      day: "numeric",
    }).format(d);
  } catch {
    return d.toISOString().slice(0, 10);
  }
}

// Human-readable remaining/elapsed days relative to now. Returns null when
// there is no expiry set.
export function relativeDays(expire: number | null | undefined): { text: string; days: number } | null {
  if (!expire) return null;
  const diff = expire - Date.now() / 1000;
  const days = Math.ceil(diff / 86400);
  if (days < 0) return { text: `${Math.abs(days)} روز گذشته`, days };
  if (days === 0) return { text: "امروز", days };
  return { text: `${days} روز مانده`, days };
}
