import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NexusPanel",
  description: "NexusPanel — professional proxy management",
  icons: {
    icon: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><circle cx='12' cy='12' r='10' fill='%232ee0c4'/></svg>",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fa" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
