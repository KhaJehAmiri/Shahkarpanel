"use client";

import { useEffect, type RefObject } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

let registered = false;

function ensureGsap() {
  if (registered || typeof window === "undefined") return;
  gsap.registerPlugin(ScrollTrigger);
  registered = true;
}

/** Hero entrance + scroll reveals for the cinematic storefront. */
export function useCinematicMotion(rootRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      root.querySelectorAll<HTMLElement>("[data-rise], [data-hero-el]").forEach((el) => {
        el.style.opacity = "1";
        el.style.transform = "none";
      });
      return;
    }

    ensureGsap();
    const ctx = gsap.context(() => {
      const heroEls = root.querySelectorAll<HTMLElement>("[data-hero-el]");
      if (heroEls.length) {
        gsap.fromTo(
          heroEls,
          { opacity: 0, y: 28 },
          {
            opacity: 1,
            y: 0,
            duration: 0.95,
            stagger: 0.09,
            ease: "power3.out",
            delay: 0.12,
          },
        );
      }

      const heroBg = root.querySelector<HTMLElement>("[data-hero-bg]");
      if (heroBg) {
        gsap.to(heroBg, {
          yPercent: 12,
          ease: "none",
          scrollTrigger: {
            trigger: root.querySelector("[data-hero]"),
            start: "top top",
            end: "bottom top",
            scrub: true,
          },
        });
      }

      root.querySelectorAll<HTMLElement>("[data-rise]").forEach((el) => {
        gsap.fromTo(
          el,
          { opacity: 0, y: 36 },
          {
            opacity: 1,
            y: 0,
            duration: 0.85,
            ease: "power2.out",
            scrollTrigger: {
              trigger: el,
              start: "top 88%",
              toggleActions: "play none none none",
            },
          },
        );
      });

      root.querySelectorAll<HTMLElement>("[data-parallax]").forEach((el) => {
        gsap.to(el, {
          yPercent: Number(el.dataset.parallax) || -8,
          ease: "none",
          scrollTrigger: {
            trigger: el.parentElement,
            start: "top bottom",
            end: "bottom top",
            scrub: true,
          },
        });
      });
    }, root);

    return () => ctx.revert();
  }, [rootRef]);
}
