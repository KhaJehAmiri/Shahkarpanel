"use client";

import Link from "next/link";
import "./public-pages.css";

/** Root landing — shown when Next static `/` is mounted; FastAPI also serves templates/home. */
export default function Home() {
  return (
    <div className="nx-public-page">
      <div className="nx-public-bg" aria-hidden />
      <main className="nx-public-wrap">
        <svg className="nx-public-mascot nx-mascot-float" viewBox="0 0 320 360" fill="none" aria-hidden>
          <defs>
            <linearGradient id="bodyGrad" x1="60" y1="80" x2="260" y2="320" gradientUnits="userSpaceOnUse">
              <stop stopColor="#1a2234" /><stop offset="1" stopColor="#0d1118" />
            </linearGradient>
            <linearGradient id="accentGrad" x1="0" y1="0" x2="1" y2="1">
              <stop stopColor="#5b8cff" /><stop offset="1" stopColor="#7c5cff" />
            </linearGradient>
            <filter id="glow"><feGaussianBlur stdDeviation="4" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          </defs>
          <line x1="160" y1="48" x2="160" y2="78" stroke="url(#accentGrad)" strokeWidth="3" strokeLinecap="round" />
          <circle cx="160" cy="40" r="8" fill="#5b8cff" filter="url(#glow)" />
          <rect x="95" y="78" width="130" height="110" rx="28" fill="url(#bodyGrad)" stroke="url(#accentGrad)" strokeWidth="2.5" />
          <rect x="110" y="108" width="100" height="44" rx="14" fill="#07090f" stroke="rgba(91,140,255,0.4)" strokeWidth="1.5" />
          <ellipse cx="135" cy="130" rx="10" ry="12" fill="#5b8cff" filter="url(#glow)" />
          <ellipse cx="185" cy="130" rx="10" ry="12" fill="#7c5cff" filter="url(#glow)" />
          <path d="M130 158 Q160 172 190 158" stroke="#5b8cff" strokeWidth="2.5" strokeLinecap="round" fill="none" opacity="0.7" />
          <path d="M75 200 Q160 185 245 200 L260 290 Q160 310 60 290 Z" fill="url(#bodyGrad)" stroke="url(#accentGrad)" strokeWidth="2.5" />
          <circle cx="160" cy="248" r="32" fill="url(#accentGrad)" filter="url(#glow)" />
          <text x="160" y="258" textAnchor="middle" fill="white" fontSize="32" fontWeight="800" fontFamily="system-ui,sans-serif">N</text>
          <path d="M75 210 Q40 230 35 270" stroke="url(#accentGrad)" strokeWidth="10" strokeLinecap="round" fill="none" />
          <path d="M245 210 Q280 230 285 270" stroke="url(#accentGrad)" strokeWidth="10" strokeLinecap="round" fill="none" />
          <circle cx="35" cy="275" r="12" fill="#1a2234" stroke="#5b8cff" strokeWidth="2" />
          <circle cx="285" cy="275" r="12" fill="#1a2234" stroke="#7c5cff" strokeWidth="2" />
          <ellipse cx="160" cy="352" rx="70" ry="8" fill="rgba(91,140,255,0.15)" />
        </svg>

        <h1 className="nx-public-brand">NexusPanel</h1>
        <p className="nx-public-desc">
          Professional VPN Control Plane — multi-tenant, white-label, Xray-powered.
        </p>

        <div className="nx-public-cards">
          <Link href="/portal/" className="nx-public-card">
            <div className="nx-public-card-ico">👤</div>
            <div><b>User Portal</b><small>Manage subscription &amp; account</small></div>
          </Link>
          <Link href="/subscribe/" className="nx-public-card">
            <div className="nx-public-card-ico">🔗</div>
            <div><b>Subscription</b><small>Personal VPN profile page</small></div>
          </Link>
        </div>

        <p className="nx-public-foot">Admin dashboard access is provided by your operator.</p>
      </main>
    </div>
  );
}
