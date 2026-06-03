"use client";

import dynamic from "next/dynamic";

const DashboardClient = dynamic(
  () => import("./DashboardClient"),
  { ssr: false, loading: () => (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
      <div className="nx-brand-logo" style={{ width: 48, height: 48, fontSize: 22 }}>N</div>
    </div>
  ) },
);

export default function DashboardPage() {
  return <DashboardClient />;
}
