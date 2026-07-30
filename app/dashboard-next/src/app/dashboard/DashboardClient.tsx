"use client";

import { useEffect } from "react";
import { AppProvider } from "@/panel/context/AppContext";
import { ToastProvider } from "@/panel/components/ui";
import { CopilotProvider } from "@/panel/copilot/CopilotContext";
import DashboardRoot from "@/panel/DashboardRoot";

/** Register SW ASAP so Chromium treats this origin as an installable app. */
function PwaBoot() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const secure =
      window.isSecureContext ||
      location.protocol === "https:" ||
      location.hostname === "localhost";
    if (!secure) return;
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => undefined);

    const applyStandalone = () => {
      const standalone =
        window.matchMedia("(display-mode: standalone)").matches ||
        (navigator as any).standalone === true;
      document.documentElement.classList.toggle("sk-standalone", standalone);
    };
    applyStandalone();
    const mq = window.matchMedia("(display-mode: standalone)");
    mq.addEventListener?.("change", applyStandalone);
    return () => mq.removeEventListener?.("change", applyStandalone);
  }, []);
  return null;
}

export default function DashboardClient() {
  return (
    <AppProvider>
      <ToastProvider>
        <CopilotProvider>
          <PwaBoot />
          <DashboardRoot />
        </CopilotProvider>
      </ToastProvider>
    </AppProvider>
  );
}
