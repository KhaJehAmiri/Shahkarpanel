import type { Metadata } from "next";
import "@/panel/index.css";

export const metadata: Metadata = {
  title: "NexusPanel",
  description: "NexusPanel — professional proxy management",
};

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return children;
}
