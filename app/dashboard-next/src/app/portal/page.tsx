"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { UsageBar } from "@/components/subscribe/UsageBar";
import { bytes, formatDate } from "@/lib/format";
import {
  clearPortalToken,
  getPortalToken,
  portalGet,
  portalLogin,
  portalPost,
} from "@/lib/portal-api";
import { detectPortalLang, PortalLang, PORTAL_LANGS, pt } from "@/lib/portal-i18n";
import { resolveSubscribeBrowserUrl } from "@/lib/subscribe-url";

interface PortalProfile {
  username: string;
  status: string;
  used_traffic: number;
  overage_traffic?: number;
  data_limit: number | null;
  expire: number | null;
  public_subscription_url?: string;
  subscription_url?: string;
}

interface PortalPlan {
  id: number;
  name: string;
  price: number;
  data_limit: number | null;
  duration_days: number | null;
}

interface PortalOrder {
  id: number;
  plan_name: string;
  amount: number;
  status: string;
  created_at: string;
}

function PortalBody() {
  const [lang, setLang] = useState<PortalLang>("fa");
  const [authed, setAuthed] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginErr, setLoginErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<PortalProfile | null>(null);
  const [plans, setPlans] = useState<PortalPlan[]>([]);
  const [orders, setOrders] = useState<PortalOrder[]>([]);
  const [payProviders, setPayProviders] = useState<string[]>([]);
  const [currencyLabel, setCurrencyLabel] = useState("");
  const [toast, setToast] = useState("");

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 3200);
  };

  const loadDashboard = useCallback(async () => {
    const me = await portalGet<PortalProfile>("/portal/me");
    setProfile(me);
    try {
      const b = await portalGet<{ panel_title?: string; primary_color?: string; logo_url?: string; currency_label?: string }>("/portal/branding");
      if (b?.primary_color) document.documentElement.style.setProperty("--nx-accent", b.primary_color);
      if (b?.panel_title) document.title = b.panel_title;
      if (b?.currency_label) setCurrencyLabel(b.currency_label);
    } catch { /* optional */ }
    try {
      const p = await portalGet<PortalPlan[]>("/portal/plans");
      setPlans(p);
    } catch {
      setPlans([]);
    }
    try {
      const o = await portalGet<PortalOrder[]>("/portal/orders");
      setOrders(o);
    } catch {
      setOrders([]);
    }
    try {
      const psp = await portalGet<string[]>("/portal/payment-providers");
      setPayProviders(psp);
    } catch {
      setPayProviders([]);
    }
  }, []);

  useEffect(() => {
    const l = detectPortalLang();
    setLang(l);
    document.documentElement.lang = l;
    document.documentElement.dir = l === "fa" ? "rtl" : "ltr";
    if (getPortalToken()) {
      loadDashboard()
        .then(() => setAuthed(true))
        .catch(() => {
          clearPortalToken();
          setAuthed(false);
        });
    }
  }, [loadDashboard]);

  const submitLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginErr("");
    setBusy(true);
    try {
      await portalLogin(username.trim(), password);
      await loadDashboard();
      setAuthed(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : pt(lang, "loginFailed");
      setLoginErr(msg === "401" ? pt(lang, "loginFailed") : msg);
    } finally {
      setBusy(false);
    }
  };

  const renew = async (planId: number) => {
    setBusy(true);
    try {
      await portalPost("/portal/renew", { plan_id: planId });
      showToast(pt(lang, "renewed"));
      await loadDashboard();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : pt(lang, "error");
      showToast(msg.includes("insufficient") ? pt(lang, "walletError") : msg);
    } finally {
      setBusy(false);
    }
  };

  const payPlan = async (planId: number) => {
    setBusy(true);
    try {
      const provider = payProviders[0] || "demo";
      const created = await portalPost<{ payment_id: number; confirm_token?: string }>("/portal/payments", {
        plan_id: planId,
        provider,
      });
      if (created.confirm_token) {
        await portalPost(`/portal/payments/${created.payment_id}/complete`, {
          confirm_token: created.confirm_token,
        });
      }
      showToast(pt(lang, "renewed"));
      await loadDashboard();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : pt(lang, "error");
      showToast(msg);
    } finally {
      setBusy(false);
    }
  };

  const logout = () => {
    clearPortalToken();
    setAuthed(false);
    setProfile(null);
    setPlans([]);
    setOrders([]);
  };

  const subUrl = profile?.public_subscription_url || profile?.subscription_url || "";
  const subscribeBrowserUrl = resolveSubscribeBrowserUrl(subUrl);
  const rtl = lang === "fa";

  const pickLang = (code: PortalLang) => {
    setLang(code);
    document.documentElement.lang = code;
    document.documentElement.dir = code === "fa" ? "rtl" : "ltr";
    const u = new URL(window.location.href);
    u.searchParams.set("lang", code);
    window.history.replaceState({}, "", u.toString());
  };
  const usagePct =
    profile?.data_limit && profile.data_limit > 0
      ? Math.min(100, (profile.used_traffic / profile.data_limit) * 100)
      : 0;

  const formatPrice = (minor: number) => {
    if (minor === 0) return pt(lang, "free");
    const label = currencyLabel || (lang === "fa" ? "تومان" : "");
    return `${(minor / 100).toLocaleString(lang === "fa" ? "fa-IR" : undefined)}${label ? ` ${label}` : ""}`;
  };

  if (!authed) {
    return (
      <div className="portal-wrap" dir={rtl ? "rtl" : "ltr"} lang={lang}>
        <div className="portal-head">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <h1>{pt(lang, "title")}</h1>
              <p>{pt(lang, "subtitle")}</p>
            </div>
            <PortalLangPicker lang={lang} onPick={pickLang} />
          </div>
        </div>
        <form className="portal-login sub-card p-5" onSubmit={submitLogin}>
          {loginErr && <div className="portal-err">{loginErr}</div>}
          <div className="portal-field">
            <label>{pt(lang, "username")}</label>
            <input
              className="portal-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              required
            />
          </div>
          <div className="portal-field">
            <label>{pt(lang, "password")}</label>
            <input
              className="portal-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <button className="portal-btn" type="submit" disabled={busy}>
            {busy ? pt(lang, "loading") : pt(lang, "login")}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="portal-wrap" dir={rtl ? "rtl" : "ltr"} lang={lang}>
      <div className="portal-toolbar">
        <div>
          <h1 style={{ margin: 0, fontSize: "1.25rem" }}>{profile?.username}</h1>
          <span className="text-sm text-sub-muted">
            {pt(lang, "status")}: {pt(lang, profile?.status || "active")}
          </span>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <PortalLangPicker lang={lang} onPick={pickLang} />
          <button type="button" className="portal-btn portal-btn-ghost" onClick={logout}>
            {pt(lang, "logout")}
          </button>
        </div>
      </div>

      {profile && (
        <>
          <div className="portal-statgrid">
            <div className="portal-stat">
              <div className="portal-stat-k">{pt(lang, "used")}</div>
              <div className="portal-stat-v">{bytes(profile.used_traffic)}</div>
            </div>
            <div className="portal-stat">
              <div className="portal-stat-k">{pt(lang, "total")}</div>
              <div className="portal-stat-v">
                {profile.data_limit ? bytes(profile.data_limit) : pt(lang, "unlimited")}
              </div>
            </div>
            <div className="portal-stat">
              <div className="portal-stat-k">{pt(lang, "expire")}</div>
              <div className="portal-stat-v">
                {profile.expire ? formatDate(profile.expire) : pt(lang, "never")}
              </div>
            </div>
            <div className="portal-stat">
              <div className="portal-stat-k">{pt(lang, "status")}</div>
              <div className="portal-stat-v">{pt(lang, profile.status)}</div>
            </div>
          </div>

          {profile.data_limit ? (
            <div className="sub-card p-4 mb-5">
              <UsageBar
                used={profile.used_traffic}
                total={profile.data_limit}
                usedLabel={pt(lang, "used")}
                totalLabel={pt(lang, "total")}
                pct={usagePct}
                exhausted={usagePct >= 100}
                overage={profile.overage_traffic ?? 0}
                overageLabel={pt(lang, "overage")}
              />
            </div>
          ) : null}

          {subUrl ? (
            <div className="sub-card p-4 mb-5">
              <div className="font-semibold mb-2">{pt(lang, "subscription")}</div>
              <p className="text-sm text-sub-muted mb-2">{pt(lang, "subHint")}</p>
              <a href={subscribeBrowserUrl || subUrl} className="text-indigo-600 text-sm break-all" target="_blank" rel="noreferrer">
                {pt(lang, "openSub")}
              </a>
            </div>
          ) : null}
        </>
      )}

      <div className="sub-card p-4 mb-5">
        <h2 style={{ fontSize: "1rem", margin: "0 0 14px" }}>{pt(lang, "plans")}</h2>
        {plans.length === 0 ? (
          <p className="text-sub-muted text-sm">{pt(lang, "noPlans")}</p>
        ) : (
          plans.map((p) => (
            <div key={p.id} className="portal-plan">
              <div>
                <div className="portal-plan-name">{p.name}</div>
                <div className="portal-plan-meta">
                  {p.data_limit ? bytes(p.data_limit) : pt(lang, "unlimited")}
                  {p.duration_days ? ` · ${p.duration_days} ${pt(lang, "days")}` : ""}
                  {" · "}
                  {formatPrice(p.price)}
                </div>
              </div>
              {p.price > 0 && payProviders.length > 0 ? (
                <button
                  type="button"
                  className="portal-btn"
                  disabled={busy}
                  onClick={() => payPlan(p.id)}
                >
                  {busy ? pt(lang, "paying") : pt(lang, "pay")}
                </button>
              ) : (
                <button
                  type="button"
                  className="portal-btn portal-btn-ghost"
                  disabled={busy}
                  onClick={() => renew(p.id)}
                >
                  {pt(lang, "renew")}
                </button>
              )}
            </div>
          ))
        )}
      </div>

      <div className="sub-card p-4">
        <h2 style={{ fontSize: "1rem", margin: "0 0 14px" }}>{pt(lang, "orders")}</h2>
        {orders.length === 0 ? (
          <p className="text-sub-muted text-sm">{pt(lang, "noOrders")}</p>
        ) : (
          <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {orders.map((o) => (
              <li
                key={o.id}
                style={{
                  padding: "10px 0",
                  borderBottom: "1px solid var(--sub-border)",
                  fontSize: "0.88rem",
                }}
              >
                <strong>{o.plan_name}</strong> — {formatPrice(o.amount)} — {o.status}
              </li>
            ))}
          </ul>
        )}
      </div>

      {toast ? <div className="portal-toast">{toast}</div> : null}
    </div>
  );
}

function PortalLangPicker({ lang, onPick }: { lang: PortalLang; onPick: (c: PortalLang) => void }) {
  return (
    <div className="flex gap-0.5 rounded-lg border border-slate-200 bg-white p-0.5 shadow-sm" role="group" aria-label={pt(lang, "lang")}>
      {PORTAL_LANGS.map((l) => (
        <button
          key={l.code}
          type="button"
          onClick={() => onPick(l.code)}
          className={`rounded-md px-2 py-1 text-[10px] font-bold transition ${lang === l.code ? "bg-indigo-100 text-indigo-700" : "text-slate-400 hover:text-slate-600"}`}
        >
          {l.label}
        </button>
      ))}
    </div>
  );
}

export default function PortalPage() {
  return (
    <Suspense fallback={<div className="portal-wrap">{detectPortalLang() === "fa" ? "در حال بارگذاری…" : "Loading…"}</div>}>
      <PortalBody />
    </Suspense>
  );
}
