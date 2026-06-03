"use client";

import { AppProvider } from "@/panel/context/AppContext";
import { ToastProvider } from "@/panel/components/ui";
import DashboardRoot from "@/panel/DashboardRoot";

export default function DashboardClient() {
  return (
    <AppProvider>
      <ToastProvider>
        <DashboardRoot />
      </ToastProvider>
    </AppProvider>
  );
}
