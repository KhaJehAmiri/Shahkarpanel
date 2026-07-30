"use client";

import { useState } from "react";
import { pt } from "@/lib/portal-i18n";
import { usePortal } from "../PortalContext";

export function SetupCredentialsView() {
  const { lang, rtl, brandTitle, busy, completeSetup, me, logout } = usePortal();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState("");

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    const u = username.trim().toLowerCase();
    if (!/^[a-z0-9_]{3,32}$/.test(u)) {
      setErr(pt(lang, "setupUsernameInvalid"));
      return;
    }
    if (password.length < 4) {
      setErr(pt(lang, "setupPasswordShort"));
      return;
    }
    if (password !== confirm) {
      setErr(pt(lang, "passwordMismatch"));
      return;
    }
    if (password.toLowerCase() === u) {
      setErr(pt(lang, "setupPasswordSameAsUser"));
      return;
    }
    try {
      await completeSetup(u, password);
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : pt(lang, "error"));
    }
  };

  return (
    <div className="p-login" dir={rtl ? "rtl" : "ltr"} lang={lang}>
      <form className="p-login-card" onSubmit={onSubmit} style={{ maxWidth: 460 }}>
        <div className="p-login-brand">
          <div className="p-login-mark">
            {brandTitle || pt(lang, "brand")}
            <span>.</span>
          </div>
        </div>
        <h1>{pt(lang, "setupTitle")}</h1>
        <p>{pt(lang, "setupHint")}</p>
        {me?.username ? (
          <div className="p-note" style={{ marginBottom: 14 }}>
            {pt(lang, "setupCurrentUser")}: <strong dir="ltr">{me.username}</strong>
          </div>
        ) : null}
        {err ? <div className="p-err">{err}</div> : null}
        <div className="p-field">
          <label htmlFor="setup-user">{pt(lang, "setupNewUsername")}</label>
          <input
            id="setup-user"
            className="p-input"
            dir="ltr"
            value={username}
            onChange={(e) => setUsername(e.target.value.toLowerCase())}
            placeholder="my_account"
            autoFocus
            required
            autoComplete="username"
          />
        </div>
        <div className="p-field">
          <label htmlFor="setup-pass">{pt(lang, "setupNewPassword")}</label>
          <input
            id="setup-pass"
            className="p-input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="new-password"
          />
        </div>
        <div className="p-field">
          <label htmlFor="setup-confirm">{pt(lang, "confirmPassword")}</label>
          <input
            id="setup-confirm"
            className="p-input"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            autoComplete="new-password"
          />
        </div>
        <button className="p-btn block" type="submit" disabled={busy}>
          {busy ? pt(lang, "loading") : pt(lang, "setupSave")}
        </button>
        <button type="button" className="p-btn ghost block" style={{ marginTop: 8 }} onClick={logout}>
          {pt(lang, "logout")}
        </button>
      </form>
    </div>
  );
}
