"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Header } from "./Header";
import { Hero } from "./Hero";
import { copy, type LandingLang } from "./i18n";
import {
  AccessVisual,
  CaseStudies,
  Deploy,
  Ecosystem,
  FeaturePairs,
  FinalCta,
  Footer,
  HowItWorks,
  LifestyleGallery,
  Stats,
  TrustBar,
} from "./sections";
import { useLandingMotion } from "./useLandingMotion";

const LANG_KEY = "nx_lang";

function readLang(): LandingLang {
  if (typeof window === "undefined") return "fa";
  try {
    const s = localStorage.getItem(LANG_KEY);
    if (s === "en" || s === "fa") return s;
  } catch {
    /* ignore */
  }
  return "fa";
}

export function LandingApp() {
  const rootRef = useRef<HTMLDivElement>(null);
  const [lang, setLang] = useState<LandingLang>("fa");
  const [ready, setReady] = useState(false);

  useLandingMotion(rootRef);

  useEffect(() => {
    setLang(readLang());
    setReady(true);
  }, []);

  const applyLang = useCallback((next: LandingLang) => {
    setLang(next);
    try {
      localStorage.setItem(LANG_KEY, next);
    } catch {
      /* ignore */
    }
    document.documentElement.setAttribute("lang", next);
    document.documentElement.setAttribute("dir", next === "fa" ? "rtl" : "ltr");
    document.title = copy[next].metaTitle;
  }, []);

  useEffect(() => {
    if (!ready) return;
    applyLang(lang);
  }, [ready, lang, applyLang]);

  const toggleLang = () => applyLang(lang === "fa" ? "en" : "fa");
  const t = copy[lang];

  return (
    <div
      id="top"
      ref={rootRef}
      className="tg"
      dir={lang === "fa" ? "rtl" : "ltr"}
      lang={lang}
    >
      <Header t={t} onLang={toggleLang} />
      <main>
        <Hero t={t} />
        <TrustBar t={t} />
        <HowItWorks t={t} />
        <FeaturePairs t={t} />
        <Ecosystem t={t} />
        <AccessVisual t={t} />
        <LifestyleGallery t={t} lang={lang} />
        <Deploy t={t} />
        <Stats t={t} />
        <CaseStudies t={t} />
        <FinalCta t={t} />
      </main>
      <Footer t={t} onLang={toggleLang} />
    </div>
  );
}
