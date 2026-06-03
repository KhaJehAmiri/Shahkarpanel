export function formatBytes(bytes: number | null | undefined, digits = 1): string {
  if (bytes === null || bytes === undefined) return "∞";
  if (bytes === 0) return "0 B";
  const k = 1024;
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const i = Math.min(Math.floor(Math.log(Math.abs(bytes)) / Math.log(k)), units.length - 1);
  return `${(bytes / Math.pow(k, i)).toFixed(digits)} ${units[i]}`;
}

export function formatSpeed(bytesPerSec: number): string {
  return `${formatBytes(bytesPerSec)}/s`;
}

export function formatDate(value: number | string | null | undefined, locale = "en"): string {
  if (!value) return "—";
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat(locale === "fa" ? "fa-IR" : locale, {
    year: "numeric", month: "short", day: "numeric",
  }).format(d);
}

export function relativeExpiry(expire: number | null | undefined): { text: string; days: number | null } {
  if (!expire) return { text: "∞", days: null };
  const now = Date.now() / 1000;
  const diff = expire - now;
  const days = Math.ceil(diff / 86400);
  return { text: `${days}d`, days };
}

export function usagePct(used: number, limit: number | null | undefined): number {
  if (!limit) return 0;
  return Math.min(100, (used / limit) * 100);
}

export function statusTone(status: string): "ok" | "danger" | "warn" | "info" | "default" {
  switch (status) {
    case "active":
    case "connected":
      return "ok";
    case "disabled":
    case "error":
      return "danger";
    case "expired":
    case "limited":
      return "warn";
    case "on_hold":
    case "connecting":
      return "info";
    default:
      return "default";
  }
}
