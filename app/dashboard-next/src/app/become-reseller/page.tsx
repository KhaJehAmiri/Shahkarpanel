"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { StorefrontFormShell } from "@/components/storefront/StorefrontShell";
import { buildLandingHref, resolveStorefrontQuery } from "@/lib/storefront-context";
import {
  applyReseller,
  fetchStorefront,
  type StorefrontPayload,
} from "@/lib/storefront-api";
import "../public-pages.css";

export default function BecomeResellerPage() {
  const [data, setData] = useState<StorefrontPayload | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [contact, setContact] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState<{ status: string; message: string; dashboard?: string } | null>(
    null,
  );
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
      const res = await applyReseller({
        username: username.trim(),
        password,
        display_name: displayName.trim() || undefined,
        contact: contact.trim() || undefined,
        message: message.trim() || undefined,
        tenant: q.tenant,
        ref: q.ref,
      });
      setDone({
        status: res.status,
        message: res.message,
        dashboard: res.dashboard_url,
      });
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : "Error");
    } finally {
      setBusy(false);
    }
  };

  if (data && !data.reseller_apply_enabled) {
    return (
      <StorefrontFormShell
        data={data}
        title={fa ? "جذب نماینده غیرفعال است" : "Reseller signup disabled"}
        lang={lang}
        backHref={buildLandingHref(q)}
      >
        <Link href={buildLandingHref(q)} className="sk-lp-btn">
          {fa ? "بازگشت" : "Back"}
        </Link>
      </StorefrontFormShell>
    );
  }

  if (done) {
    return (
      <StorefrontFormShell
        data={data}
        title={
          done.status === "created"
            ? fa
              ? "حساب نماینده ساخته شد"
              : "Reseller account created"
            : fa
              ? "درخواست ثبت شد"
              : "Application submitted"
        }
        subtitle={done.message}
        lang={lang}
        backHref={buildLandingHref(q)}
      >
        {done.status === "created" ? (
          <Link href={done.dashboard || "/dashboard/"} className="sk-lp-btn">
            {fa ? "ورود به داشبورد" : "Open dashboard"}
          </Link>
        ) : (
          <Link href={buildLandingHref(q)} className="sk-lp-btn">
            {fa ? "بازگشت به لندینگ" : "Back to landing"}
          </Link>
        )}
      </StorefrontFormShell>
    );
  }

  return (
    <StorefrontFormShell
      data={data}
      title={fa ? "درخواست نمایندگی" : "Become a reseller"}
      subtitle={
        q.ref
          ? fa
            ? "با کد دعوت، حساب زیرنماینده بلافاصله ساخته می‌شود."
            : "With an invite code, a sub-reseller account is created immediately."
          : fa
            ? "درخواست شما پس از تأیید اپراتور فعال می‌شود."
            : "Your application will be reviewed by an operator."
      }
      lang={lang}
      backHref={buildLandingHref(q)}
    >
      <form className="sk-store-form" onSubmit={onSubmit}>
        {err ? <div className="sk-store-err">{err}</div> : null}
        <label>
          <span>{fa ? "نام نمایشی" : "Display name"}</span>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={128} />
        </label>
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
          <span>{fa ? "تماس" : "Contact"}</span>
          <input
            value={contact}
            onChange={(e) => setContact(e.target.value)}
            maxLength={256}
            placeholder={fa ? "تلگرام / موبایل" : "Telegram / phone"}
            dir="ltr"
          />
        </label>
        <label>
          <span>{fa ? "پیام" : "Message"}</span>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            maxLength={1000}
            rows={3}
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "…" : fa ? "ارسال درخواست" : "Submit"}
        </button>
        <p className="sk-store-form-foot">
          {fa ? "نماینده هستید؟" : "Already a reseller?"}{" "}
          <Link href="/dashboard/">{fa ? "ورود به داشبورد" : "Dashboard login"}</Link>
        </p>
      </form>
    </StorefrontFormShell>
  );
}
