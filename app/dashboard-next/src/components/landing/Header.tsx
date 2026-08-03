"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import { ASSETS } from "./assets";
import {
  CTA_PRIMARY_HREF,
  CTA_SIGNIN_HREF,
  type LandingCopy,
} from "./i18n";

export function Header({
  t,
  onLang,
}: {
  t: LandingCopy;
  onLang: () => void;
}) {
  const [solid, setSolid] = useState(false);

  useEffect(() => {
    const onScroll = () => setSolid(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className={`tg-header${solid ? " is-solid" : ""}`}>
      <div className="tg-header-inner">
        <a href="#top" className="tg-logo">
          <Image
            src={ASSETS.logoFull}
            alt=""
            width={36}
            height={36}
            className="tg-logo-img"
            priority
          />
          <span className="tg-logo-word">{t.brand}</span>
        </a>
        <nav className="tg-nav" aria-label="Primary">
          <a href="#features">{t.nav.product}</a>
          <a href="#how">{t.nav.how}</a>
          <a href="#platforms">{t.nav.platforms}</a>
          <a href="#cases">{t.nav.stories}</a>
        </nav>
        <div className="tg-header-actions">
          <button type="button" className="tg-lang" onClick={onLang}>
            {t.langToggle}
          </button>
          <a href={CTA_SIGNIN_HREF} className="tg-signin">
            {t.nav.signIn}
          </a>
          <a href={CTA_PRIMARY_HREF} className="tg-btn tg-btn-primary">
            {t.hero.primaryCta}
          </a>
        </div>
      </div>
    </header>
  );
}
