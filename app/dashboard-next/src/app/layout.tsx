import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NexusPanel",
  description: "NexusPanel — professional proxy management",
  icons: {
    icon: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><circle cx='12' cy='12' r='10' fill='%232ee0c4'/></svg>",
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
