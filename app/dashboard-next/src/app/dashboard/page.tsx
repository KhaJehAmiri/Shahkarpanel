"use client";

import dynamic from "next/dynamic";

const DashboardClient = dynamic(
  () => import("./DashboardClient"),
  { ssr: false, loading: () => (
    <div className="sk-splash">
      <img
        src="/sub-assets/brand/shahkar.png"
        alt=""
        className="sk-splash-logo"
      />
    </div>
  ) },
);

export default function DashboardPage() {
  return <DashboardClient />;
}
