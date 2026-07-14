"use client";

import dynamic from "next/dynamic";

const DashboardClient = dynamic(
  () => import("./DashboardClient"),
  { ssr: false, loading: () => (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
      <img
        src="/sub-assets/brand/nexuspanel-logo.png"
        alt=""
        className="nx-brand-logo nx-brand-logo-img"
        style={{ width: 48, height: 48 }}
      />
    </div>
  ) },
);

export default function DashboardPage() {
  return <DashboardClient />;
}
