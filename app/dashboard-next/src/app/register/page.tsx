"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { StorefrontFormShell } from "@/components/storefront/StorefrontShell";
import { buildLandingHref, resolveStorefrontQuery } from "@/lib/storefront-context";
import {
  fetchStorefront,
  registerCustomer,
  type StorefrontPayload,
} from "@/lib/storefront-api";
import { setPortalToken } from "@/lib/portal-api";
import "../public-pages.css";

export default function RegisterPage() {
  const [data, setData] = useState<StorefrontPayload | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [lang, setLang] = useState<"fa" | "en">("fa");

  const q = useMemo(() => {
    if (typeof window === "undefined") return { tenant: null, ref: null };
    return resolveStorefrontQuery(window.location.pathname, window.location.search);
  }, []);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("nx_lang");
      if (stored === "en" || stored === "fa") setLang(stored);
    } catch {
      /* ignore */
    }
    fetchStorefront({ tenant: q.tenant, ref: q.ref })
      .then(setData)
      .catch(() => setData(null));
  }, [q.tenant, q.ref]);

  const fa = lang === "fa";

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const res = await registerCustomer({
        username: username.trim(),
        password,
        contact: contact.trim() || undefined,
        tenant: q.tenant,
        ref: q.ref,
      });
      setPortalToken(res.access_token);
      window.location.href = res.portal_url || "/portal/";
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : "Error");
    } finally {
      setBusy(false);
    }
  };

  if (data && !data.signup_enabled) {
    return (
      <StorefrontFormShell
        data={data}
        title={fa ? "ثبت‌نام غیرفعال است" : "Signup disabled"}
        subtitle={fa ? "از اپراتور خود لینک دعوت بگیرید." : "Ask your operator for an invite."}
        lang={lang}
        backHref={buildLandingHref(q)}
      >
        <Link href="/portal/" className="sk-lp-btn">
          {fa ? "ورود به پورتال" : "Open portal"}
        </Link>
      </StorefrontFormShell>
    );
  }

  return (
    <StorefrontFormShell
      data={data}
      title={fa ? "ثبت‌نام مشتری" : "Create account"}
      subtitle={fa ? "بعد از ثبت‌نام وارد پورتال می‌شوید و پلن می‌خرید." : "After signup you’ll enter the portal to buy a plan."}
      lang={lang}
      backHref={buildLandingHref(q)}
    >
      <form className="sk-store-form" onSubmit={onSubmit}>
        {err ? <div className="sk-store-err">{err}</div> : null}
        <label>
          <span>{fa ? "نام کاربری" : "Username"}</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            minLength={3}
            maxLength={32}
            autoComplete="username"
            dir="ltr"
          />
        </label>
        <label>
          <span>{fa ? "رمز عبور" : "Password"}</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={4}
            autoComplete="new-password"
          />
        </label>
        <label>
          <span>{fa ? "تماس (اختیاری)" : "Contact (optional)"}</span>
          <input
            value={contact}
            onChange={(e) => setContact(e.target.value)}
            maxLength={256}
            placeholder={fa ? "تلگرام یا موبایل" : "Telegram or phone"}
            dir="ltr"
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "…" : fa ? "ثبت‌نام" : "Sign up"}
        </button>
        <p className="sk-store-form-foot">
          {fa ? "حساب دارید؟" : "Already have an account?"}{" "}
          <Link href="/portal/">{fa ? "ورود" : "Log in"}</Link>
        </p>
      </form>
    </StorefrontFormShell>
  );
}
