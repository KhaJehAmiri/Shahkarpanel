"use client";

import {
  CTA_DEMO_HREF,
  CTA_PRIMARY_HREF,
  type LandingCopy,
} from "./i18n";
import { DashboardMock } from "./mockups";

export function Hero({ t }: { t: LandingCopy }) {
  return (
    <section className="tg-hero" data-hero aria-labelledby="tg-hero-title">
      <div className="tg-hero-glow" aria-hidden />
      <div className="tg-hero-line" aria-hidden />
      <div className="tg-hero-dot" aria-hidden />

      <div className="tg-wrap tg-hero-copy">
        <h1 id="tg-hero-title" data-hero-el>
          {t.hero.headline}
        </h1>
        <p className="tg-lead" data-hero-el>
          {t.hero.subhead}
        </p>
        <div className="tg-hero-ctas" data-hero-el>
          <a href={CTA_PRIMARY_HREF} className="tg-btn tg-btn-primary">
            {t.hero.primaryCta}
          </a>
          <a href={CTA_DEMO_HREF} className="tg-btn tg-btn-text">
            {t.hero.secondaryCta}
          </a>
        </div>
      </div>

      <div className="tg-wrap tg-mock-wrap" data-hero-el>
        <div className="tg-mock-glow" aria-hidden />
        <DashboardMock priority />
      </div>
    </section>
  );
}
