"use client";

import { FC } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { useApp } from "./context/AppContext";
import { Shell } from "./components/Shell";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { Users } from "./pages/Users";
import { ServersHub } from "./pages/ServersHub";
import { ConnectionHub } from "./pages/ConnectionHub";
import { BusinessHub } from "./pages/BusinessHub";
import { Billing } from "./pages/Billing";
import { Resellers } from "./pages/Resellers";
import { System } from "./pages/System";
import { SetupWizard } from "./components/SetupWizard";
import { ResellerOnboardingWizard } from "./components/ResellerOnboardingWizard";
import "./i18n";

const Splash: FC = () => (
  <div className="sk-splash">
    <img
      src="/sub-assets/brand/shahkar.png"
      alt=""
      className="sk-splash-logo"
    />
  </div>
);

const LegacyRedirect: FC<{ to: string }> = ({ to }) => <Navigate to={to} replace />;

export default function DashboardRoot() {
  const { admin, loadingAuth } = useApp();

  if (loadingAuth) return <Splash />;
  if (!admin) return <Login />;

  return (
    <HashRouter>
      <SetupWizard />
      <ResellerOnboardingWizard />
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Navigate to="/overview" replace />} />
          <Route path="/overview" element={<Overview />} />
          <Route path="/users" element={<Users />} />
          <Route path="/servers" element={<ServersHub />} />
          <Route path="/connection" element={<ConnectionHub />} />
          <Route path="/billing" element={<Billing />} />
          <Route path="/resellers" element={<Resellers />} />
          <Route path="/business" element={<BusinessHub />} />
          <Route path="/system" element={<System />} />

          {/* Legacy URLs → hubs */}
          <Route path="/nodes" element={<LegacyRedirect to="/servers?tab=nodes" />} />
          <Route path="/wireguard" element={<LegacyRedirect to="/servers?tab=wireguard" />} />
          <Route path="/singbox" element={<LegacyRedirect to="/servers?tab=h2" />} />
          <Route path="/tunnels" element={<LegacyRedirect to="/servers?tab=tunnels" />} />
          <Route path="/dedicated-ip" element={<LegacyRedirect to="/servers?tab=dedip" />} />
          <Route path="/inbounds" element={<LegacyRedirect to="/connection?tab=inbounds" />} />
          <Route path="/hosts" element={<LegacyRedirect to="/connection?tab=hosts" />} />
          <Route path="/xray" element={<LegacyRedirect to="/connection?tab=advanced" />} />
          <Route path="/analytics" element={<LegacyRedirect to="/business?tab=analytics" />} />
          <Route path="/automation" element={<LegacyRedirect to="/business?tab=automation" />} />
          <Route path="/infrastructure" element={<LegacyRedirect to="/servers?tab=nodes" />} />

          <Route path="*" element={<Navigate to="/overview" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
