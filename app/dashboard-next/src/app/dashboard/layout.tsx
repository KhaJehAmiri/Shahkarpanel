import type { Metadata } from "next";
import "@/panel/index.css";
import "@/panel/design-pro.css";

export const metadata: Metadata = {
  title: "NexusPanel",
  description: "NexusPanel — professional proxy management",
};

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return children;
}
