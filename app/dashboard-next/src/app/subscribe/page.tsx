"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { QR } from "@/components/QR";
import { AppTile } from "@/components/AppTile";
import { PLATFORMS, type Platform, appsFor, detectPlatform } from "@/lib/apps";
import { copyToClipboard } from "@/lib/clipboard";
import { bytes, formatDate, relativeDays } from "@/lib/format";
import {
  SUB_LANGS,
  SubLang,
  detectSubLang,
  t as subT,
} from "@/lib/subscribe-i18n";

interface SubInfo {
  username: string;
  status: string;
  used_traffic: number;
  data_limit: number | null;
  expire: number | null;
  links?: string[];
  subscription_url?: string;
  proxies?: Record<string, unknown>;
}

function getToken(): string {
  if (typeof window === "undefined") return "";
  const q = new URLSearchParams(window.location.search).get("token");
  if (q) return q;
  const m = window.location.pathname.match(/\/subscribe\/([^/]+)\/?$/);
  return m?.[1] ?? "";
}

function statusFor(lang: SubLang, s: string): { label: string; tone: "ok" | "warn" | "danger" | "neutral" } {
  const key = ["active", "disabled", "expired", "limited", "on_hold"].includes(s) ? s : s;
  const label = subT(lang, key) !== key ? subT(lang, key) : s;
  const tone =
    s === "active" ? "ok" :
    s === "expired" ? "warn" :
    s === "limited" ? "danger" : "neutral";
  return { label, tone };
}

function SubscribeBody() {
  const [lang, setLang] = useState<SubLang>("en");
  const [token, setToken] = useState<string>("");
  const [info, setInfo] = useState<SubInfo | null>(null);
  const [err, setErr] = useState<string>("");
  const [platform, setPlatform] = useState<Platform>("android");
  const [toast, setToastState] = useState<{ msg: string; kind: "ok" | "error" } | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setLang(detectSubLang());
    setToken(getToken());
    setPlatform(detectPlatform(typeof navigator !== "undefined" ? navigator.userAgent : ""));
  }, []);

  useEffect(() => {
    if (!token) return;
    fetch(`/sub/${token}/info`, { headers: { Accept: "application/json" } })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: SubInfo) => setInfo(data))
      .catch((e: Error) => setErr(e.message || subT(lang, "fetchError")));
  }, [token, lang]);

  const subUrl = useMemo(() => {
    if (!token || typeof window === "undefined") return "";
    return `${window.location.origin}/sub/${token}/`;
  }, [token]);

  const wgUrl = useMemo(() => {
    if (!token || typeof window === "undefined") return "";
    return `${window.location.origin}/sub/${token}/wireguard`;
  }, [token]);

  const hasWireguard = !!info?.proxies && "wireguard" in info.proxies;
  const used = info?.used_traffic ?? 0;
  const total = info?.data_limit || 0;
  const pct = total ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const status = info ? statusFor(lang, info.status) : { label: "—", tone: "neutral" as const };
  const expiry = info ? relativeDays(info.expire) : null;
  const rtl = lang === "fa";

  const showToast = useCallback((msg: string, kind: "ok" | "error" = "ok") => {
    setToastState({ msg, kind });
    setTimeout(() => setToastState(null), 2600);
  }, []);

  const pickLang = (code: SubLang) => {
    setLang(code);
    const u = new URL(window.location.href);
    u.searchParams.set("lang", code);
    window.history.replaceState({}, "", u.toString());
  };

  async function handleCopySub() {
    const ok = await copyToClipboard(subUrl);
    if (ok) {
      setCopied(true);
      showToast(subT(lang, "copied"));
      setTimeout(() => setCopied(false), 1500);
    } else {
      showToast(subT(lang, "copyFailed"), "error");
    }
  }

  if (err) {
    return (
      <main className="mx-auto max-w-md p-6 text-center" dir={rtl ? "rtl" : "ltr"}>
        <LangBar lang={lang} onPick={pickLang} />
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-6 text-danger">
          <div className="text-base font-bold">{subT(lang, "fetchError")}</div>
          <div className="mt-2 text-sm">{err}</div>
        </div>
      </main>
    );
  }

  if (!info) {
    return (
      <main className="mx-auto max-w-md p-6" dir={rtl ? "rtl" : "ltr"}>
        <LangBar lang={lang} onPick={pickLang} />
        <div className="h-32 animate-pulse rounded-lg bg-surface" />
        <div className="mt-3 h-44 animate-pulse rounded-lg bg-surface" />
        <div className="mt-3 h-64 animate-pulse rounded-lg bg-surface" />
      </main>
    );
  }

  const apps = appsFor(platform);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-6" dir={rtl ? "rtl" : "ltr"}>
      <LangBar lang={lang} onPick={pickLang} />

      <section className="rounded-lg border border-border bg-surface p-6 sm:p-8 shadow-card">
        <div className="flex flex-wrap items-center gap-5">
          <div className="grid h-16 w-16 flex-shrink-0 place-items-center rounded-[18px] bg-gradient-to-br from-accent to-accent-2 text-2xl font-bold tracking-tight text-[#04110f]">
            {info.username.slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-2xl font-bold tracking-tight">{info.username}</div>
            <div className="mt-0.5 text-xs text-text-faint">NexusPanel · {subT(lang, "personalSub")}</div>
            <div className="mt-2.5 inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold"
              style={{
                background:
                  status.tone === "ok" ? "rgba(52,211,153,0.18)" :
                  status.tone === "warn" ? "rgba(251,191,36,0.18)" :
                  status.tone === "danger" ? "rgba(248,113,113,0.18)" :
                  "rgba(120,130,150,0.18)",
                color:
                  status.tone === "ok" ? "#34d399" :
                  status.tone === "warn" ? "#fbbf24" :
                  status.tone === "danger" ? "#f87171" : "#98a4b6",
              }}
            >
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-current" />
              {status.label}
            </div>
          </div>
          <div className="flex flex-col items-center gap-1">
            <div className="relative h-24 w-24">
              <svg width="96" height="96" viewBox="0 0 96 96" className="-rotate-90">
                <circle cx="48" cy="48" r="40" fill="none" stroke="#232c3a" strokeWidth="8" />
                <circle
                  cx="48" cy="48" r="40" fill="none"
                  stroke={pct >= 90 ? "#f87171" : pct >= 70 ? "#fbbf24" : "#2ee0c4"}
                  strokeWidth="8" strokeLinecap="round"
                  strokeDasharray="251.327"
                  strokeDashoffset={251.327 - (251.327 * pct) / 100}
                />
              </svg>
              <div className="absolute inset-0 grid place-items-center text-lg font-bold tabular-nums">
                {total ? `${pct}%` : "∞"}
              </div>
            </div>
            <div className="text-[10px] uppercase tracking-widest text-text-faint">{subT(lang, "usage")}</div>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Stat k={subT(lang, "used")} v={bytes(used)} />
          <Stat k={subT(lang, "total")} v={total ? bytes(total) : subT(lang, "unlimited")} />
          <Stat
            k={subT(lang, "expiry")}
            v={info.expire ? formatDate(info.expire) : subT(lang, "noExpiry")}
            sub={info.expire && expiry ? expiry.text : undefined}
          />
        </div>
      </section>

      <section className="mt-5 rounded-lg border border-border bg-surface p-5 shadow-card">
        <div className="mb-3 text-[11px] font-bold uppercase tracking-widest text-text-faint">{subT(lang, "subLink")}</div>
        <div className="flex flex-col items-center gap-5 sm:flex-row">
          <div className="rounded-xl bg-white p-3 shadow-sm">
            {subUrl ? <QR value={subUrl} size={148} /> : null}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-bold tracking-tight">{subT(lang, "addToApp")}</h2>
            <p className="mt-1 text-sm leading-relaxed text-text-dim">{subT(lang, "addToAppHint")}</p>
            <div className="mt-3 flex items-stretch overflow-hidden rounded-md border border-border-strong bg-surface-2">
              <input readOnly dir="ltr" value={subUrl} className="min-w-0 flex-1 bg-transparent px-3 py-2 font-mono text-xs text-text outline-none"
                onClick={(e) => (e.target as HTMLInputElement).select()} />
              <button type="button" onClick={handleCopySub}
                className={`border-s border-border px-4 text-xs font-bold transition ${copied ? "bg-ok-soft text-ok" : "bg-surface-3 hover:bg-border-strong"}`}>
                {copied ? `✓ ${subT(lang, "copied")}` : subT(lang, "copy")}
              </button>
            </div>
          </div>
        </div>
      </section>

      {hasWireguard && (
        <section className="mt-5 rounded-lg border border-border bg-surface p-5 shadow-card">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-widest text-text-faint">{subT(lang, "wgTitle")}</div>
          <p className="text-sm leading-relaxed text-text-dim">{subT(lang, "wgHint")}</p>
          <a href={wgUrl} download={`${info.username}.conf`}
            className="mt-3 inline-flex items-center gap-2 rounded-md border border-accent bg-accent-soft px-4 py-2 text-sm font-bold text-accent">
            ⬇ {subT(lang, "wgDownload")}
          </a>
        </section>
      )}

      <section className="mt-5">
        <div className="mb-3 flex items-center justify-between px-1">
          <div className="text-[11px] font-bold uppercase tracking-widest text-text-faint">{subT(lang, "pickPlatform")}</div>
          <div className="text-[11px] text-text-faint">{apps.length} {subT(lang, "appsSuggested")}</div>
        </div>
        <div className="mb-3 flex flex-wrap gap-2">
          {PLATFORMS.map((p) => (
            <button key={p.id} type="button" onClick={() => setPlatform(p.id)}
              className={`rounded-md border px-4 py-2 text-sm font-semibold transition ${platform === p.id ? "border-accent bg-accent-soft text-accent" : "border-border bg-surface text-text-dim"}`}>
              {p.label}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {apps.map((a) => (
            <AppTile key={a.id} app={a} platform={platform} subUrl={subUrl} profileName="NexusPanel" onToast={showToast} />
          ))}
        </div>
      </section>

      {info.links && info.links.length > 0 && (
        <section className="mt-5">
          <div className="mb-3 px-1 text-[11px] font-bold uppercase tracking-widest text-text-faint">
            {subT(lang, "separateConfigs")} ({info.links.length})
          </div>
          <div className="flex flex-col gap-2">
            {info.links.map((link, i) => (
              <ConfigRow key={i} link={link} copyLabel={subT(lang, "copy")} closeLabel={subT(lang, "close")} onToast={showToast} />
            ))}
          </div>
        </section>
      )}

      <footer className="mt-8 border-t border-border pt-4 text-center text-[11px] text-text-faint">
        <div>{subT(lang, "footer")}</div>
        <div className="mt-1">{subT(lang, "footerHint")}</div>
      </footer>

      {toast && (
        <div role="status" className={`fixed inset-x-0 bottom-4 z-50 mx-auto w-max max-w-[calc(100%-2rem)] rounded-md border-s-4 bg-surface px-4 py-2.5 text-sm shadow-pop ${toast.kind === "ok" ? "border-s-ok" : "border-s-danger"}`}>
          {toast.msg}
        </div>
      )}
    </main>
  );
}

function LangBar({ lang, onPick }: { lang: SubLang; onPick: (c: SubLang) => void }) {
  return (
    <div className="mb-4 flex justify-end gap-1">
      {SUB_LANGS.map((l) => (
        <button key={l.code} type="button" onClick={() => onPick(l.code)}
          className={`rounded px-2 py-1 text-xs font-semibold ${lang === l.code ? "bg-accent-soft text-accent" : "text-text-faint hover:text-text"}`}>
          {l.label}
        </button>
      ))}
    </div>
  );
}

function Stat({ k, v, sub }: { k: string; v: string; sub?: string }) {
  return (
    <div className="rounded-md border border-border bg-surface-2 px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-text-faint">{k}</div>
      <div className="mt-0.5 truncate text-sm font-bold tabular-nums">{v}</div>
      {sub && <div className="mt-0.5 text-[11px] text-text-dim">{sub}</div>}
    </div>
  );
}

function ConfigRow({ link, copyLabel, closeLabel, onToast }: { link: string; copyLabel: string; closeLabel: string; onToast: (msg: string, kind?: "ok" | "error") => void }) {
  const [copied, setCopied] = useState(false);
  const [showQr, setShowQr] = useState(false);
  const proto = link.includes("://") ? link.split("://")[0] : "link";

  async function copy() {
    const ok = await copyToClipboard(link);
    if (ok) { setCopied(true); onToast(copyLabel); setTimeout(() => setCopied(false), 1500); }
    else { onToast(copyLabel, "error"); }
  }

  return (
    <div className="flex items-center gap-3 rounded-md border border-border bg-surface px-3 py-2.5">
      <span className="rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-bold uppercase text-accent">{proto}</span>
      <div dir="ltr" className="min-w-0 flex-1 truncate text-xs">{link}</div>
      <button type="button" onClick={() => setShowQr(true)} className="rounded-md border border-border-strong bg-surface-2 px-3 py-1.5 text-xs font-semibold">QR</button>
      <button type="button" onClick={copy} className={`rounded-md px-3 py-1.5 text-xs font-semibold ${copied ? "bg-ok-soft text-ok" : "border border-border-strong bg-surface-2"}`}>
        {copied ? "✓" : copyLabel}
      </button>
      {showQr && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-5" onClick={() => setShowQr(false)}>
          <div className="max-w-xs rounded-lg border border-border bg-surface p-5 text-center" onClick={(e) => e.stopPropagation()}>
            <div className="inline-block rounded-lg bg-white p-3"><QR value={link} size={200} /></div>
            <button type="button" onClick={() => setShowQr(false)} className="mt-3 rounded-md bg-surface-3 px-4 py-2 text-xs font-semibold">{closeLabel}</button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function SubscribePage() {
  return (
    <Suspense fallback={<div className="p-6 text-center text-text-dim">…</div>}>
      <SubscribeBody />
    </Suspense>
  );
}
