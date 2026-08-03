const API_BASE = process.env.NEXT_PUBLIC_BASE_API || "/api/";

export type StorefrontPlan = {
  id: number;
  name: string;
  price: number;
  data_limit?: number | null;
  duration_days?: number | null;
  device_limit?: number | null;
};

export type StorefrontBranding = {
  panel_title?: string | null;
  logo_url?: string | null;
  favicon_url?: string | null;
  primary_color?: string | null;
  support_url?: string | null;
  domain?: string | null;
  panel_url?: string | null;
};

export type StorefrontPayload = {
  storefront_enabled: boolean;
  signup_enabled: boolean;
  reseller_apply_enabled: boolean;
  tenant_slug?: string | null;
  ref?: string | null;
  headline: string;
  tagline: string;
  currency_label: string;
  branding: StorefrontBranding;
  plans: StorefrontPlan[];
};

function apiUrl(path: string): string {
  const base = API_BASE.endsWith("/") ? API_BASE.slice(0, -1) : API_BASE;
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${base}${p}`;
}

async function errorFromResponse(res: Response): Promise<Error> {
  let msg = `HTTP ${res.status}`;
  try {
    const j = await res.json();
    if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* ignore */
  }
  return new Error(msg);
}

export type StorefrontQuery = {
  tenant?: string | null;
  ref?: string | null;
  domain?: string | null;
};

export function storefrontQueryFromSearch(search: string): StorefrontQuery {
  const sp = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  return {
    tenant: sp.get("tenant"),
    ref: sp.get("ref"),
    domain: sp.get("domain"),
  };
}

export async function fetchStorefront(q: StorefrontQuery = {}): Promise<StorefrontPayload> {
  const sp = new URLSearchParams();
  if (q.tenant) sp.set("tenant", q.tenant);
  if (q.ref) sp.set("ref", q.ref);
  if (q.domain) sp.set("domain", q.domain);
  const qs = sp.toString();
  const res = await fetch(apiUrl(`/public/storefront${qs ? `?${qs}` : ""}`), {
    credentials: "same-origin",
  });
  if (!res.ok) throw await errorFromResponse(res);
  return res.json();
}

export async function registerCustomer(
  body: {
    username: string;
    password: string;
    contact?: string;
    tenant?: string | null;
    ref?: string | null;
  },
): Promise<{ access_token: string; username: string; portal_url: string }> {
  const res = await fetch(apiUrl("/public/register"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await errorFromResponse(res);
  return res.json();
}

export async function applyReseller(body: {
  username: string;
  password: string;
  display_name?: string;
  contact?: string;
  message?: string;
  tenant?: string | null;
  ref?: string | null;
}): Promise<{
  status: string;
  username?: string;
  id?: number;
  role?: string;
  dashboard_url?: string;
  message: string;
}> {
  const res = await fetch(apiUrl("/public/reseller-apply"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await errorFromResponse(res);
  return res.json();
}

export function formatPlanMeta(
  plan: StorefrontPlan,
  currency: string,
  lang: "fa" | "en" = "fa",
): string {
  const bits: string[] = [];
  if (plan.data_limit == null || plan.data_limit === 0) {
    bits.push(lang === "fa" ? "حجم نامحدود" : "Unlimited data");
  } else {
    const gb = plan.data_limit / (1024 ** 3);
    const vol =
      gb >= 1
        ? `${gb % 1 === 0 ? gb : gb.toFixed(1)} GB`
        : `${Math.round(plan.data_limit / (1024 ** 2))} MB`;
    bits.push(lang === "fa" ? `${vol} حجم` : vol);
  }
  if (plan.duration_days) {
    bits.push(lang === "fa" ? `${plan.duration_days} روز` : `${plan.duration_days} days`);
  } else {
    bits.push(lang === "fa" ? "بدون انقضا" : "No expiry");
  }
  if (currency) {
    /* price shown separately in UI */
  }
  return bits.join(" · ");
}
