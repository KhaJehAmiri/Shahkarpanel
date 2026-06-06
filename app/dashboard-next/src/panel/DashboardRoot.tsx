"use client";

import { FC } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { useApp } from "./context/AppContext";
import { Shell } from "./components/Shell";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { Users } from "./pages/Users";
import { Inbounds } from "./pages/Inbounds";
import { Infrastructure } from "./pages/Infrastructure";
import { Nodes } from "./pages/Nodes";
import { TunnelsPage } from "./pages/TunnelsPage";
import { WireGuard } from "./pages/WireGuard";
import { XrayConfig } from "./pages/XrayConfig";
import { Hosts } from "./pages/Hosts";
import { Resellers } from "./pages/Resellers";
import { Automation } from "./pages/Automation";
import { Analytics } from "./pages/Analytics";
import { Billing } from "./pages/Billing";
import { System } from "./pages/System";
import { SetupWizard } from "./components/SetupWizard";
import "./i18n";

const Splash: FC = () => (
  <div style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
    <div
      className="nx-brand-logo"
      style={{ width: 48, height: 48, fontSize: 22, animation: "nx-shimmer 1.3s infinite" }}
    >
      N
    </div>
  </div>
);

export default function DashboardRoot() {
  const { admin, loadingAuth } = useApp();

  if (loadingAuth) return <Splash />;
  if (!admin) return <Login />;

  return (
    <>
      <SetupWizard />
      <HashRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Navigate to="/overview" replace />} />
          <Route path="/overview" element={<Overview />} />
          <Route path="/inbounds" element={<Inbounds />} />
          <Route path="/users" element={<Users />} />
          <Route path="/nodes" element={<Nodes />} />
          <Route path="/tunnels" element={<TunnelsPage />} />
          <Route path="/wireguard" element={<WireGuard />} />
          <Route path="/xray" element={<XrayConfig />} />
          <Route path="/hosts" element={<Hosts />} />
          <Route path="/infrastructure" element={<Infrastructure />} />
          <Route path="/resellers" element={<Resellers />} />
          <Route path="/automation" element={<Automation />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/billing" element={<Billing />} />
          <Route path="/system" element={<System />} />
          <Route path="*" element={<Navigate to="/overview" replace />} />
        </Route>
      </Routes>
    </HashRouter>
    </>
  );
}
