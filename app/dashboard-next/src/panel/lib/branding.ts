import { Branding } from "../api/types";

export function applyBranding(branding: Branding | null | undefined) {
  if (!branding?.primary_color) return;
  document.documentElement.style.setProperty("--nx-accent", branding.primary_color);
}

export function brandingTitle(branding: Branding | null | undefined, fallback: string) {
  return branding?.panel_title?.trim() || fallback;
}
