import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { login } from "../api/client";
import { useApp } from "../context/AppContext";
import { LANGUAGES, setLanguage } from "../i18n";
import { Button, Field, Input } from "../components/ui";

export const Login: FC = () => {
  const { t, i18n } = useTranslation();
  const { onAuthenticated } = useApp();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username.trim(), password);
      await onAuthenticated();
    } catch (err: any) {
      setError(err?.status === 401 ? t("login.failed") : err?.message || t("common.error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="nx-login">
      <div className="nx-login-card">
        <div className="nx-brand" style={{ padding: "0 0 22px", justifyContent: "center" }}>
          <div className="nx-brand-logo" style={{ width: 40, height: 40, fontSize: 18 }}>N</div>
          <div>
            <div className="nx-brand-name" style={{ fontSize: 18 }}>{t("common.appName")}</div>
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
          {error && <div className="nx-callout danger" style={{ padding: "10px 12px" }}>{error}</div>}
          <Button type="submit" variant="primary" disabled={busy} className="nx-center">
            {busy ? t("login.signingIn") : t("login.signIn")}
          </Button>
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
