import type { Metadata, Viewport } from "next";
import "@/panel/index.css";
import "@/panel/design-pro.css";

export const metadata: Metadata = {
  title: "Shahkar Panel",
  description: "پنل نمایندگان و مدیریت شاهکار",
  applicationName: "Shahkar Panel",
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
      { url: "/brand/favicon.ico?v=3", sizes: "any" },
      { url: "/brand/pwa-192.png?v=3", type: "image/png", sizes: "192x192" },
      { url: "/brand/pwa-512.png?v=3", type: "image/png", sizes: "512x512" },
    ],
    apple: { url: "/brand/apple-touch-icon.png?v=3", sizes: "180x180" },
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
  const earlyInstall = `(function(){try{
  var ua=navigator.userAgent||'';
  var mobile=/Android|iPhone|iPad|iPod|Windows Phone|IEMobile/i.test(ua)
    ||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
  if(window.matchMedia&&window.matchMedia('(display-mode: standalone)').matches)document.documentElement.classList.add('sk-standalone');
  if(window.navigator&&window.navigator.standalone===true)document.documentElement.classList.add('sk-standalone');
  if(!mobile)return;
  if(window.matchMedia&&window.matchMedia('(display-mode: standalone)').matches)return;
  if(window.navigator&&window.navigator.standalone===true)return;
  window.addEventListener('beforeinstallprompt',function(e){
    e.preventDefault();
    window.__nxPanelBip=e;
    try{window.dispatchEvent(new CustomEvent('sk-panel-install-ready'));}catch(_){}
  });
}catch(e){}})();`;

  return (
    <>
      <link rel="manifest" href="/manifest.webmanifest" />
      <meta name="mobile-web-app-capable" content="yes" />
      <meta name="apple-mobile-web-app-capable" content="yes" />
      <meta name="apple-mobile-web-app-title" content="Shahkar" />
      <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
      <script dangerouslySetInnerHTML={{ __html: earlyInstall }} />
      {children}
    </>
  );
}
