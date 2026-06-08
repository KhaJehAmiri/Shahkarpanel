import { FC, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { brandingTitle } from "../lib/branding";
import { useCopilot } from "../copilot/CopilotContext";
import { Copilot } from "../copilot/Copilot";
import { LANGUAGES, setLanguage } from "../i18n";
import { IcGlobe, IcLogout, IcMenu, IcMoon, IcSun, navIcon } from "./icons";

/** Clear, task-oriented navigation — each item is one job, not a junk drawer. */
const NAV_SUDO = [
  { group: "work", items: ["overview", "users"] },
  { group: "connect", items: ["inbounds", "nodes", "tunnels", "wireguard", "dedip"] },
  { group: "advanced", items: ["xray", "hosts"] },
  { group: "manage", items: ["analytics", "automation"] },
  { group: "business", items: ["resellers", "billing"] },
];

const PATHS: Record<string, string> = {
  overview: "/overview",
  users: "/users",
  inbounds: "/inbounds",
  nodes: "/nodes",
  tunnels: "/tunnels",
  wireguard: "/wireguard",
  dedip: "/dedicated-ip",
  xray: "/xray",
  hosts: "/hosts",
  analytics: "/analytics",
  automation: "/automation",
  resellers: "/resellers",
  billing: "/billing",
  system: "/system",
  // Legacy bookmark
  infrastructure: "/nodes",
};

const NavItem: FC<{ id: string; onNav: () => void }> = ({ id, onNav }) => {
  const { t } = useTranslation();
  return (
    <NavLink to={PATHS[id]} onClick={onNav} className={({ isActive }) => `nx-nav-item ${isActive ? "active" : ""}`}>
      {navIcon(id)}
      <span>{t(`nav.${id}`)}</span>
    </NavLink>
  );
};

export const Shell: FC = () => {
  const { t, i18n } = useTranslation();
  const { admin, branding, theme, setTheme, logout, isEnabled } = useApp();
  const appTitle = brandingTitle(branding, t("common.appName"));
  const { setOpen: setCopilotOpen } = useCopilot();
  const [open, setOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const loc = useLocation();

  // Items that only make sense alongside a branded client app. They stay hidden
  // for plain panel operators until the client_api feature flag is enabled.
  const clientApiOn = isEnabled("client_api");

  const nav = useMemo(() => {
    const sections = admin?.is_sudo
      ? NAV_SUDO
      : (() => {
          const role = admin?.role || "reseller";
          const base = [{ group: "work", items: ["overview", "users"] }];
          if (role !== "support") {
            base.push({ group: "connect", items: ["nodes"] });
            base.push({ group: "business", items: ["resellers", "billing"] });
          }
          base.push({ group: "manage", items: ["analytics"] });
          return base;
        })();
    const hidden = clientApiOn ? [] : ["dedip"];
    return sections
      .map((s) => ({ ...s, items: s.items.filter((id) => !hidden.includes(id)) }))
      .filter((s) => s.items.length > 0);
  }, [admin?.is_sudo, admin?.role, clientApiOn]);

  const currentId =
    Object.keys(PATHS).find((k) => loc.pathname.startsWith(PATHS[k])) || "overview";
  const navTitle = t(`nav.${currentId}`, { defaultValue: t("nav.overview") });
  const roleLabel = admin?.is_sudo ? t("common.roleOwner") : t("common.roleReseller");

  const closeNav = () => setOpen(false);

  return (
    <div className="nx-app">
      <div className={`nx-scrim ${open ? "show" : ""}`} onClick={closeNav} />
      <aside className={`nx-sidebar ${open ? "open" : ""}`}>
        <div className="nx-brand">
          {branding?.logo_url ? (
            <img src={branding.logo_url} alt="" className="nx-brand-logo" style={{ objectFit: "contain" }} />
          ) : (
            <div className="nx-brand-logo">N</div>
          )}
          <div>
            <div className="nx-brand-name">{appTitle}</div>
            <div className="nx-brand-sub">{t("common.tagline")}</div>
          </div>
        </div>

        {nav.map((section) => (
          <div key={section.group}>
            <div className="nx-nav-group-label">{t(`nav.${section.group}`)}</div>
            {section.items.map((id) => (
              <NavItem key={id} id={id} onNav={closeNav} />
            ))}
          </div>
        ))}

        <div className="nx-spacer" />
        <NavItem id="system" onNav={closeNav} />
      </aside>

      <div className="nx-main">
        <header className="nx-topbar">
          <div className="nx-row" style={{ gap: 10 }}>
            <button className="nx-btn icon ghost nx-hamburger" onClick={() => setOpen((o) => !o)}>
              <IcMenu />
            </button>
            <div>
              <div className="nx-topbar-title">{navTitle}</div>
              <div className="nx-breadcrumb">{appTitle} / {navTitle}</div>
            </div>
          </div>

          <div className="nx-row" style={{ gap: 8, position: "relative" }}>
            <button className="nx-btn ghost sm nx-copilot-topbtn" onClick={() => setCopilotOpen(true)} title={t("copilot.open")}>
              <span aria-hidden>✦</span>
              <span className="nx-copilot-topbtn-label">{t("copilot.title")}</span>
            </button>
            <button
              className="nx-btn icon ghost"
              title={t("common.theme")}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <IcSun /> : <IcMoon />}
            </button>

            <button className="nx-btn ghost sm" onClick={() => setLangOpen((o) => !o)}>
              <IcGlobe className="nx-ico" />
              {LANGUAGES.find((l) => l.code === i18n.language)?.label || "English"}
            </button>
            {langOpen && (
              <>
                <div style={{ position: "fixed", inset: 0, zIndex: 30 }} onClick={() => setLangOpen(false)} />
                <div
                  className="nx-card"
                  style={{ position: "absolute", top: 44, insetInlineEnd: 0, padding: 6, zIndex: 40, minWidth: 160 }}
                >
                  {LANGUAGES.map((l) => (
                    <button
                      key={l.code}
                      className={`nx-nav-item ${i18n.language === l.code ? "active" : ""}`}
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

            <div className="nx-row" style={{ gap: 8, marginInlineStart: 6 }}>
              <div style={{ textAlign: "end" }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{admin?.username}</div>
                <div className="nx-faint" style={{ fontSize: 11 }}>{roleLabel}</div>
              </div>
              <button className="nx-btn icon ghost" title={t("common.logout")} onClick={logout}>
                <IcLogout />
              </button>
            </div>
          </div>
        </header>

        <main className="nx-content">
          <Outlet />
        </main>
      </div>

      <Copilot />
    </div>
  );
};

export const PageHeader: FC<{ title: string; subtitle?: string; description?: any; actions?: any }> = ({ title, subtitle, description, actions }) => (
  <div className="nx-page-head">
    <div style={{ minWidth: 0, flex: 1 }}>
      <div className="nx-page-title">{title}</div>
      {subtitle && <div className="nx-page-subtitle">{subtitle}</div>}
      {description && <div className="nx-page-desc">{description}</div>}
    </div>
    {actions && <div className="nx-row" style={{ flexShrink: 0 }}>{actions}</div>}
  </div>
);
