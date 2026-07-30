"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, Share } from "lucide-react";
import { pt } from "@/lib/portal-i18n";
import { usePortal } from "../PortalContext";
import {
  canShowInstallHint,
  dismissInstallHint,
  hasNativeInstallPrompt,
  isIos,
  isMobileDevice,
  isStandalone,
  promptPortalInstall,
} from "../lib/portalPwa";

/**
 * Default install gate: shown when entering the portal until installed / skipped this session.
 * On Android Chrome, the Install button opens the system Install App dialog.
 * On iOS Safari there is no system API — clear Add to Home Screen steps are shown.
 */
export function InstallGate() {
  const { lang, rtl, brandTitle, brandLogo } = usePortal();
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
    window.addEventListener("sk-portal-install-ready", onReady);
    window.addEventListener("sk-portal-installed", onInstalled);
    window.addEventListener("sk-portal-install-dismissed", onDismissed);
    return () => {
      window.removeEventListener("sk-portal-install-ready", onReady);
      window.removeEventListener("sk-portal-installed", onInstalled);
      window.removeEventListener("sk-portal-install-dismissed", onDismissed);
    };
  }, [refresh]);

  const onInstall = async () => {
    setBusy(true);
    try {
      const result = await promptPortalInstall();
      if (result === "accepted") {
        setOpen(false);
        return;
      }
      if (result === "dismissed") {
        // User closed the system sheet — keep our gate so they can retry.
        return;
      }
      // No native prompt yet (iOS / desktop Safari / engagement not ready):
      // keep instructions visible; user follows OS steps.
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

  const name = brandTitle || pt(lang, "brand");

  return (
    <div className="p-install-gate" role="dialog" aria-modal="true" aria-labelledby="p-install-title" dir={rtl ? "rtl" : "ltr"}>
      <div className="p-install-sheet">
        <div className="p-install-sheet-icon" aria-hidden>
          <img
            src={brandLogo || "/sub-assets/brand/shahkar.png"}
            alt=""
            className="p-brand-logo"
            style={{ width: 48, height: 48, borderRadius: 12 }}
          />
        </div>
        <h2 id="p-install-title">{pt(lang, "installTitle")}</h2>
        <p className="p-install-sheet-lead">
          {pt(lang, "installLead").replace("{name}", name)}
        </p>

        {ios ? (
          <ol className="p-install-steps">
            <li>
              {pt(lang, "installIosStep1")} <Share size={14} className="p-install-share" aria-hidden />
            </li>
            <li>{pt(lang, "installIosStep2")}</li>
            <li>{pt(lang, "installIosStep3")}</li>
          </ol>
        ) : (
          <p className="p-install-sheet-hint">
            {canNative ? pt(lang, "installNativeHint") : pt(lang, "installAndroid")}
          </p>
        )}

        <div className="p-install-sheet-actions">
          {!ios ? (
            <button
              type="button"
              className="p-btn block"
              disabled={busy}
              onClick={onInstall}
            >
              <Download size={18} aria-hidden />
              {busy ? pt(lang, "loading") : pt(lang, "installNow")}
            </button>
          ) : null}
          <button type="button" className="p-btn ghost block" onClick={onLater}>
            {pt(lang, "installLater")}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Compact strip after login (if user skipped the gate this session, hide). */
export function InstallBanner() {
  const { lang } = usePortal();
  const [show, setShow] = useState(false);
  const [ios, setIos] = useState(false);
  const [canNative, setCanNative] = useState(false);

  useEffect(() => {
    setIos(isIos());
    setCanNative(hasNativeInstallPrompt());
    // Banner only if gate was skipped but still not installed — rare; keep off when session-skipped.
    setShow(false);
    const onReady = () => setCanNative(true);
    window.addEventListener("sk-portal-install-ready", onReady);
    return () => window.removeEventListener("sk-portal-install-ready", onReady);
  }, []);

  if (!show || isStandalone()) return null;

  return (
    <div className="p-install" role="region" aria-label={pt(lang, "installTitle")}>
      <div className="p-install-icon" aria-hidden>
        <Download size={20} />
      </div>
      <div className="p-install-copy">
        <strong>{pt(lang, "installTitle")}</strong>
        <span>
          {ios ? (
            <>
              {pt(lang, "installIos")} <Share size={14} className="p-install-share" aria-hidden />
            </>
          ) : canNative ? (
            pt(lang, "installNativeHint")
          ) : (
            pt(lang, "installAndroid")
          )}
        </span>
      </div>
      {!ios && canNative ? (
        <button
          type="button"
          className="p-btn"
          style={{ flexShrink: 0, padding: "8px 12px", fontSize: "0.8rem" }}
          onClick={() => void promptPortalInstall()}
        >
          {pt(lang, "installNow")}
        </button>
      ) : null}
    </div>
  );
}
