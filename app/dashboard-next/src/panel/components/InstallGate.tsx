"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { brandLogoUrl, brandingTitle } from "../lib/branding";
import { useApp } from "../context/AppContext";
import { IcDownload, IcShare } from "./icons";
import {
  canShowInstallHint,
  dismissInstallHint,
  hasNativeInstallPrompt,
  isIos,
  isMobileDevice,
  isStandalone,
  promptPanelInstall,
} from "../lib/panelPwa";

/**
 * Mobile install gate for the reseller/admin panel.
 * Android: native Install App dialog. iOS: Add to Home Screen steps.
 */
export function InstallGate() {
  const { t } = useTranslation();
  const { branding } = useApp();
  const [open, setOpen] = useState(false);
  const [ios, setIos] = useState(false);
  const [canNative, setCanNative] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    if (!isMobileDevice() || isStandalone()) {
      setOpen(false);
      return;
    }
    setIos(isIos());
    setCanNative(hasNativeInstallPrompt());
    setOpen(canShowInstallHint());
  }, []);

  useEffect(() => {
    if (!isMobileDevice() || isStandalone()) {
      setOpen(false);
      return;
    }
    refresh();
    const onReady = () => {
      if (!isMobileDevice()) return;
      setCanNative(true);
      if (canShowInstallHint() && !isStandalone()) setOpen(true);
    };
    const onInstalled = () => setOpen(false);
    const onDismissed = () => setOpen(false);
    window.addEventListener("sk-panel-install-ready", onReady);
    window.addEventListener("sk-panel-installed", onInstalled);
    window.addEventListener("sk-panel-install-dismissed", onDismissed);
    return () => {
      window.removeEventListener("sk-panel-install-ready", onReady);
      window.removeEventListener("sk-panel-installed", onInstalled);
      window.removeEventListener("sk-panel-install-dismissed", onDismissed);
    };
  }, [refresh]);

  const onInstall = async () => {
    setBusy(true);
    try {
      const result = await promptPanelInstall();
      if (result === "accepted") {
        setOpen(false);
        return;
      }
    } finally {
      setBusy(false);
      setCanNative(hasNativeInstallPrompt());
    }
  };

  const onLater = () => {
    dismissInstallHint();
    setOpen(false);
  };

  if (!open) return null;

  const name = brandingTitle(branding, t("common.appName"));
  const logo = brandLogoUrl(branding);

  return (
    <div
      className="sk-install-gate"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sk-install-title"
    >
      <div className="sk-install-sheet">
        <div className="sk-install-sheet-icon" aria-hidden>
          <img src={logo} alt="" width={48} height={48} />
        </div>
        <h2 id="sk-install-title">{t("pwa.installTitle")}</h2>
        <p className="sk-install-sheet-lead">{t("pwa.installLead", { name })}</p>

        {ios ? (
          <ol className="sk-install-steps">
            <li>
              {t("pwa.installIosStep1")} <IcShare size={14} className="sk-install-share" />
            </li>
            <li>{t("pwa.installIosStep2")}</li>
            <li>{t("pwa.installIosStep3")}</li>
          </ol>
        ) : (
          <p className="sk-install-sheet-hint">
            {canNative ? t("pwa.installNativeHint") : t("pwa.installAndroid")}
          </p>
        )}

        <div className="sk-install-sheet-actions">
          {!ios ? (
            <button type="button" className="sk-btn primary" disabled={busy} onClick={() => void onInstall()}>
              <IcDownload size={18} />
              {busy ? t("common.loading") : t("pwa.installNow")}
            </button>
          ) : null}
          <button type="button" className="sk-btn ghost" onClick={onLater}>
            {t("pwa.installLater")}
          </button>
        </div>
      </div>
    </div>
  );
}
