import type { Metadata, Viewport } from "next";
import "@/panel/index.css";
import "@/panel/design-pro.css";

export const metadata: Metadata = {
  title: "Shahkar",
  description: "Shahkar — professional proxy management",
  applicationName: "Shahkar",
  // Do NOT set metadata.manifest — Next adds crossorigin=use-credentials which
  // breaks Chromium PWA install (opens as normal browser tab instead of app).
  appleWebApp: {
    capable: true,
    title: "Shahkar",
    statusBarStyle: "black-translucent",
  },
  formatDetection: {
    telephone: false,
  },
  other: {
    "mobile-web-app-capable": "yes",
  },
  icons: {
    icon: [
      { url: "/brand/favicon.ico", sizes: "any" },
      { url: "/brand/pwa-192.png", type: "image/png", sizes: "192x192" },
      { url: "/brand/pwa-512.png", type: "image/png", sizes: "512x512" },
    ],
    apple: { url: "/brand/apple-touch-icon.png", sizes: "180x180" },
  },
};

export const viewport: Viewport = {
  themeColor: "#0b1220",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
};

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <link rel="manifest" href="/manifest.webmanifest" />
      {children}
    </>
  );
}
