"use client";

import Image from "next/image";
import { ASSETS } from "./assets";
import {
  CTA_DEMO_HREF,
  CTA_PRIMARY_HREF,
  type LandingCopy,
  type LandingLang,
} from "./i18n";
import { FeatureShot, ProtocolBadgeRow } from "./mockups";

function CheckIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M5 12.5l4.2 4.2L19 7.5"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg width="36" height="36" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 3l7 3v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M9 12.2l2 2 4-4.5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function TrustBar({ t }: { t: LandingCopy }) {
  return (
    <section className="tg-trust" id="trust" aria-label={t.trust.label}>
      <div className="tg-wrap" data-rise>
        <p className="tg-trust-label">{t.trust.label}</p>
        <ProtocolBadgeRow t={t} />
      </div>
    </section>
  );
}

export function HowItWorks({ t }: { t: LandingCopy }) {
  return (
    <section className="tg-section tg-how" id="how" aria-labelledby="tg-how-title">
      <div className="tg-wrap">
        <div className="tg-how-icon" data-rise aria-hidden>
          <ShieldIcon />
        </div>
        <div className="tg-diagram" data-rise aria-hidden>
          <div className="tg-node">{t.how.left}</div>
          <div className="tg-wire" />
          <div className="tg-node tg-node-center" title={t.how.center}>
            <CheckIcon />
          </div>
          <div className="tg-wire" />
          <div className="tg-node">{t.how.right}</div>
        </div>
        <div className="tg-how-copy" data-rise>
          <span className="tg-eyebrow">{t.how.eyebrow}</span>
          <h2 className="tg-h2" id="tg-how-title">
            {t.how.title}
          </h2>
          <p className="tg-lead">{t.how.body}</p>
          <a className="tg-link" href="#features">
            {t.how.link}
          </a>
        </div>
      </div>
    </section>
  );
}

export function FeaturePairs({ t }: { t: LandingCopy }) {
  return (
    <section className="tg-section tg-section-alt" id="features">
      <div className="tg-wrap" style={{ display: "grid", gap: "6rem" }}>
        <div className="tg-split" data-rise>
          <FeatureShot src={ASSETS.speed} alt={t.features.left.title} />
          <div className="tg-split-copy">
            <span className="tg-eyebrow">{t.features.left.eyebrow}</span>
            <h2 className="tg-h2">{t.features.left.title}</h2>
            <p className="tg-lead">{t.features.left.body}</p>
            <a className="tg-link" href="#deploy">
              {t.features.left.link}
            </a>
          </div>
        </div>
        <div className="tg-split is-rev" data-rise>
          <div className="tg-split-copy">
            <span className="tg-eyebrow">{t.features.right.eyebrow}</span>
            <h2 className="tg-h2">{t.features.right.title}</h2>
            <p className="tg-lead">{t.features.right.body}</p>
            <a className="tg-link" href="#access">
              {t.features.right.link}
            </a>
          </div>
          <FeatureShot src={ASSETS.monitor} alt={t.features.right.title} />
        </div>
      </div>
    </section>
  );
}

export function Ecosystem({ t }: { t: LandingCopy }) {
  return (
    <section className="tg-section" id="platforms" aria-labelledby="tg-eco-title">
      <div className="tg-wrap">
        <div data-rise style={{ textAlign: "center", marginInline: "auto" }}>
          <span className="tg-eyebrow">{t.ecosystem.eyebrow}</span>
          <h2 className="tg-h2" id="tg-eco-title">
            {t.ecosystem.title}
          </h2>
          <p className="tg-lead" style={{ marginInline: "auto" }}>
            {t.ecosystem.body}
          </p>
        </div>
        <div className="tg-eco-visual" data-rise style={{ marginInline: "auto" }}>
          <FeatureShot src={ASSETS.eco} alt={t.ecosystem.title} ratio="16/9" />
        </div>
        <div className="tg-eco-grid">
          {t.ecosystem.items.slice(0, 3).map((item) => (
            <article className="tg-eco-card" data-rise key={item.title}>
              <div className="tg-eco-icon">{item.title.slice(0, 2)}</div>
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

export function AccessVisual({ t }: { t: LandingCopy }) {
  return (
    <section
      className="tg-section tg-section-alt"
      id="access"
      aria-labelledby="tg-access-title"
    >
      <div className="tg-wrap tg-access-grid">
        <div data-rise>
          <FeatureShot
            src={ASSETS.accessPhone}
            alt={t.access.title}
            ratio="3/4"
          />
        </div>
        <div data-rise>
          <span className="tg-eyebrow">{t.access.eyebrow}</span>
          <h2 className="tg-h2" id="tg-access-title">
            {t.access.title}
          </h2>
          <p className="tg-lead">{t.access.body}</p>
          <ul className="tg-bullet-list">
            {t.access.treeLabels.slice(1).map((label) => (
              <li key={label}>{label}</li>
            ))}
          </ul>
          <a className="tg-link" href={CTA_PRIMARY_HREF}>
            {t.access.link}
          </a>
          <div className="tg-feed" style={{ marginTop: "1.5rem" }}>
            <div className="tg-feed-head">{t.access.feedTitle}</div>
            {t.access.feedItems.map((item) => (
              <div className="tg-feed-row" key={item.device}>
                <span>{item.device}</span>
                <span
                  className={
                    item.status.includes("Offline") || item.status.includes("قطع")
                      ? "tg-off"
                      : "tg-ok"
                  }
                >
                  {item.status}
                </span>
                <em>{item.time}</em>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export function LifestyleGallery({
  t,
  lang,
}: {
  t: LandingCopy;
  lang: LandingLang;
}) {
  const items = [
    {
      src: ASSETS.lifeWork,
      caption: lang === "fa" ? "کار ریموت پایدار" : "Stable remote work",
    },
    {
      src: ASSETS.lifePhone,
      caption: lang === "fa" ? "اتصال امن موبایل" : "Secure mobile link",
    },
    {
      src: ASSETS.lifeDesk,
      caption: lang === "fa" ? "آماده روی میز کار" : "Ready at your desk",
    },
  ];
  return (
    <section className="tg-section" aria-label={t.pillars.items[0]?.title}>
      <div className="tg-wrap">
        <div className="tg-life-grid">
          {items.map((item) => (
            <figure className="tg-life-card" data-rise key={item.src}>
              <div className="tg-life-frame">
                <Image
                  src={item.src}
                  alt={item.caption}
                  width={900}
                  height={675}
                  sizes="(max-width: 768px) 92vw, 360px"
                  className="tg-media-img"
                />
              </div>
              <figcaption>{item.caption}</figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}

export function Deploy({ t }: { t: LandingCopy }) {
  return (
    <section
      className="tg-section tg-section-alt"
      id="deploy"
      aria-labelledby="tg-deploy-title"
    >
      <div className="tg-wrap">
        <div className="tg-deploy-head" data-rise>
          <div>
            <span className="tg-eyebrow">{t.deploy.eyebrow}</span>
            <h2 className="tg-h2" id="tg-deploy-title">
              {t.deploy.title}
            </h2>
            <p className="tg-lead">{t.deploy.body}</p>
          </div>
          <div className="tg-deploy-ctas">
            <a href={CTA_PRIMARY_HREF} className="tg-btn tg-btn-primary">
              {t.deploy.primaryCta}
            </a>
            <a href="#how" className="tg-btn tg-btn-ghost">
              {t.deploy.secondaryCta}
            </a>
          </div>
        </div>
        <div className="tg-deploy-visual" data-rise>
          <FeatureShot src={ASSETS.deploy} alt={t.deploy.title} ratio="16/9" />
        </div>
        <div className="tg-plat-grid">
          {t.deploy.platforms.map((p) => (
            <div className="tg-plat" data-rise key={p.name}>
              <strong>{p.name}</strong>
              <span>{p.hint}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function Stats({ t }: { t: LandingCopy }) {
  return (
    <section className="tg-section tg-stats" id="stats" aria-labelledby="tg-stats-title">
      <div className="tg-stats-bg" aria-hidden>
        <Image
          src={ASSETS.statsBg}
          alt=""
          fill
          sizes="100vw"
          className="tg-stats-bg-img"
        />
      </div>
      <div className="tg-stats-glow" aria-hidden />
      <div className="tg-wrap">
        <div data-rise>
          <span className="tg-eyebrow">{t.stats.eyebrow}</span>
          <h2 className="tg-h2" id="tg-stats-title">
            {t.stats.title}
          </h2>
        </div>
        <div className="tg-stats-row">
          {t.stats.items.map((s) => (
            <div className="tg-stat" data-rise key={s.label}>
              <strong>{s.value}</strong>
              <span>{s.label}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function CaseStudies({ t }: { t: LandingCopy }) {
  return (
    <section
      className="tg-section tg-section-alt"
      id="cases"
      aria-labelledby="tg-cases-title"
    >
      <div className="tg-wrap">
        <div data-rise>
          <span className="tg-eyebrow">{t.cases.eyebrow}</span>
          <h2 className="tg-h2" id="tg-cases-title">
            {t.cases.title}
          </h2>
        </div>
        <div className="tg-cases" style={{ marginTop: "2.5rem" }}>
          {t.cases.items.map((c) => (
            <article className="tg-case" data-rise key={c.name}>
              <blockquote>“{c.quote}”</blockquote>
              <footer>
                <div>
                  <strong>{c.name}</strong>
                  <cite>{c.role}</cite>
                </div>
                <span className="tg-case-out">{c.outcome}</span>
              </footer>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

export function FinalCta({ t }: { t: LandingCopy }) {
  return (
    <section className="tg-final" id="final-cta" aria-labelledby="tg-final-title">
      <div className="tg-wrap" data-rise>
        <h2 className="tg-h2" id="tg-final-title">
          {t.finalCta.title}
        </h2>
        <p className="tg-lead">{t.finalCta.body}</p>
        <div className="tg-final-ctas">
          <a href={CTA_PRIMARY_HREF} className="tg-btn tg-btn-primary">
            {t.finalCta.primaryCta}
          </a>
          <a href={CTA_DEMO_HREF} className="tg-btn tg-btn-text">
            {t.finalCta.secondaryCta}
          </a>
        </div>
      </div>
    </section>
  );
}

export function Footer({
  t,
  onLang,
}: {
  t: LandingCopy;
  onLang: () => void;
}) {
  return (
    <footer className="tg-footer">
      <div className="tg-wrap">
        <div className="tg-footer-top">
          <div className="tg-footer-brand">
            <a href="#top" className="tg-logo">
              <Image
                src={ASSETS.logoFull}
                alt=""
                width={36}
                height={36}
                className="tg-logo-img"
              />
              <span className="tg-logo-word">{t.brand}</span>
            </a>
            <p>{t.footer.tagline}</p>
          </div>
          <div className="tg-footer-cols">
            {t.footer.columns.map((col) => (
              <div key={col.title}>
                <h4>{col.title}</h4>
                <ul>
                  {col.links.map((l) => (
                    <li key={l.label}>
                      <a href={l.href}>{l.label}</a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
        <div className="tg-footer-bottom">
          <span>
            © {new Date().getFullYear()} {t.footer.copyright}
          </span>
          <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
            <button type="button" className="tg-lang" onClick={onLang}>
              {t.langToggle}
            </button>
            <span className="tg-status">
              <i aria-hidden />
              {t.footer.status}
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}
