"use client";

import { Suspense } from "react";
import { PortalApp, PortalFallback } from "@/portal/PortalApp";

export default function PortalPage() {
  return (
    <Suspense fallback={<PortalFallback />}>
      <PortalApp />
    </Suspense>
  );
}
