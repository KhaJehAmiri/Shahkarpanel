import type { Metadata } from "next";
import "./landing.css";

export const metadata: Metadata = {
  title: "شاهکار — اینترنت بدون قطعی",
  description:
    "سرویس پرمیوم پروکسی و VPN مبتنی بر Xray. چند پروتکل، مانیتورینگ دائمی، راه‌اندازی ساده. شروع رایگان.",
  openGraph: {
    title: "شاهکار — اینترنت بدون قطعی",
    description:
      "زیرساخت سازمانی روی Xray؛ تجربهٔ ساده برای همه. وصل در کمتر از یک دقیقه.",
    locale: "fa_IR",
    alternateLocale: ["en_US"],
    type: "website",
    siteName: "Shahkar",
    url: "/landing/",
  },
  twitter: {
    card: "summary_large_image",
    title: "شاهکار — اینترنت بدون قطعی",
    description: "زیرساخت سازمانی روی Xray؛ تجربهٔ ساده برای همه.",
  },
  robots: { index: true, follow: true },
};

export default function LandingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
