import type { Metadata, Viewport } from "next";
import "./portal.css";

export const metadata: Metadata = {
  title: "Shahkar",
  description: "خرید، تمدید و دریافت کانفیگ",
  applicationName: "Shahkar",
  appleWebApp: {
    capable: true,
    title: "Shahkar",
    statusBarStyle: "black-translucent",
  },
  other: {
    "mobile-web-app-capable": "yes",
  },
  icons: {
    icon: [{ url: "/brand/pwa-192.png", type: "image/png", sizes: "192x192" }],
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

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  const earlyInstall = `(function(){try{
  var ua=navigator.userAgent||'';
  var mobile=/Android|iPhone|iPad|iPod|Windows Phone|IEMobile/i.test(ua)
    ||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
  document.documentElement.classList.add('p-portal-lock');
  if(document.body)document.body.classList.add('p-portal-lock');
  else document.addEventListener('DOMContentLoaded',function(){document.body&&document.body.classList.add('p-portal-lock');});
  if(window.matchMedia&&window.matchMedia('(display-mode: standalone)').matches)document.documentElement.classList.add('p-standalone');
  if(window.navigator&&window.navigator.standalone===true)document.documentElement.classList.add('p-standalone');
  if(!mobile)return;
  if(window.matchMedia&&window.matchMedia('(display-mode: standalone)').matches)return;
  if(window.navigator&&window.navigator.standalone===true)return;
  window.addEventListener('beforeinstallprompt',function(e){
    e.preventDefault();
    window.__nxPortalBip=e;
    try{window.dispatchEvent(new CustomEvent('sk-portal-install-ready'));}catch(_){}
  });
}catch(e){}})();`;

  return (
    <>
      <link rel="manifest" href="/portal/manifest.webmanifest" />
      <meta name="mobile-web-app-capable" content="yes" />
      <link
        rel="preload"
        href="/fonts/Vazirmatn-400.woff2"
        as="font"
        type="font/woff2"
        crossOrigin="anonymous"
      />
      <link
        rel="preload"
        href="/fonts/Vazirmatn-700.woff2"
        as="font"
        type="font/woff2"
        crossOrigin="anonymous"
      />
      <script dangerouslySetInnerHTML={{ __html: earlyInstall }} />
      <div className="portal-theme p-app-shell">{children}</div>
    </>
  );
}
