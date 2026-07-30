import { PortalLang, pt } from "@/lib/portal-i18n";
import type { PortalProfile, PortalAccountSummary } from "./types";

export function statusTone(status: string): "ok" | "warn" | "danger" | "" {
  if (status === "active") return "ok";
  if (status === "on_hold" || status === "limited") return "warn";
  if (status === "expired" || status === "disabled") return "danger";
  return "";
}

export function pickDefaultUsername(me: PortalProfile, list: PortalAccountSummary[]): string {
  const login = list.find((a) => a.is_portal_login);
  if (login) return login.username;
  if (list.length) return list[0].username;
  return me.username;
}

export function usagePct(profile: PortalProfile | null | undefined): number {
  if (!profile?.data_limit || profile.data_limit <= 0) return 0;
  return Math.min(100, (profile.used_traffic / profile.data_limit) * 100);
}

export function remainingBytes(profile: PortalProfile | null | undefined): number | null {
  if (!profile?.data_limit || profile.data_limit <= 0) return null;
  return Math.max(0, profile.data_limit - profile.used_traffic);
}

export function daysLeft(expire: number | null | undefined): number | null {
  if (!expire) return null;
  const ms = expire * 1000 - Date.now();
  return Math.ceil(ms / 86400000);
}

export function formatPrice(amount: number, lang: PortalLang, currencyLabel: string): string {
  if (amount === 0) return pt(lang, "free");
  const label = currencyLabel || (lang === "fa" ? "تومان" : "");
  return `${amount.toLocaleString(lang === "fa" ? "fa-IR" : undefined)}${label ? ` ${label}` : ""}`;
}

export function orderStatusLabel(lang: PortalLang, status: string): string {
  const key = `order_${status}`;
  const translated = pt(lang, key);
  return translated === key ? status : translated;
}

export function needsAttention(profile: PortalProfile | null | undefined): "expired" | "low_data" | "expiring" | null {
  if (!profile) return null;
  if (profile.status === "expired" || profile.status === "disabled") return "expired";
  if (profile.status === "limited") return "low_data";
  const days = daysLeft(profile.expire);
  if (days != null && days <= 3 && days >= 0) return "expiring";
  const pct = usagePct(profile);
  if (profile.data_limit && pct >= 90) return "low_data";
  return null;
}

/** Remaining resource health for an account summary or profile. */
export type AccountHealth = "ok" | "warn" | "danger";

export function remainingDataPct(used: number, limit: number | null | undefined): number | null {
  if (!limit || limit <= 0) return null;
  return Math.max(0, Math.min(100, ((limit - used) / limit) * 100));
}

export function accountHealth(input: {
  status: string;
  used_traffic: number;
  data_limit: number | null;
  expire: number | null;
}): AccountHealth {
  if (input.status === "expired" || input.status === "disabled" || input.status === "limited") {
    return "danger";
  }
  const days = daysLeft(input.expire);
  if (days != null && days <= 0) return "danger";

  const dataRem = remainingDataPct(input.used_traffic, input.data_limit);
  const dataDanger = dataRem != null && dataRem <= 15;
  const dataWarn = dataRem != null && dataRem <= 30;
  const timeDanger = days != null && days <= 3;
  const timeWarn = days != null && days <= 7;

  if (dataDanger || timeDanger) return "danger";
  if (dataWarn || timeWarn) return "warn";
  return "ok";
}

export function healthRemainingLabel(
  lang: PortalLang,
  input: { used_traffic: number; data_limit: number | null; expire: number | null },
): string {
  const parts: string[] = [];
  const dataRem = remainingDataPct(input.used_traffic, input.data_limit);
  if (dataRem != null) {
    parts.push(`${Math.round(dataRem)}% ${pt(lang, "remaining")}`);
  }
  const days = daysLeft(input.expire);
  if (days != null) {
    parts.push(days > 0 ? `${days} ${pt(lang, "daysLeft")}` : pt(lang, "expired"));
  }
  return parts.join(" · ");
}
