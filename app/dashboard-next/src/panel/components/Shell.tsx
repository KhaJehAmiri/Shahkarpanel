import { FC, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { brandLogoUrl, brandingTitle } from "../lib/branding";
import { useCopilot } from "../copilot/CopilotContext";
import { Copilot } from "../copilot/Copilot";
import { LANGUAGES, setLanguage } from "../i18n";
import { IcGlobe, IcLogout, IcMenu, IcMoon, IcSun, navIcon } from "./icons";
import { AutoWebPush } from "./AutoWebPush";
import { UpdateProvider } from "../context/UpdateContext";
import { PanelVersionStrip } from "./PanelVersionStrip";

/** Main nav: finance + resellers are first-class; Business = analytics/automation. */
const NAV_SUDO = [
  { group: "main", items: ["home", "users", "servers", "connection", "billing", "resellers", "business"] },
];

const PATHS: Record<string, string> = {
  home: "/overview",
  overview: "/overview",
  users: "/users",
  servers: "/servers",
  connection: "/connection",
  billing: "/billing",
  resellers: "/resellers",
  business: "/business",
  system: "/system",
  // Legacy redirects handled in DashboardRoot
  inbounds: "/connection",
  nodes: "/servers",
  tunnels: "/servers",
  wireguard: "/servers",
  singbox: "/servers",
  dedip: "/servers",
  xray: "/connection",
  hosts: "/connection",
  analytics: "/business",
  automation: "/business",
  infrastructure: "/servers",
};

const NavItem: FC<{ id: string; onNav: () => void }> = ({ id, onNav }) => {
  const { t } = useTranslation();
  const path = PATHS[id];
  return (
    <NavLink
      to={path}
      onClick={onNav}
      className={({ isActive }) => `sk-nav-item ${isActive ? "active" : ""}`}
    >
      {navIcon(id)}
      <span>{t(`nav.${id}`)}</span>
    </NavLink>
  );
};

export const Shell: FC = () => {
  const { t, i18n } = useTranslation();
  const { admin, branding, theme, setTheme, logout } = useApp();
  const appTitle = brandingTitle(branding, t("common.appName"));
  const { setOpen: setCopilotOpen } = useCopilot();
  const [open, setOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const loc = useLocation();

  const nav = useMemo(() => {
    if (admin?.is_sudo) return NAV_SUDO;
    const role = admin?.role || "reseller";
    const items = ["home", "users"];
    if (role !== "support") items.push("servers", "billing", "resellers", "business");
    else items.push("business");
    return [{ group: "main", items }];
  }, [admin?.is_sudo, admin?.role]);

  const currentId = (() => {
    if (loc.pathname.startsWith("/overview")) return "home";
    if (loc.pathname.startsWith("/users")) return "users";
    if (loc.pathname.startsWith("/servers")) return "servers";
    if (loc.pathname.startsWith("/connection")) return "connection";
    if (loc.pathname.startsWith("/billing")) return "billing";
    if (loc.pathname.startsWith("/resellers")) return "resellers";
    if (loc.pathname.startsWith("/business")) return "business";
    if (loc.pathname.startsWith("/system")) return "system";
    return "home";
  })();
  const navTitle = t(`nav.${currentId}`, { defaultValue: t("nav.home") });
  const roleLabel = admin?.is_sudo ? t("common.roleOwner") : t("common.roleReseller");

  const closeNav = () => setOpen(false);

  return (
    <UpdateProvider sudo={!!admin?.is_sudo} lang={i18n.language}>
    <div className="sk-app">
      <div className="sk-app-bg" aria-hidden />
      <div className={`sk-scrim ${open ? "show" : ""}`} onClick={closeNav} />
      <aside className={`sk-sidebar ${open ? "open" : ""}`}>
        <div className="sk-brand">
          <img src={brandLogoUrl(branding)} alt="" className="sk-brand-logo sk-brand-logo-img" />
          <div>
            <div className="sk-brand-name">{appTitle}</div>
            <div className="sk-brand-sub">{t("common.tagline")}</div>
          </div>
        </div>

        {nav.map((section) => (
          <div key={section.group}>
            <div className="sk-nav-group-label">{t(`nav.${section.group}`)}</div>
            {section.items.map((id) => (
              <NavItem key={id} id={id} onNav={closeNav} />
            ))}
          </div>
        ))}

        <div className="sk-spacer" />

        <button
          type="button"
          className="sk-side-assist"
          onClick={() => { setCopilotOpen(true); closeNav(); }}
        >
          <span className="sk-side-assist-ico" aria-hidden>✦</span>
          <span className="sk-side-assist-body">
            <b>{t("copilot.title")}</b>
            <small>{t("overview.openGuide")}</small>
          </span>
        </button>

        <NavItem id="system" onNav={closeNav} />

        <PanelVersionStrip sudo={!!admin?.is_sudo} />

        <div className="sk-side-profile">
          <span className="sk-side-avatar">{(admin?.username || "?").slice(0, 1).toUpperCase()}</span>
          <span className="sk-side-profile-body">
            <b>{admin?.username}</b>
            <small>{roleLabel}</small>
          </span>
          <button className="sk-btn icon ghost" title={t("common.logout")} aria-label={t("common.logout")} onClick={logout}>
            <IcLogout />
          </button>
        </div>
      </aside>

      <div className="sk-main">
        <header className="sk-topbar">
          <div className="sk-row" style={{ gap: 10 }}>
            <button className="sk-btn icon ghost sk-hamburger" title={t("common.menu")} aria-label={t("common.menu")} onClick={() => setOpen((o) => !o)}>
              <IcMenu />
            </button>
            <div>
              <div className="sk-topbar-title">{navTitle}</div>
              <div className="sk-breadcrumb">{appTitle} / {navTitle}</div>
            </div>
          </div>

          <div className="sk-row" style={{ gap: 8, position: "relative" }}>
            <AutoWebPush />
            <button className="sk-btn ghost sm sk-copilot-topbtn" onClick={() => setCopilotOpen(true)} title={t("copilot.open")}>
              <span aria-hidden>✦</span>
              <span className="sk-copilot-topbtn-label">{t("copilot.title")}</span>
            </button>
            <button
              className="sk-btn icon ghost"
              title={t("common.theme")}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <IcSun /> : <IcMoon />}
            </button>

            <button className="sk-btn ghost sm" onClick={() => setLangOpen((o) => !o)}>
              <IcGlobe className="sk-ico" />
              {LANGUAGES.find((l) => l.code === i18n.language)?.label || "English"}
            </button>
            {langOpen && (
              <>
                <div style={{ position: "fixed", inset: 0, zIndex: 30 }} onClick={() => setLangOpen(false)} />
                <div
                  className="sk-card"
                  style={{ position: "absolute", top: 44, insetInlineEnd: 0, padding: 6, zIndex: 40, minWidth: 160 }}
                >
                  {LANGUAGES.map((l) => (
                    <button
                      key={l.code}
                      className={`sk-nav-item ${i18n.language === l.code ? "active" : ""}`}
                      onClick={() => {
                        setLanguage(l.code);
                        setLangOpen(false);
                      }}
                    >
                      <span style={{ fontSize: 16 }}>{l.flag}</span>
                      <span>{l.label}</span>
                    </button>
                  ))}
                </div>
              </>
            )}

            <div className="sk-topbar-user sk-row" style={{ gap: 8, marginInlineStart: 6 }}>
              <div style={{ textAlign: "end" }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{admin?.username}</div>
                <div className="sk-faint" style={{ fontSize: 11 }}>{roleLabel}</div>
              </div>
            </div>
          </div>
        </header>

        <main className="sk-content">
          <Outlet />
        </main>
      </div>

      <Copilot />
    </div>
    </UpdateProvider>
  );
};

export const PageHeader: FC<{ title: string; subtitle?: string; description?: any; actions?: any }> = ({ title, subtitle, description, actions }) => (
  <div className="sk-page-head">
    <div className="sk-page-head-copy">
      <div className="sk-page-title">{title}</div>
      {subtitle && <div className="sk-page-subtitle">{subtitle}</div>}
      {description && <div className="sk-page-desc">{description}</div>}
    </div>
    {actions && <div className="sk-page-head-actions">{actions}</div>}
  </div>
);
