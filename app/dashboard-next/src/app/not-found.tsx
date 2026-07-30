"use client";

import Link from "next/link";
import "./public-pages.css";

export default function NotFound() {
  return (
    <div className="sk-public-page">
      <div className="sk-public-plane" aria-hidden />
      <main className="sk-public-wrap">
        <div className="sk-404-code">404</div>
        <h1 className="sk-public-title">Page not found</h1>
        <p className="sk-public-desc">
          The path you requested doesn&apos;t exist or has been moved.
        </p>
        <div className="sk-public-cta">
          <Link href="/" className="sk-public-btn">
            Back to home
            <svg viewBox="0 0 16 16" fill="none" aria-hidden>
              <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </Link>
        </div>
        <p className="sk-public-foot" style={{ padding: 0, marginTop: 40 }}>Shahkar</p>
      </main>
    </div>
  );
}
