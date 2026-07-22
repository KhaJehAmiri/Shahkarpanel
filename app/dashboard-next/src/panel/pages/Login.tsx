import { FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, login, setRefreshToken, setToken } from "../api/client";
import { Branding } from "../api/types";
import { useApp } from "../context/AppContext";
import { LANGUAGES, setLanguage } from "../i18n";
import { applyBranding, brandLogoUrl, brandingTitle } from "../lib/branding";
import { Button, Field, Input } from "../components/ui";

export const Login: FC = () => {
  const { t, i18n } = useTranslation();
  const { onAuthenticated } = useApp();
  const [branding, setBranding] = useState<Branding | null>(null);

  useEffect(() => {
    const host = typeof window !== "undefined" ? window.location.hostname : "";
    const q = host ? `?domain=${encodeURIComponent(host)}` : "";
    api.get<Branding>(`/branding${q}`).then((b) => {
      setBranding(b);
      applyBranding(b);
    }).catch(() => {});
    api.get<{ default_lang?: string }>("/setup/status").then((s) => {
      if (!localStorage.getItem("nx_lang") && s.default_lang) {
        setLanguage(s.default_lang);
      }
    }).catch(() => {});
  }, []);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [requires2fa, setRequires2fa] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ssoUrl, setSsoUrl] = useState<string | null>(null);
  const [ssoBusy, setSsoBusy] = useState(false);

  useEffect(() => {
    api.get<{ enabled?: boolean; authorize_url?: string }>("/admin/sso/public")
      .then((cfg) => { if (cfg.enabled && cfg.authorize_url) setSsoUrl(cfg.authorize_url); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    if (!code) return;
    setSsoBusy(true);
    setError("");
    api.post<{ access_token: string; refresh_token?: string }>("/admin/sso/callback", {
      code,
      redirect_uri: window.location.origin + window.location.pathname,
    })
      .then(async (res) => {
        setToken(res.access_token);
        if (res.refresh_token) setRefreshToken(res.refresh_token);
        window.history.replaceState({}, "", window.location.pathname + window.location.hash);
        await onAuthenticated();
      })
      .catch((err: any) => {
        setError(err?.message || t("common.error"));
      })
      .finally(() => setSsoBusy(false));
  }, [onAuthenticated, t]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username.trim(), password, otp.trim() || undefined);
      await onAuthenticated();
    } catch (err: any) {
      const msg = String(err?.message || "");
      const is2fa = Boolean(err?.requires2fa) || (err?.status === 401 && /two-factor/i.test(msg));
      if (is2fa) {
        setRequires2fa(true);
        // Distinguish "please enter code" from "code was wrong".
        setError(otp ? t("login.otpInvalid") : t("login.otpRequired"));
      } else {
        setError(err?.status === 401 ? t("login.failed") : err?.message || t("common.error"));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="nx-login">
      <div className="nx-app-bg" aria-hidden />
      <div className="nx-login-card">
        <div className="nx-brand" style={{ padding: "0 0 22px", justifyContent: "center" }}>
          <img
            src={brandLogoUrl(branding)}
            alt=""
            className="nx-brand-logo nx-brand-logo-img"
            style={{ width: 40, height: 40 }}
          />
          <div>
            <div className="nx-brand-name" style={{ fontSize: 18 }}>{brandingTitle(branding, t("common.appName"))}</div>
            <div className="nx-brand-sub">{t("common.tagline")}</div>
          </div>
        </div>

        <h1 style={{ fontSize: 20, margin: "0 0 4px" }}>{t("login.title")}</h1>
        <p className="nx-muted" style={{ margin: "0 0 22px", fontSize: 13 }}>{t("login.subtitle")}</p>

        <form onSubmit={submit} className="nx-stack">
          <Field label={t("common.username")}>
            <Input value={username} onChange={(e: any) => setUsername(e.target.value)} autoFocus required />
          </Field>
          <Field label={t("common.password")}>
            <Input type="password" value={password} onChange={(e: any) => setPassword(e.target.value)} required />
          </Field>
          {requires2fa && (
            <Field label={t("login.otpLabel")}>
              <Input
                value={otp}
                onChange={(e: any) => setOtp(e.target.value)}
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="123456"
                autoFocus
                required
              />
            </Field>
          )}
          {error && <div className="nx-callout danger" style={{ padding: "10px 12px" }}>{error}</div>}
          <Button type="submit" variant="primary" disabled={busy || ssoBusy} className="nx-center">
            {busy || ssoBusy ? t("login.signingIn") : t("login.signIn")}
          </Button>
          {ssoUrl && (
            <Button
              type="button"
              variant="ghost"
              disabled={busy || ssoBusy}
              className="nx-center"
              onClick={() => { window.location.href = ssoUrl; }}
            >
              {t("login.ssoSignIn", { defaultValue: "Sign in with SSO" })}
            </Button>
          )}
        </form>

        <div className="nx-row" style={{ justifyContent: "center", gap: 4, marginTop: 22 }}>
          {LANGUAGES.map((l) => (
            <button
              key={l.code}
              className={`nx-btn ghost sm ${i18n.language === l.code ? "active" : ""}`}
              style={i18n.language === l.code ? { color: "var(--nx-accent)" } : undefined}
              onClick={() => setLanguage(l.code)}
              type="button"
            >
              {l.flag} {l.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
