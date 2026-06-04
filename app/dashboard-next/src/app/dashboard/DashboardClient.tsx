"use client";

import { AppProvider } from "@/panel/context/AppContext";
import { ToastProvider } from "@/panel/components/ui";
import { CopilotProvider } from "@/panel/copilot/CopilotContext";
import DashboardRoot from "@/panel/DashboardRoot";

export default function DashboardClient() {
  return (
    <AppProvider>
      <ToastProvider>
        <CopilotProvider>
          <DashboardRoot />
        </CopilotProvider>
      </ToastProvider>
    </AppProvider>
  );
}
