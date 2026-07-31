"use client";

import { useEffect } from "react";
import { AppProvider } from "@/panel/context/AppContext";
import { ToastProvider } from "@/panel/components/ui";
import { CopilotProvider } from "@/panel/copilot/CopilotContext";
import { InstallGate } from "@/panel/components/InstallGate";
import { bootPanelPwa } from "@/panel/lib/panelPwa";
import DashboardRoot from "@/panel/DashboardRoot";

/** Register SW + capture install prompt so the panel is installable on phones. */
function PwaBoot() {
  useEffect(() => bootPanelPwa(), []);
  return null;
}

export default function DashboardClient() {
  return (
    <AppProvider>
      <ToastProvider>
        <CopilotProvider>
          <PwaBoot />
          <InstallGate />
          <DashboardRoot />
        </CopilotProvider>
      </ToastProvider>
    </AppProvider>
  );
}
