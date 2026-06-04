import { FC, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import { Copilot } from "../copilot/Copilot";
import { LANGUAGES, setLanguage } from "../i18n";
import { IcGlobe, IcLogout, IcMenu, IcMoon, IcSun, navIcon } from "./icons";

const NAV_BASE = [
  { group: "main", items: ["overview", "inbounds", "users"] as string[] },
  { group: "platform", items: ["infrastructure", "automation", "analytics"] },
  { group: "business", items: ["resellers", "billing"] },
];

const PATHS: Record<string, string> = {
  overview: "/overview",
  inbounds: "/inbounds",
  users: "/users",
  infrastructure: "/infrastructure",
  automation: "/automation",
  analytics: "/analytics",
  resellers: "/resellers",
  billing: "/billing",
  system: "/system",
};

const NavItem: FC<{ id: string; onNav: () => void }> = ({ id, onNav }) => {
  const { t } = useTranslation();
  const iconKey = id === "infrastructure" ? "infra" : id;
  return (
    <NavLink to={PATHS[id]} onClick={onNav} className={({ isActive }) => `nx-nav-item ${isActive ? "active" : ""}`}>
      {navIcon(iconKey)}
      <span>{t(`nav.${id}`)}</span>
    </NavLink>
  );
};

export const Shell: FC = () => {
  const { t, i18n } = useTranslation();
  const { admin, theme, setTheme, logout } = useApp();
  const { setOpen: setCopilotOpen } = useCopilot();
  const [open, setOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const loc = useLocation();

  const nav = useMemo(() => {
    if (admin?.is_sudo) return NAV_BASE;
    const role = admin?.role || "reseller";
    return NAV_BASE.map((s) => {
      let items = s.items.filter((id) => id !== "inbounds" && id !== "infrastructure" && id !== "automation");
      if (role === "support") {
        items = items.filter((id) => id !== "resellers" && id !== "billing");
      }
      return { ...s, items };
    });
  }, [admin?.is_sudo, admin?.role]);

  const currentId =
    Object.keys(PATHS).find((k) => loc.pathname.startsWith(PATHS[k])) || "overview";

  const closeNav = () => setOpen(false);

  return (
    <div className="nx-app">
      <div className={`nx-scrim ${open ? "show" : ""}`} onClick={closeNav} />
      <aside className={`nx-sidebar ${open ? "open" : ""}`}>
        <div className="nx-brand">
          <div className="nx-brand-logo">N</div>
          <div>
            <div className="nx-brand-name">{t("common.appName")}</div>
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
        <div className="nx-nav-group-label">{t("nav.platform")}</div>
        <NavItem id="system" onNav={closeNav} />
      </aside>

      <div className="nx-main">
        <header className="nx-topbar">
          <div className="nx-row" style={{ gap: 10 }}>
            <button className="nx-btn icon ghost nx-hamburger" onClick={() => setOpen((o) => !o)}>
              <IcMenu />
            </button>
            <div>
              <div className="nx-topbar-title">{t(`nav.${currentId}`)}</div>
              <div className="nx-breadcrumb">{t("common.appName")} / {t(`nav.${currentId}`)}</div>
            </div>
          </div>

          <div className="nx-row" style={{ gap: 8, position: "relative" }}>
            <button className="nx-btn ghost sm nx-copilot-topbtn" onClick={() => setCopilotOpen(true)} title={t("copilot.open")}>
              <span aria-hidden>✦</span>
              <span className="nx-copilot-topbtn-label">{t("copilot.title")}</span>
            </button>
            <button
              className="nx-btn icon ghost"
              title="Theme"
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
                <div className="nx-faint" style={{ fontSize: 11 }}>
                  {admin?.is_sudo ? "Owner" : "Reseller"}
                </div>
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
