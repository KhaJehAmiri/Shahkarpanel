"use client";

import { pt } from "@/lib/portal-i18n";
import { usePortal } from "../PortalContext";
import { PageHeader } from "../components/Shell";

export function SecurityView() {
  const {
    lang,
    curPw,
    setCurPw,
    newPw,
    setNewPw,
    confirmPw,
    setConfirmPw,
    busy,
    savePassword,
  } = usePortal();

  const canSave = !busy && Boolean(curPw) && newPw.length >= 4;

  return (
    <div className="p-stack">
      <PageHeader title={pt(lang, "securityTitle")} hint={pt(lang, "securityHint")} />
      <section className="p-card p-card-pad" style={{ maxWidth: 480 }}>
        <h2 className="p-section-title">{pt(lang, "passwordChange")}</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canSave) void savePassword();
          }}
        >
          <div className="p-field">
            <label htmlFor="sec-cur-pw">{pt(lang, "currentPassword")}</label>
            <input
              id="sec-cur-pw"
              className="p-input"
              type="password"
              value={curPw}
              onChange={(e) => setCurPw(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          <div className="p-field">
            <label htmlFor="sec-new-pw">{pt(lang, "newPassword")}</label>
            <input
              id="sec-new-pw"
              className="p-input"
              type="password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              autoComplete="new-password"
            />
          </div>
          <div className="p-field">
            <label htmlFor="sec-confirm-pw">{pt(lang, "confirmPassword")}</label>
            <input
              id="sec-confirm-pw"
              className="p-input"
              type="password"
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              autoComplete="new-password"
            />
          </div>
          <button type="submit" className="p-btn" disabled={!canSave}>
            {busy ? pt(lang, "loading") : pt(lang, "save")}
          </button>
        </form>
      </section>
    </div>
  );
}
