import type { StorefrontPlan } from "./storefront-api";

export type PlanFeature = { label: string; ok: boolean };

export function planVolumeLabel(plan: StorefrontPlan, lang: "fa" | "en"): string {
  if (plan.data_limit == null || plan.data_limit === 0) {
    return lang === "fa" ? "حجم نامحدود" : "Unlimited data";
  }
  const gb = plan.data_limit / (1024 ** 3);
  if (gb >= 1) {
    const n = gb % 1 === 0 ? String(gb) : gb.toFixed(1);
    return lang === "fa" ? `${n} گیگابایت` : `${n} GB`;
  }
  const mb = Math.round(plan.data_limit / (1024 ** 2));
  return lang === "fa" ? `${mb} مگابایت` : `${mb} MB`;
}

export function planDurationLabel(plan: StorefrontPlan, lang: "fa" | "en"): string {
  if (!plan.duration_days) return lang === "fa" ? "بدون انقضا" : "No expiry";
  return lang === "fa" ? `${plan.duration_days} روز` : `${plan.duration_days} days`;
}

export function planDeviceLabel(plan: StorefrontPlan, lang: "fa" | "en"): string {
  if (plan.device_limit == null || plan.device_limit <= 0) {
    return lang === "fa" ? "چند دستگاه" : "Multi-device";
  }
  return lang === "fa" ? `${plan.device_limit} دستگاه` : `${plan.device_limit} devices`;
}

export function planFeatures(plan: StorefrontPlan, lang: "fa" | "en"): PlanFeature[] {
  return [
    { label: planVolumeLabel(plan, lang), ok: true },
    { label: planDurationLabel(plan, lang), ok: true },
    { label: planDeviceLabel(plan, lang), ok: true },
    {
      label: lang === "fa" ? "فعال‌سازی آنی" : "Instant activation",
      ok: true,
    },
    {
      label: lang === "fa" ? "پشتیبانی از همه پلتفرم‌ها" : "All major platforms",
      ok: true,
    },
  ];
}

export function pickFeaturedPlanIndex(plans: StorefrontPlan[]): number {
  if (plans.length < 2) return 0;
  // Prefer a mid paid tier as "most popular"
  const paid = plans
    .map((p, i) => ({ p, i }))
    .filter(({ p }) => (p.price || 0) > 0);
  if (paid.length === 0) return Math.min(1, plans.length - 1);
  return paid[Math.floor((paid.length - 1) / 2)].i;
}

export function formatPlanPrice(
  plan: StorefrontPlan,
  currency: string,
  lang: "fa" | "en",
): { main: string; suffix: string } {
  if (plan.price === 0) {
    return { main: lang === "fa" ? "رایگان" : "Free", suffix: "" };
  }
  return {
    main: plan.price.toLocaleString(lang === "fa" ? "fa-IR" : "en-US"),
    suffix: currency || "",
  };
}
