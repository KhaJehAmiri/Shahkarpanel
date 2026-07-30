"use client";

import { useEffect } from "react";
import { detectPortalLang, pt } from "@/lib/portal-i18n";
import { PortalProvider, usePortal } from "./PortalContext";
import { LoginScreen } from "./components/LoginScreen";
import { InstallGate } from "./components/InstallBanner";
import { Shell, Toast } from "./components/Shell";
import { AccountsView } from "./views/AccountsView";
import { HistoryView } from "./views/HistoryView";
import { HomeView } from "./views/HomeView";
import { SecurityView } from "./views/SecurityView";
import { SetupCredentialsView } from "./views/SetupCredentialsView";
import { ShopView } from "./views/ShopView";
import { bootPortalPwa, bindInstallPromptCapture } from "./lib/portalPwa";
import type { TabId } from "./types";

if (typeof window !== "undefined") {
  bindInstallPromptCapture();
}

function PortalBody() {
  const { authed, bootstrapping, tab, setTab, lang, mustChangeCredentials } = usePortal();

  useEffect(() => {
    if (tab === "configs") setTab("accounts");
  }, [tab, setTab]);

  useEffect(() => {
    const cleanup = bootPortalPwa({ requestPush: authed });
    const onTab = (e: Event) => {
      const id = (e as CustomEvent).detail as TabId;
      if (id) setTab(id);
    };
    window.addEventListener("sk-portal-tab", onTab as EventListener);
    return () => {
      cleanup?.();
      window.removeEventListener("sk-portal-tab", onTab as EventListener);
    };
  }, [authed, setTab]);

  if (bootstrapping) {
    return (
      <div className="p-login">
        <p className="p-muted">{pt(lang, "loading")}</p>
      </div>
    );
  }

  return (
    <>
      <InstallGate />
      <div className="p-frame">
        {!authed ? (
          <>
            <LoginScreen />
            <Toast />
          </>
        ) : mustChangeCredentials ? (
          <>
            <SetupCredentialsView />
            <Toast />
          </>
        ) : (
          <>
            <Shell>
              {tab === "home" ? <HomeView /> : null}
              {tab === "accounts" || tab === "configs" ? <AccountsView /> : null}
              {tab === "shop" ? <ShopView /> : null}
              {tab === "security" ? <SecurityView /> : null}
              {tab === "history" ? <HistoryView /> : null}
            </Shell>
            <Toast />
          </>
        )}
      </div>
    </>
  );
}

export function PortalApp() {
  return (
    <PortalProvider>
      <PortalBody />
    </PortalProvider>
  );
}

export function PortalFallback() {
  const lang = detectPortalLang();
  return <div className="p-login">{pt(lang, "loading")}</div>;
}
