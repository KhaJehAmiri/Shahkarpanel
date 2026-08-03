"use client";

import { useEffect, useRef } from "react";
import {
  Home,
  KeyRound,
  LogOut,
  Radio,
  ShoppingBag,
  History,
  Shield,
} from "lucide-react";
import { PORTAL_LANGS, pt } from "@/lib/portal-i18n";
import { accountHealth, healthRemainingLabel, remainingDataPct } from "../format";
import { usePortal } from "../PortalContext";
import type { TabId } from "../types";
import { bytes } from "@/lib/format";
import { InstallBanner } from "./InstallBanner";

const NAV: { id: TabId; icon: typeof Home; labelKey: string; mobile?: boolean }[] = [
  { id: "home", icon: Home, labelKey: "nav_home", mobile: true },
  { id: "accounts", icon: Radio, labelKey: "nav_connect", mobile: true },
  { id: "shop", icon: ShoppingBag, labelKey: "nav_shop", mobile: true },
  { id: "family", icon: Shield, labelKey: "nav_family", mobile: true },
  { id: "history", icon: History, labelKey: "nav_history", mobile: true },
  { id: "security", icon: KeyRound, labelKey: "nav_security" },
];

/** In-place account picker — switches active account without changing tab. */
export function AccountPickerStrip({ title }: { title?: string }) {
  const { lang, accounts, activeUsername, setActiveUsername } = usePortal();

  if (accounts.length === 0) return null;

  return (
    <section className="p-card p-card-pad p-picker">
      <div className="p-picker-head">
        <div>
          <div className="p-kicker">{title || pt(lang, "chooseAccount")}</div>
          <p className="p-picker-desc">{pt(lang, "chooseAccountHint")}</p>
        </div>
        {accounts.length > 1 ? (
          <span className="p-muted" style={{ fontSize: "0.78rem", fontWeight: 700 }}>
            {accounts.length} {pt(lang, "accounts")}
          </span>
        ) : null}
      </div>
      <div className="p-picker-grid" role="listbox" aria-label={pt(lang, "chooseAccount")}>
        {accounts.map((a) => {
          const health = accountHealth(a);
          const dataRem = remainingDataPct(a.used_traffic, a.data_limit);
          const selected = a.username === activeUsername;
          return (
            <button
              key={a.username}
              type="button"
              role="option"
              aria-selected={selected}
              className={`p-picker-card health-${health}${selected ? " is-on" : ""}`}
              onClick={() => setActiveUsername(a.username)}
            >
              <div className="p-picker-card-top">
                <div className="p-avatar" aria-hidden>
                  {a.username.slice(0, 1).toUpperCase()}
                </div>
                <div className="p-picker-card-copy">
                  <strong dir="ltr">{a.username}</strong>
                  <span className={`p-health-pill ${health}`}>
                    {health === "danger"
                      ? pt(lang, "healthDanger")
                      : health === "warn"
                        ? pt(lang, "healthWarn")
                        : pt(lang, "healthOk")}
                  </span>
                </div>
                {selected ? <span className="p-picker-check" aria-hidden>✓</span> : null}
              </div>
              <div className="p-picker-card-meta">
                <span className={`p-chip ${a.status === "active" ? "ok" : a.status === "expired" ? "danger" : "warn"}`}>
                  {pt(lang, a.status)}
                </span>
                <span className={`p-chip ${a.online ? "ok" : ""}`}>
                  {a.online ? pt(lang, "online") : pt(lang, "offline")}
                </span>
              </div>
              <div className="p-picker-card-usage">
                {bytes(a.used_traffic)} / {a.data_limit ? bytes(a.data_limit) : pt(lang, "unlimited")}
                {dataRem != null ? ` · ${Math.round(dataRem)}% ${pt(lang, "remaining")}` : ""}
              </div>
              {health !== "ok" ? (
                <div className="p-picker-card-alert">{healthRemainingLabel(lang, a)}</div>
              ) : null}
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const {
    lang,
    rtl,
    tab,
    setTab,
    brandTitle,
    brandLogo,
    me,
    activeUsername,
    supportUrl,
    logout,
    txUnreadCount,
  } = usePortal();

  const contentRef = useRef<HTMLElement>(null);
  const mobileNav = NAV.filter((n) => n.mobile);

  useEffect(() => {
    const el = contentRef.current;
    if (el) el.scrollTop = 0;
  }, [tab]);

  const goTab = (id: TabId) => {
    setTab(id);
  };

  return (
    <div className="p-app" dir={rtl ? "rtl" : "ltr"} lang={lang}>
      <aside className="p-sidebar" aria-label={pt(lang, "title")}>
        <div className="p-sidebar-brand">
          <img
            src={brandLogo || "/sub-assets/brand/shahkar.png"}
            alt=""
            className="p-brand-logo"
          />
          <div className="p-sidebar-brand-text">
            <strong>{brandTitle || pt(lang, "brand")}</strong>
            <small dir="ltr">{me?.username}</small>
          </div>
        </div>
        <nav className="p-nav">
          {NAV.map((item) => {
            const Icon = item.icon;
            const unread = item.id === "history" ? txUnreadCount : 0;
            return (
              <button
                key={item.id}
                type="button"
                className={`p-nav-item${tab === item.id ? " is-on" : ""}`}
                onClick={() => goTab(item.id)}
              >
                <span className="p-nav-icon-wrap">
                  <Icon aria-hidden />
                </span>
                <span className="p-nav-label">{pt(lang, item.labelKey)}</span>
                {unread > 0 ? (
                  <span className="p-nav-badge">{unread > 99 ? "99+" : unread}</span>
                ) : null}
              </button>
            );
          })}
        </nav>
        <div className="p-sidebar-foot">
          {supportUrl ? (
            <a className="p-btn ghost" href={supportUrl} target="_blank" rel="noreferrer">
              {pt(lang, "support")}
            </a>
          ) : null}
          <LangPicker />
          <button type="button" className="p-btn ghost" onClick={logout}>
            <LogOut size={16} aria-hidden />
            {pt(lang, "logout")}
          </button>
        </div>
      </aside>

      <div className="p-main">
        <header className="p-topbar">
          <div className="p-topbar-welcome">
            <div className="p-kicker" style={{ marginBottom: 0 }}>
              {pt(lang, "welcome")}
            </div>
            <div className="p-topbar-welcome-name" dir="ltr">
              {activeUsername || me?.username || "—"}
            </div>
          </div>
          <div className="p-topbar-actions">
            <div className="p-topbar-lang">
              <LangPicker compact />
            </div>
            <button
              type="button"
              className="p-btn ghost"
              onClick={() => goTab("security")}
              aria-label={pt(lang, "nav_security")}
            >
              <KeyRound size={16} />
            </button>
            <button type="button" className="p-btn ghost" onClick={logout} aria-label={pt(lang, "logout")}>
              <LogOut size={16} />
            </button>
          </div>
        </header>

        <InstallBanner />
        <main className="p-content" ref={contentRef}>
          {children}
        </main>
      </div>

      <nav className="p-bottom-nav" aria-label={pt(lang, "title")}>
        {mobileNav.map((item) => {
          const Icon = item.icon;
          const unread = item.id === "history" ? txUnreadCount : 0;
          return (
            <button
              key={item.id}
              type="button"
              className={`p-nav-item${tab === item.id ? " is-on" : ""}`}
              onClick={() => goTab(item.id)}
            >
              <span className="p-nav-icon-wrap">
                <Icon aria-hidden />
                {unread > 0 ? (
                  <span className="p-nav-badge">{unread > 99 ? "99+" : unread}</span>
                ) : null}
              </span>
              <span className="p-nav-label">{pt(lang, item.labelKey)}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}

function LangPicker({ compact = false }: { compact?: boolean }) {
  const { lang, pickLang } = usePortal();
  return (
    <div className="p-lang" role="group" aria-label={pt(lang, "lang")}>
      {PORTAL_LANGS.map((l) => (
        <button
          key={l.code}
          type="button"
          className={lang === l.code ? "is-on" : ""}
          onClick={() => pickLang(l.code)}
          title={l.label}
          aria-label={l.label}
        >
          {compact ? l.code.toUpperCase() : l.label}
        </button>
      ))}
    </div>
  );
}

export function PageHeader({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="p-page-header">
      <h1>{title}</h1>
      {hint ? <p>{hint}</p> : null}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
  actionLabel,
  onAction,
}: {
  icon: React.ReactNode;
  title: string;
  hint?: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="p-card p-card-pad p-empty">
      <div className="p-empty-icon">{icon}</div>
      <h3>{title}</h3>
      {hint ? <p>{hint}</p> : null}
      {actionLabel && onAction ? (
        <button type="button" className="p-btn" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const { lang } = usePortal();
  const tone =
    status === "active"
      ? "ok"
      : status === "on_hold" || status === "limited"
        ? "warn"
        : status === "expired" || status === "disabled"
          ? "danger"
          : "";
  return (
    <span className={`p-chip ${tone}`}>
      {status === "active" ? <span className="p-dot" /> : null}
      {pt(lang, status)}
    </span>
  );
}

export function UsageMeter({
  pct,
  usedLabel,
  limitLabel,
}: {
  pct: number;
  usedLabel: string;
  limitLabel: string;
}) {
  const { lang } = usePortal();
  return (
    <div className="p-usage-wrap">
      <div className="p-ring" style={{ ["--pct" as string]: pct }}>
        <div className="p-ring-inner">{Number.isFinite(pct) ? `${Math.round(pct)}%` : "∞"}</div>
      </div>
      <div>
        <div className="p-kicker">{pt(lang, "trafficUsage")}</div>
        <strong>
          {usedLabel} / {limitLabel}
        </strong>
      </div>
    </div>
  );
}

export function Toast() {
  const { toast } = usePortal();
  if (!toast) return null;
  return <div className="p-toast">{toast}</div>;
}
