import { Branding } from "../api/types";

/** Built-in mark — served via /sub-assets (always mounted) and /brand after restart. */
export const DEFAULT_LOGO_URL = "/sub-assets/brand/shahkar.png";
export const DEFAULT_FAVICON_URL = "/sub-assets/brand/favicon.ico";

export function brandLogoUrl(branding: Branding | null | undefined): string {
  return branding?.logo_url?.trim() || DEFAULT_LOGO_URL;
}

export function brandFaviconUrl(branding: Branding | null | undefined): string {
  return branding?.favicon_url?.trim() || DEFAULT_FAVICON_URL;
}

function ensureLink(rel: string): HTMLLinkElement {
  let el = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement("link");
    el.rel = rel;
    document.head.appendChild(el);
  }
  return el;
}

/** Dedicated home-screen icon — opaque PNG; never point apple-touch at .ico. */
export const DEFAULT_APPLE_TOUCH_URL = "/brand/apple-touch-icon.png?v=4";

export function appleTouchUrl(faviconHref: string): string {
  const href = (faviconHref || "").trim();
  // .ico / generic favicon paths are wrong for iOS Add to Home Screen.
  if (!href || /favicon\.ico(?:$|\?)/i.test(href) || href.toLowerCase().includes("favicon")) {
    return DEFAULT_APPLE_TOUCH_URL;
  }
  return href;
}

export function applyFavicon(href: string) {
  if (typeof document === "undefined" || !href) return;
  ensureLink("icon").href = href;
  ensureLink("shortcut icon").href = href;
  const apple = ensureLink("apple-touch-icon");
  apple.href = appleTouchUrl(href);
  apple.setAttribute("sizes", "180x180");
}

export function applyBranding(branding: Branding | null | undefined, fallbackTitle = "Shahkar") {
  if (typeof document === "undefined") return;
  if (branding?.primary_color) {
    document.documentElement.style.setProperty("--sk-accent", branding.primary_color);
  }
  applyFavicon(brandFaviconUrl(branding));
  // Browser tab title must follow reseller/admin panel_title (static HTML is "Shahkar").
  document.title = brandingTitle(branding, fallbackTitle);
}

export function brandingTitle(branding: Branding | null | undefined, fallback: string) {
  return branding?.panel_title?.trim() || fallback;
}
