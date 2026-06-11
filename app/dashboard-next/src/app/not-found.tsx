"use client";

import Link from "next/link";
import "./public-pages.css";

export default function NotFound() {
  return (
    <div className="nx-public-page">
      <div className="nx-public-bg" aria-hidden />
      <main className="nx-public-wrap">
        <div className="nx-404-code">404</div>
        <svg className="nx-public-mascot nx-mascot-lost" viewBox="0 0 200 200" fill="none" aria-hidden>
          <defs>
            <linearGradient id="g404" x1="0" y1="0" x2="1" y2="1">
              <stop stopColor="#5b8cff" />
              <stop offset="1" stopColor="#7c5cff" />
            </linearGradient>
          </defs>
          <rect x="45" y="50" width="110" height="90" rx="24" fill="#1a2234" stroke="url(#g404)" strokeWidth="2" />
          <rect x="60" y="72" width="80" height="32" rx="10" fill="#07090f" />
          <circle cx="85" cy="88" r="8" fill="#ff6b6b" />
          <circle cx="115" cy="88" r="8" fill="#ff6b6b" />
          <path d="M75 108 Q100 95 125 108" stroke="#ff6b6b" strokeWidth="2.5" strokeLinecap="round" fill="none" />
          <path d="M30 120 Q15 140 20 165" stroke="url(#g404)" strokeWidth="6" strokeLinecap="round" fill="none" />
          <path d="M170 120 Q185 140 180 165" stroke="url(#g404)" strokeWidth="6" strokeLinecap="round" fill="none" />
        </svg>
        <h1 className="nx-public-title">Page not found</h1>
        <p className="nx-public-desc">
          The path you requested doesn&apos;t exist or has been moved.
        </p>
        <Link href="/" className="nx-public-btn">← Back to home</Link>
        <p className="nx-public-foot">NexusPanel</p>
      </main>
    </div>
  );
}
