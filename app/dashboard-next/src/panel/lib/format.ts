export function formatBytes(bytes: number | null | undefined, digits = 1): string {
  if (bytes === null || bytes === undefined) return "∞";
  if (bytes === 0) return "0 B";
  const k = 1024;
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const i = Math.min(Math.floor(Math.log(Math.abs(bytes)) / Math.log(k)), units.length - 1);
  return `${(bytes / Math.pow(k, i)).toFixed(digits)} ${units[i]}`;
}

/** Compact wallet amounts: 500000000 → "500M", 4500 → "4,500". */
export function formatCompactAmount(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1_000_000_000) return `${sign}${(abs / 1_000_000_000).toFixed(abs >= 10_000_000_000 ? 0 : 1)}B`;
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  if (abs >= 100_000) return `${sign}${(abs / 1_000).toFixed(0)}K`;
  return `${sign}${Math.round(abs).toLocaleString()}`;
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

/**
 * Localized "time until expiry" label, e.g. "۵ روز مانده" / "5d left".
 * `t` is the i18next translate function from the calling component.
 */
export function relativeExpiryLabel(
  expire: number | null | undefined,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  if (!expire) return "∞";
  const diffSec = expire - Date.now() / 1000;
  const abs = Math.abs(diffSec);
  let value: string;
  if (abs >= 86400) value = t("users.unitDays", { n: Math.ceil(abs / 86400) });
  else if (abs >= 3600) value = t("users.unitHours", { n: Math.ceil(abs / 3600) });
  else value = t("users.unitMinutes", { n: Math.max(1, Math.ceil(abs / 60)) });
  return diffSec >= 0 ? t("users.expiresIn", { value }) : t("users.expiredAgo", { value });
}

export function formatAgo(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (isNaN(d.getTime())) return "—";
  const sec = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
  if (sec < 45) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`;
  return `${Math.floor(sec / 86400)}d`;
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
    case "on_hold":
    case "connecting":
    case "syncing":
      return "info";
    case "expired":
    case "limited":
    case "drifted":
      return "warn";
    default:
      return "default";
  }
}
