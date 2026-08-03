import { LandingApp } from "@/components/landing/LandingApp";

const jsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      name: "شاهکار",
      alternateName: "Shahkar",
      url: "/landing/",
      description:
        "سرویس پرمیوم مدیریت پروکسی و VPN مبتنی بر Xray با چند پروتکل و مانیتورینگ دائمی.",
    },
    {
      "@type": "SoftwareApplication",
      name: "شاهکار",
      applicationCategory: "NetworkingApplication",
      operatingSystem: "Windows, macOS, Linux, iOS, Android",
      description:
        "اتصال پایدار با چند پروتکل (VLESS/Reality، VMess، Shadowsocks، Trojan، WireGuard) و راه‌اندازی یک‌کلیکی.",
      offers: {
        "@type": "Offer",
        price: "0",
        priceCurrency: "IRR",
        description: "شروع رایگان",
      },
    },
  ],
};

export default function LandingPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <LandingApp />
    </>
  );
}
