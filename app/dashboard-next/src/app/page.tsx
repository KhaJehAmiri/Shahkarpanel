"use client";

import { useEffect, useMemo, useState } from "react";
import {
  StorefrontLanding,
  StorefrontLoading,
  useStoreLang,
} from "@/components/storefront/StorefrontShell";
import {
  buildBecomeHref,
  buildRegisterHref,
  resolveStorefrontQuery,
} from "@/lib/storefront-context";
import { fetchStorefront, type StorefrontPayload } from "@/lib/storefront-api";
import "./public-pages.css";

export default function Home() {
  const [data, setData] = useState<StorefrontPayload | null>(null);
  const [err, setErr] = useState("");
  const [lang, setLang] = useStoreLang("fa");

  const q = useMemo(() => {
    if (typeof window === "undefined") return { tenant: null, ref: null };
    return resolveStorefrontQuery(window.location.pathname, window.location.search);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchStorefront({ tenant: q.tenant, ref: q.ref })
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((e: Error) => {
        if (!cancelled) setErr(e.message || "Failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [q.tenant, q.ref]);

  if (err) {
    return (
      <div className="sk-lp" dir={lang === "fa" ? "rtl" : "ltr"}>
        <main className="sk-lp-hero">
          <div className="sk-lp-hero-inner">
            <h1>Shahkar</h1>
            <p className="sk-lp-sub">{err}</p>
          </div>
        </main>
      </div>
    );
  }

  if (!data) return <StorefrontLoading lang={lang} />;

  return (
    <StorefrontLanding
      data={data}
      lang={lang}
      onLang={setLang}
      registerHref={buildRegisterHref(q)}
      becomeHref={buildBecomeHref(q)}
    />
  );
}
