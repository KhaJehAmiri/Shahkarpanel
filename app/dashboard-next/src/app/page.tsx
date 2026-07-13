"use client";

import Link from "next/link";
import "./public-pages.css";

/** Root landing — shown when Next static `/` is mounted; FastAPI also serves templates/home. */
export default function Home() {
  return (
    <div className="nx-public-page">
      <div className="nx-public-plane" aria-hidden>
        <div className="nx-public-orbits">
          <svg viewBox="0 0 640 640" fill="none">
            <circle cx="320" cy="320" r="210" stroke="rgba(46,224,196,0.18)" strokeWidth="1.2" />
            <circle className="nx-ring-slow" cx="320" cy="320" r="278" stroke="rgba(46,224,196,0.1)" strokeWidth="1" strokeDasharray="6 14" />
            <circle cx="320" cy="320" r="146" stroke="rgba(46,224,196,0.22)" strokeWidth="1.4" />
            <circle cx="320" cy="110" r="5" fill="#2ee0c4" opacity="0.9" />
            <circle cx="510" cy="360" r="4" fill="#2ee0c4" opacity="0.65" />
            <circle cx="180" cy="470" r="3.5" fill="#2ee0c4" opacity="0.5" />
            <path d="M320 110 L510 360 L180 470 Z" stroke="rgba(46,224,196,0.2)" strokeWidth="1" />
            <circle cx="320" cy="320" r="10" fill="rgba(46,224,196,0.15)" stroke="#2ee0c4" strokeWidth="1.5" />
          </svg>
        </div>
      </div>

      <main className="nx-public-hero">
        <svg className="nx-public-mark" viewBox="0 0 42 42" fill="none" aria-hidden>
          <circle cx="21" cy="21" r="18" stroke="currentColor" strokeWidth="1.5" opacity="0.35" />
          <circle cx="21" cy="21" r="9" stroke="currentColor" strokeWidth="2" />
          <circle cx="21" cy="21" r="3" fill="currentColor" />
        </svg>

        <h1 className="nx-public-brand">
          Nexus<span>Panel</span>
        </h1>
        <p className="nx-public-headline">The control plane for modern VPN fleets.</p>
        <p className="nx-public-desc">Multi-tenant. White-label. Xray at the core.</p>

        <div className="nx-public-cta">
          <Link href="/portal/" className="nx-public-btn">
            Open portal
            <svg viewBox="0 0 16 16" fill="none" aria-hidden>
              <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </Link>
          <Link href="/subscribe/" className="nx-public-ghost">
            Subscription
          </Link>
        </div>
      </main>

      <p className="nx-public-foot">Admin dashboard access is provided by your operator.</p>
    </div>
  );
}
