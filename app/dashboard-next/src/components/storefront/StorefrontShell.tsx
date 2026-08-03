"use client";

import Link from "next/link";
import {
  CSSProperties,
  ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ArrowLeft, ArrowRight, Check, Lock, Signal, Zap } from "lucide-react";
import {
  formatPlanPrice,
  pickFeaturedPlanIndex,
  planFeatures,
} from "@/lib/plan-display";
import type { StorefrontPayload, StorefrontPlan } from "@/lib/storefront-api";
import { useCinematicMotion } from "./useCinematicMotion";
import "@/app/public-pages.css";

const DEFAULT_LOGO = "/sub-assets/brand/shahkar.png";

const IMG = {
  hero: "/brand/landing/cin-hero.png",
  problem: "/brand/landing/cin-problem.png",
  secure: "/brand/landing/cin-solution.png",
  speed: "/brand/landing/cin-feat-fast.png",
  stable: "/brand/landing/cin-feat-stable.png",
  support: "/brand/landing/cin-feat-support.png",
  product: "/brand/landing/cin-product.png",
  cta: "/brand/landing/cin-solution.png",
} as const;

const COPY = {
  fa: {
    start: "شروع کنید",
    login: "ورود به پنل",
    choosePlan: "خرید این پلن",
    plans: "پلن‌های اتصال",
    plansCta: "مشاهده پلن‌ها",
    plansHint: "حجم، مدت و تعداد دستگاه — بعد از پرداخت، همان لحظه فعال می‌شود.",
    popular: "پرفروش",
    reseller: "نمایندگی بفروشید",
    resellerHint: "برند خودتان، پنل اختصاصی، و امکان جذب زیرنماینده.",
    apply: "درخواست نمایندگی",
    support: "پشتیبانی",
    defaultHeadline: "امن. سریع. همیشه وصل.",
    defaultTagline:
      "اتصال خصوصی برای گوشی و لپ‌تاپ — ثبت‌نام کنید، پلن بخرید و همان لحظه آنلاین شوید.",
    kicker: "شبکهٔ خصوصی امن",
    pillarsTitle: "سه ستون اتصال شما",
    pillarsHint: "امنیت، سرعت و پایداری — بدون شعار اضافه.",
    secT: "امنیت",
    secD: "ترافیک رمزنگاری‌شده؛ هویت و مسیر شما پشت لایهٔ خصوصی می‌ماند.",
    spdT: "سرعت",
    spdD: "مسیرهای بهینه‌شده برای پخش، کار و بازی در ساعات اوج.",
    conT: "اتصال پایدار",
    conD: "طراحی‌شده برای قطع‌نشدن؛ وصل بمانید وقتی شبکه شلوغ است.",
    problemTitle: "قطع و کندی، تمام شد",
    problemHint: "از قطعی و مسیرهای شلوغ تا یک کانفیگ آماده — یک قدم فاصله است.",
    pathTitle: "تا اتصال امن، سه قدم",
    pathHint: "از خرید تا کانفیگ — بدون پیچیدگی اضافه.",
    p1t: "حساب بسازید",
    p1d: "ثبت‌نام کوتاه؛ ورود به پنل کاربری.",
    p2t: "پلن بخرید",
    p2d: "حجم و مدت مناسب را انتخاب و پرداخت کنید.",
    p3t: "وصل شوید",
    p3d: "کانفیگ را بگیرید و روی گوشی یا لپ‌تاپ وصل شوید.",
    shelfNote: "قیمت‌ها به {currency}",
    productTitle: "همه‌جا، یک اتصال",
    productHint: "پنل ساده روی دسکتاپ و موبایل — وضعیت، مصرف و کانفیگ در یک نگاه.",
    finalCta: "همین حالا وصل شوید",
    finalHint: "حساب بسازید یا اگر حساب دارید، مستقیم وارد پنل شوید.",
    secureAlt: "لایهٔ امنیتی فعال روی دستگاه",
    speedAlt: "مسیر پرسرعت شبکه",
    connectAlt: "اتصال پایدار سراسری",
    productAlt: "پنل روی لپ‌تاپ و موبایل",
  },
  en: {
    start: "Get started",
    login: "Open panel",
    choosePlan: "Buy this plan",
    plans: "Connection plans",
    plansCta: "View plans",
    plansHint: "Data, duration, and devices — activate the moment you pay.",
    popular: "Best seller",
    reseller: "Sell as a reseller",
    resellerHint: "Your brand, your panel, and room to grow with sub-resellers.",
    apply: "Apply as reseller",
    support: "Support",
    defaultHeadline: "Secure. Fast. Always on.",
    defaultTagline:
      "Private access for phone and laptop — sign up, buy a plan, and connect instantly.",
    kicker: "Private secure network",
    pillarsTitle: "Three pillars of your link",
    pillarsHint: "Security, speed, and uptime — no extra noise.",
    secT: "Security",
    secD: "Encrypted traffic; your identity and path stay behind a private layer.",
    spdT: "Speed",
    spdD: "Routes tuned for stream, work, and play when the network peaks.",
    conT: "Stable link",
    conD: "Built to hold — stay online when the path gets crowded.",
    problemTitle: "Drops and lag, done",
    problemHint: "From dead links and crowded routes to a ready config — one step away.",
    pathTitle: "Online in three steps",
    pathHint: "From purchase to config — no maze.",
    p1t: "Create an account",
    p1d: "Short signup, then your user panel.",
    p2t: "Buy a plan",
    p2d: "Pick the data and duration that fit, then pay.",
    p3t: "Connect",
    p3d: "Get your config and connect on phone or laptop.",
    shelfNote: "Prices in {currency}",
    productTitle: "One link, every screen",
    productHint: "A clean panel on desktop and mobile — status, usage, and config at a glance.",
    finalCta: "Connect now",
    finalHint: "Create an account — or go straight to the panel if you already have one.",
    secureAlt: "Active security layer on device",
    speedAlt: "High-speed network path",
    connectAlt: "Stable global connection",
    productAlt: "Panel on laptop and phone",
  },
} as const;

export function useStorefrontTheme(data: StorefrontPayload | null) {
  useEffect(() => {
    if (!data) return;
    const roots = [
      document.documentElement,
      ...Array.from(document.querySelectorAll<HTMLElement>(".sk-lp")),
    ];
    const color = data.branding.primary_color?.trim();
    if (color) {
      const rgb = hexToRgb(color);
      for (const el of roots) {
        el.style.setProperty("--sk-brand", color);
        if (rgb) el.style.setProperty("--sk-brand-rgb", `${rgb.r}, ${rgb.g}, ${rgb.b}`);
      }
    }
    document.title = data.branding.panel_title?.trim() || "Shahkar";
    const fav = data.branding.favicon_url?.trim();
    if (fav) {
      let link = document.head.querySelector<HTMLLinkElement>('link[rel="icon"]');
      if (!link) {
        link = document.createElement("link");
        link.rel = "icon";
        document.head.appendChild(link);
      }
      link.href = fav;
    }
  }, [data]);
}

function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex.trim());
  if (!m) return null;
  return { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) };
}

function Arrow({ rtl }: { rtl?: boolean }) {
  return rtl ? (
    <ArrowLeft size={16} strokeWidth={2.2} aria-hidden />
  ) : (
    <ArrowRight size={16} strokeWidth={2.2} aria-hidden />
  );
}

function resolveHeadline(data: StorefrontPayload, brand: string, fa: boolean): string {
  const raw = (data.headline || "").trim();
  if (raw && raw.toLowerCase() !== brand.toLowerCase()) return raw;
  return fa ? COPY.fa.defaultHeadline : COPY.en.defaultHeadline;
}

function resolveTagline(data: StorefrontPayload, fa: boolean): string {
  const raw = (data.tagline || "").trim();
  if (
    raw &&
    raw !== "Secure access. Self-service. Ready in minutes." &&
    raw !== "Multi-tenant. White-label. Xray at the core."
  ) {
    return raw;
  }
  return fa ? COPY.fa.defaultTagline : COPY.en.defaultTagline;
}

function PlanCard({
  plan,
  featured,
  currency,
  lang,
  href,
  signupEnabled,
}: {
  plan: StorefrontPlan;
  featured: boolean;
  currency: string;
  lang: "fa" | "en";
  href: string;
  signupEnabled: boolean;
}) {
  const t = COPY[lang];
  const price = formatPlanPrice(plan, currency, lang);
  const features = planFeatures(plan, lang);

  return (
    <article className={`sk-lp-card${featured ? " is-featured" : ""}`} data-rise>
      {featured ? <span className="sk-lp-card-badge">{t.popular}</span> : null}
      <header className="sk-lp-card-head">
        <h3>{plan.name}</h3>
        <div className="sk-lp-card-price">
          <strong>{price.main}</strong>
          {price.suffix ? <span>{price.suffix}</span> : null}
        </div>
      </header>
      <ul className="sk-lp-card-features">
        {features.map((f) => (
          <li key={f.label}>
            <span className="sk-lp-check">
              <Check size={14} strokeWidth={2.4} aria-hidden />
            </span>
            {f.label}
          </li>
        ))}
      </ul>
      <Link
        href={signupEnabled ? href : "/portal/"}
        className={`sk-lp-btn${featured ? "" : " sk-lp-btn-ghost"} sk-lp-card-cta`}
      >
        {t.choosePlan}
        <Arrow rtl={lang === "fa"} />
      </Link>
    </article>
  );
}

function HeroSignalField() {
  return (
    <div className="sk-cin-signals" aria-hidden>
      <span className="sk-cin-orbit sk-cin-orbit-a" />
      <span className="sk-cin-orbit sk-cin-orbit-b" />
      <span className="sk-cin-beam" />
      <svg className="sk-cin-mesh" viewBox="0 0 800 500" preserveAspectRatio="xMidYMid slice">
        <defs>
          <linearGradient id="skMeshGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="rgba(61,224,197,0)" />
            <stop offset="45%" stopColor="rgba(61,224,197,0.45)" />
            <stop offset="100%" stopColor="rgba(90,235,255,0)" />
          </linearGradient>
        </defs>
        <g className="sk-cin-mesh-lines" stroke="url(#skMeshGrad)" strokeWidth="1.2" fill="none">
          <path d="M40 420 C180 300 320 380 480 220 S700 80 780 140" />
          <path d="M20 260 C200 200 340 320 520 180 S720 220 790 90" />
          <path d="M60 480 C240 360 400 400 560 280 S740 300 800 220" />
        </g>
        <g className="sk-cin-mesh-nodes" fill="rgba(61,224,197,0.85)">
          <circle cx="180" cy="310" r="3.5" />
          <circle cx="480" cy="220" r="4" />
          <circle cx="560" cy="280" r="3" />
          <circle cx="720" cy="150" r="3.5" />
        </g>
      </svg>
    </div>
  );
}

type LandingProps = {
  data: StorefrontPayload;
  lang?: "fa" | "en";
  onLang?: (lang: "fa" | "en") => void;
  registerHref: string;
  becomeHref: string;
  portalHref?: string;
};

export function StorefrontLanding({
  data,
  lang = "fa",
  onLang,
  registerHref,
  becomeHref,
  portalHref = "/portal/",
}: LandingProps) {
  useStorefrontTheme(data);
  const rootRef = useRef<HTMLDivElement>(null);
  useCinematicMotion(rootRef);

  const fa = lang === "fa";
  const t = COPY[lang];
  const brand = data.branding.panel_title?.trim() || "Shahkar";
  const logo = data.branding.logo_url?.trim() || DEFAULT_LOGO;
  const headline = resolveHeadline(data, brand, fa);
  const tagline = resolveTagline(data, fa);
  const plans = data.plans.slice(0, 6);
  const featuredIdx = useMemo(() => pickFeaturedPlanIndex(plans), [plans]);
  const primaryHref = data.signup_enabled ? registerHref : portalHref;

  const pillars = [
    { icon: Lock, title: t.secT, desc: t.secD, img: IMG.secure, alt: t.secureAlt },
    { icon: Zap, title: t.spdT, desc: t.spdD, img: IMG.speed, alt: t.speedAlt },
    { icon: Signal, title: t.conT, desc: t.conD, img: IMG.stable, alt: t.connectAlt },
  ];

  const path = [
    { n: fa ? "۰۱" : "01", title: t.p1t, desc: t.p1d },
    { n: fa ? "۰۲" : "02", title: t.p2t, desc: t.p2d },
    { n: fa ? "۰۳" : "03", title: t.p3t, desc: t.p3d },
  ];

  return (
    <div className="sk-lp sk-cin" ref={rootRef} dir={fa ? "rtl" : "ltr"} lang={lang}>
      <div className="sk-cin-grain" aria-hidden />

      <header className="sk-lp-nav sk-lp-nav-over">
        <div className="sk-lp-nav-inner">
          <div className="sk-lp-brand">
            <img src={logo} alt="" />
            <span>{brand}</span>
          </div>
          <div className="sk-lp-nav-actions">
            {onLang ? (
              <div className="sk-lp-lang" role="group" aria-label="Language">
                <button type="button" className={lang === "fa" ? "is-on" : ""} onClick={() => onLang("fa")}>
                  FA
                </button>
                <button type="button" className={lang === "en" ? "is-on" : ""} onClick={() => onLang("en")}>
                  EN
                </button>
              </div>
            ) : null}
            <Link href={portalHref} className="sk-lp-link">
              {t.login}
            </Link>
            <Link href={primaryHref} className="sk-lp-btn sk-lp-btn-sm">
              {t.start}
            </Link>
          </div>
        </div>
      </header>

      <main>
        <section className="sk-lp-hero sk-lp-hero-bleed" data-hero>
          <img
            className="sk-lp-hero-bg"
            data-hero-bg
            src={IMG.hero}
            alt=""
            fetchPriority="high"
          />
          <div className="sk-lp-hero-scrim" aria-hidden />
          <HeroSignalField />
          <div className="sk-cin-hero-frame">
            <p className="sk-cin-kicker" data-hero-el>
              {t.kicker}
            </p>
            <h1 className="sk-cin-brand" data-hero-el>
              {brand}
            </h1>
            <p className="sk-cin-headline" data-hero-el>
              {headline}
            </p>
            <p className="sk-lp-sub" data-hero-el>
              {tagline}
            </p>
            <div className="sk-lp-hero-cta" data-hero-el>
              <Link href={primaryHref} className="sk-lp-btn sk-lp-btn-pulse">
                {t.start}
                <Arrow rtl={fa} />
              </Link>
              {plans.length > 0 ? (
                <a href="#plans" className="sk-lp-btn sk-lp-btn-ghost">
                  {t.plansCta}
                </a>
              ) : null}
            </div>
          </div>
        </section>

        <section className="sk-lp-section sk-cin-pillars" aria-labelledby="sk-pillars">
          <div className="sk-lp-section-inner">
            <div className="sk-lp-section-head" data-rise>
              <h2 id="sk-pillars">{t.pillarsTitle}</h2>
              <p>{t.pillarsHint}</p>
            </div>
            <div className="sk-cin-pillar-grid">
              {pillars.map((p) => {
                const Icon = p.icon;
                return (
                  <article key={p.title} className="sk-cin-pillar" data-rise>
                    <figure className="sk-cin-pillar-visual">
                      <img src={p.img} alt={p.alt} data-parallax="-6" />
                    </figure>
                    <div className="sk-cin-pillar-body">
                      <span className="sk-cin-pillar-icon">
                        <Icon size={18} strokeWidth={2.1} aria-hidden />
                      </span>
                      <h3>{p.title}</h3>
                      <p>{p.desc}</p>
                    </div>
                  </article>
                );
              })}
            </div>
          </div>
        </section>

        <section className="sk-lp-section sk-cin-bridge" aria-labelledby="sk-bridge">
          <div className="sk-lp-section-inner sk-cin-bridge-grid">
            <figure className="sk-cin-bridge-shot" data-rise>
              <img src={IMG.problem} alt="" data-parallax="-5" />
            </figure>
            <div data-rise>
              <h2 id="sk-bridge">{t.problemTitle}</h2>
              <p>{t.problemHint}</p>
              <Link href={primaryHref} className="sk-lp-btn" style={{ marginTop: 22 }}>
                {t.start}
                <Arrow rtl={fa} />
              </Link>
            </div>
          </div>
        </section>

        <section className="sk-lp-section sk-cin-path" aria-labelledby="sk-path">
          <div className="sk-lp-section-inner">
            <div className="sk-lp-section-head" data-rise>
              <h2 id="sk-path">{t.pathTitle}</h2>
              <p>{t.pathHint}</p>
            </div>
            <ol className="sk-cin-steps">
              {path.map((step) => (
                <li key={step.title} data-rise>
                  <span className="sk-cin-step-n">{step.n}</span>
                  <strong>{step.title}</strong>
                  <small>{step.desc}</small>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {plans.length > 0 && (
          <section className="sk-lp-section sk-cin-shelf" id="plans" aria-labelledby="sk-plans">
            <div className="sk-lp-section-inner">
              <div className="sk-lp-section-head" data-rise>
                <h2 id="sk-plans">{t.plans}</h2>
                <p>{t.plansHint}</p>
                <p className="sk-cin-shelf-note">
                  {t.shelfNote.replace("{currency}", data.currency_label || "")}
                </p>
              </div>
              <div
                className="sk-lp-cards"
                style={
                  {
                    gridTemplateColumns:
                      plans.length === 1
                        ? "minmax(0, 340px)"
                        : plans.length === 2
                          ? "repeat(2, minmax(0, 1fr))"
                          : "repeat(auto-fit, minmax(250px, 1fr))",
                    justifyContent: plans.length === 1 ? "center" : undefined,
                  } as CSSProperties
                }
              >
                {plans.map((plan, i) => (
                  <PlanCard
                    key={plan.id}
                    plan={plan}
                    featured={i === featuredIdx && plans.length > 1}
                    currency={data.currency_label}
                    lang={lang}
                    href={registerHref}
                    signupEnabled={data.signup_enabled}
                  />
                ))}
              </div>
            </div>
          </section>
        )}

        <section className="sk-lp-section sk-cin-product" aria-labelledby="sk-product">
          <div className="sk-lp-section-inner sk-cin-product-grid">
            <div data-rise>
              <h2 id="sk-product">{t.productTitle}</h2>
              <p>{t.productHint}</p>
            </div>
            <figure className="sk-cin-product-shot" data-rise>
              <img src={IMG.product} alt={t.productAlt} data-parallax="-7" />
            </figure>
          </div>
        </section>

        {data.reseller_apply_enabled && (
          <section className="sk-lp-section">
            <div className="sk-lp-section-inner">
              <div className="sk-lp-reseller" data-rise>
                <div>
                  <h2>{t.reseller}</h2>
                  <p>{t.resellerHint}</p>
                </div>
                <Link href={becomeHref} className="sk-lp-btn sk-lp-btn-ghost">
                  {t.apply}
                  <Arrow rtl={fa} />
                </Link>
              </div>
            </div>
          </section>
        )}

        <section className="sk-lp-section sk-lp-final">
          <div className="sk-lp-section-inner">
            <div className="sk-lp-final-panel sk-lp-final-photo" data-rise>
              <img src={IMG.cta} alt="" className="sk-lp-final-bg" />
              <div className="sk-lp-final-scrim" aria-hidden />
              <div className="sk-lp-final-content">
                <h2>{t.finalCta}</h2>
                <p>{t.finalHint}</p>
                <div className="sk-lp-hero-cta">
                  <Link href={primaryHref} className="sk-lp-btn sk-lp-btn-pulse">
                    {t.start}
                    <Arrow rtl={fa} />
                  </Link>
                  <Link href={portalHref} className="sk-lp-btn sk-lp-btn-ghost">
                    {t.login}
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="sk-lp-foot">
        <div className="sk-lp-foot-inner">
          <div className="sk-lp-brand sk-lp-brand-sm">
            <img src={logo} alt="" />
            <span>{brand}</span>
          </div>
          {data.branding.support_url ? (
            <a href={data.branding.support_url} target="_blank" rel="noreferrer">
              {t.support}
            </a>
          ) : (
            <span />
          )}
        </div>
      </footer>
    </div>
  );
}

type FormShellProps = {
  data: StorefrontPayload | null;
  title: string;
  subtitle?: string;
  lang?: "fa" | "en";
  children: ReactNode;
  backHref?: string;
};

export function StorefrontFormShell({
  data,
  title,
  subtitle,
  lang = "fa",
  children,
  backHref = "/",
}: FormShellProps) {
  useStorefrontTheme(data);
  const fa = lang === "fa";
  const brand = data?.branding.panel_title?.trim() || "Shahkar";
  const logo = data?.branding.logo_url?.trim() || DEFAULT_LOGO;

  return (
    <div className="sk-lp sk-lp-form sk-cin" dir={fa ? "rtl" : "ltr"} lang={lang}>
      <img className="sk-lp-form-bg" src={IMG.hero} alt="" aria-hidden />
      <div className="sk-lp-form-scrim" aria-hidden />
      <main className="sk-lp-form-wrap">
        <Link href={backHref} className="sk-lp-back">
          {fa ? `→ ${brand}` : `← ${brand}`}
        </Link>
        <div className="sk-lp-form-card">
          <div className="sk-lp-brand sk-lp-form-brand">
            <img src={logo} alt="" />
            <span>{brand}</span>
          </div>
          <h1>{title}</h1>
          {subtitle ? <p className="sk-lp-form-sub">{subtitle}</p> : null}
          {children}
        </div>
      </main>
    </div>
  );
}

export function StorefrontLoading({ lang = "fa" }: { lang?: "fa" | "en" }) {
  return (
    <div className="sk-lp sk-cin" dir={lang === "fa" ? "rtl" : "ltr"}>
      <img className="sk-lp-hero-bg" src={IMG.hero} alt="" />
      <div className="sk-lp-hero-scrim" aria-hidden />
      <main className="sk-lp-hero sk-lp-hero-bleed">
        <div className="sk-cin-hero-frame">
          <div className="sk-lp-skel sk-lp-skel-brand" />
          <div className="sk-lp-skel sk-lp-skel-h1" />
          <div className="sk-lp-skel sk-lp-skel-sub" />
          <div className="sk-lp-skel sk-lp-skel-btn" />
        </div>
      </main>
    </div>
  );
}

export function useStoreLang(initial: "fa" | "en" = "fa") {
  const [lang, setLang] = useState<"fa" | "en">(initial);
  useEffect(() => {
    try {
      const stored = localStorage.getItem("nx_lang");
      if (stored === "en" || stored === "fa") setLang(stored);
      else if ((navigator.language || "").startsWith("en")) setLang("en");
    } catch {
      /* ignore */
    }
  }, []);
  const pick = (next: "fa" | "en") => {
    setLang(next);
    try {
      localStorage.setItem("nx_lang", next);
      document.documentElement.setAttribute("lang", next);
      document.documentElement.setAttribute("dir", next === "fa" ? "rtl" : "ltr");
    } catch {
      /* ignore */
    }
  };
  return [lang, pick] as const;
}
