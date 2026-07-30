"use client";

import { PORTAL_LANGS, pt } from "@/lib/portal-i18n";
import { usePortal } from "../PortalContext";

export function LoginScreen() {
  const {
    lang,
    rtl,
    brandTitle,
    brandLogo,
    loginUser,
    setLoginUser,
    password,
    setPassword,
    loginErr,
    busy,
    submitLogin,
    pickLang,
  } = usePortal();

  return (
    <div className="p-login" dir={rtl ? "rtl" : "ltr"} lang={lang}>
      <form className="p-login-card" onSubmit={submitLogin}>
        <div className="p-login-brand">
          <div className="p-login-mark">
            <img
              src={brandLogo || "/sub-assets/brand/shahkar.png"}
              alt=""
              className="p-brand-logo"
            />
            <span>{brandTitle || pt(lang, "brand")}</span>
          </div>
          <div className="p-lang" role="group" aria-label={pt(lang, "lang")}>
            {PORTAL_LANGS.map((l) => (
              <button
                key={l.code}
                type="button"
                className={lang === l.code ? "is-on" : ""}
                onClick={() => pickLang(l.code)}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>
        <h1>{pt(lang, "title")}</h1>
        <p>{pt(lang, "subtitle")}</p>
        {loginErr ? <div className="p-err">{loginErr}</div> : null}
        <div className="p-field">
          <label htmlFor="portal-user">{pt(lang, "username")}</label>
          <input
            id="portal-user"
            className="p-input"
            value={loginUser}
            onChange={(e) => setLoginUser(e.target.value)}
            autoFocus
            required
            dir="ltr"
            autoComplete="username"
          />
        </div>
        <div className="p-field">
          <label htmlFor="portal-pass">{pt(lang, "password")}</label>
          <input
            id="portal-pass"
            className="p-input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
          />
        </div>
        <button className="p-btn block" type="submit" disabled={busy}>
          {busy ? pt(lang, "loading") : pt(lang, "login")}
        </button>
      </form>
    </div>
  );
}
