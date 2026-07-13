"use client";

import Link from "next/link";
import "./public-pages.css";

export default function NotFound() {
  return (
    <div className="nx-public-page">
      <div className="nx-public-plane" aria-hidden />
      <main className="nx-public-wrap">
        <div className="nx-404-code">404</div>
        <h1 className="nx-public-title">Page not found</h1>
        <p className="nx-public-desc">
          The path you requested doesn&apos;t exist or has been moved.
        </p>
        <div className="nx-public-cta">
          <Link href="/" className="nx-public-btn">
            Back to home
            <svg viewBox="0 0 16 16" fill="none" aria-hidden>
              <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </Link>
        </div>
        <p className="nx-public-foot" style={{ padding: 0, marginTop: 40 }}>NexusPanel</p>
      </main>
    </div>
  );
}
