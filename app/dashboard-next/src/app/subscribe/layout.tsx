"use client";

import { useEffect } from "react";
import { initSubTheme } from "@/lib/sub-theme";
import "./subscribe.css";

export default function SubscribeLayout({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    initSubTheme();
  }, []);
  return <div className="sub-theme">{children}</div>;
}
