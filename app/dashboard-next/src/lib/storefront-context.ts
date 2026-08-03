"use client";

import { useMemo } from "react";
import type { StorefrontQuery } from "./storefront-api";

/** Resolve tenant slug / invite ref from URL path and query string. */
export function resolveStorefrontQuery(
  pathname: string,
  search: string,
): StorefrontQuery & { pathTenant?: string } {
  const sp = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const parts = pathname.split("/").filter(Boolean);
  let pathTenant: string | undefined;
  if (parts[0] === "t" && parts[1]) {
    pathTenant = decodeURIComponent(parts[1]);
  }
  return {
    tenant: sp.get("tenant") || pathTenant || null,
    ref: sp.get("ref"),
    domain: sp.get("domain"),
    pathTenant,
  };
}

export function useStorefrontQuery(): StorefrontQuery & { pathTenant?: string; ready: boolean } {
  return useMemo(() => {
    if (typeof window === "undefined") {
      return { tenant: null, ref: null, domain: null, ready: false };
    }
    return {
      ...resolveStorefrontQuery(window.location.pathname, window.location.search),
      ready: true,
    };
  }, []);
}

export function buildRegisterHref(q: StorefrontQuery): string {
  const sp = new URLSearchParams();
  if (q.tenant) sp.set("tenant", q.tenant);
  if (q.ref) sp.set("ref", q.ref);
  const qs = sp.toString();
  return qs ? `/register/?${qs}` : "/register/";
}

export function buildBecomeHref(q: StorefrontQuery): string {
  const sp = new URLSearchParams();
  if (q.tenant) sp.set("tenant", q.tenant);
  if (q.ref) sp.set("ref", q.ref);
  const qs = sp.toString();
  return qs ? `/become-reseller/?${qs}` : "/become-reseller/";
}

export function buildLandingHref(q: StorefrontQuery): string {
  if (q.tenant) return `/t/${encodeURIComponent(q.tenant)}/`;
  if (q.ref) return `/?ref=${encodeURIComponent(q.ref)}`;
  return "/";
}
