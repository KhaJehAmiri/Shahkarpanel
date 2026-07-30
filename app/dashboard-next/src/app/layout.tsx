import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Shahkar",
  description: "Shahkar — professional proxy management",
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
    icon: [
      { url: "/brand/favicon.ico", sizes: "any" },
      { url: "/brand/pwa-192.png", type: "image/png", sizes: "192x192" },
      { url: "/brand/pwa-512.png", type: "image/png", sizes: "512x512" },
    ],
    apple: { url: "/brand/apple-touch-icon.png", sizes: "180x180" },
    shortcut: "/brand/favicon.ico",
  },
};

// Set <html lang/dir> from the persisted language before paint so non-Persian
// users don't get a flash of RTL. Mirrors applyDir() in panel/i18n.ts.
const LANG_BOOTSTRAP = `(function(){try{
  var s=localStorage.getItem('nx_lang');
  var nav=(navigator.language||'').slice(0,2);
  var lang=(['en','fa','ru','zh'].indexOf(s)>=0)?s:((['en','fa','ru','zh'].indexOf(nav)>=0)?nav:'en');
  var dir=lang==='fa'?'rtl':'ltr';
  document.documentElement.setAttribute('lang',lang);
  document.documentElement.setAttribute('dir',dir);
  var standalone = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
    || (window.navigator && window.navigator.standalone === true);
  if (standalone) document.documentElement.classList.add('sk-standalone');
}catch(e){}})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fa" dir="rtl">
      <head>
        <script dangerouslySetInnerHTML={{ __html: LANG_BOOTSTRAP }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
