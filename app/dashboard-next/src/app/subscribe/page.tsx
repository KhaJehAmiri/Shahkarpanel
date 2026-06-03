"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { QR } from "@/components/QR";
import { AppTile } from "@/components/AppTile";
import { PLATFORMS, type Platform, appsFor, detectPlatform } from "@/lib/apps";
import { copyToClipboard } from "@/lib/clipboard";
import { bytes, formatDate, relativeDays } from "@/lib/format";

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

function statusLabel(s: string): { fa: string; tone: "ok" | "warn" | "danger" | "neutral" } {
  switch (s) {
    case "active":
      return { fa: "فعال", tone: "ok" };
    case "disabled":
      return { fa: "غیرفعال", tone: "neutral" };
    case "expired":
      return { fa: "منقضی شده", tone: "warn" };
    case "limited":
      return { fa: "حجم تمام شد", tone: "danger" };
    case "on_hold":
      return { fa: "در انتظار", tone: "neutral" };
    default:
      return { fa: s, tone: "neutral" };
  }
}

function getToken(): string {
  if (typeof window === "undefined") return "";
  const q = new URLSearchParams(window.location.search).get("token");
  if (q) return q;
  // Some hosts may rewrite /sub/<token>/ → /subscribe/<token>/ — handle that.
  const m = window.location.pathname.match(/\/subscribe\/([^/]+)\/?$/);
  return m?.[1] ?? "";
}

function SubscribeBody() {
  const [token, setToken] = useState<string>("");
  const [info, setInfo] = useState<SubInfo | null>(null);
  const [err, setErr] = useState<string>("");
  const [platform, setPlatform] = useState<Platform>("android");
  const [toast, setToastState] = useState<{ msg: string; kind: "ok" | "error" } | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
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
      .catch((e: Error) => setErr(e.message || "خطا در دریافت اطلاعات"));
  }, [token]);

  const subUrl = useMemo(() => {
    if (!token) return "";
    return `${window.location.origin}/sub/${token}/`;
  }, [token]);

  const used = info?.used_traffic ?? 0;
  const total = info?.data_limit || 0;
  const pct = total ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const status = info ? statusLabel(info.status) : { fa: "—", tone: "neutral" as const };
  const expiry = info ? relativeDays(info.expire) : null;

  const showToast = useCallback((msg: string, kind: "ok" | "error" = "ok") => {
    setToastState({ msg, kind });
    setTimeout(() => setToastState(null), 2600);
  }, []);

  async function handleCopySub() {
    const ok = await copyToClipboard(subUrl);
    if (ok) {
      setCopied(true);
      showToast("لینک کپی شد");
      setTimeout(() => setCopied(false), 1500);
    } else {
      showToast("کپی ناموفق — به‌صورت دستی کپی کنید", "error");
    }
  }

  if (err) {
    return (
      <main className="mx-auto max-w-md p-6 text-center">
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-6 text-danger">
          <div className="text-base font-bold">خطا در دریافت اطلاعات اشتراک</div>
          <div className="mt-2 text-sm">{err}</div>
        </div>
      </main>
    );
  }

  if (!info) {
    return (
      <main className="mx-auto max-w-md p-6">
        <div className="h-32 animate-pulse rounded-lg bg-surface" />
        <div className="mt-3 h-44 animate-pulse rounded-lg bg-surface" />
        <div className="mt-3 h-64 animate-pulse rounded-lg bg-surface" />
      </main>
    );
  }

  const apps = appsFor(platform);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-6">
      {/* ===== HERO ===== */}
      <section className="rounded-lg border border-border bg-surface p-6 sm:p-8 shadow-card">
        <div className="flex flex-wrap items-center gap-5">
          <div className="grid h-16 w-16 flex-shrink-0 place-items-center rounded-[18px] bg-gradient-to-br from-accent to-accent-2 text-2xl font-bold tracking-tight text-[#04110f]">
            {info.username.slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-2xl font-bold tracking-tight">{info.username}</div>
            <div className="mt-0.5 text-xs text-text-faint">NexusPanel · اشتراک شخصی</div>
            <div className="mt-2.5 inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold"
              style={{
                background:
                  status.tone === "ok" ? "var(--ok-soft, rgba(52,211,153,0.18))" :
                  status.tone === "warn" ? "var(--warn-soft, rgba(251,191,36,0.18))" :
                  status.tone === "danger" ? "var(--danger-soft, rgba(248,113,113,0.18))" :
                  "rgba(120,130,150,0.18)",
                color:
                  status.tone === "ok" ? "#34d399" :
                  status.tone === "warn" ? "#fbbf24" :
                  status.tone === "danger" ? "#f87171" : "#98a4b6",
              }}
            >
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-current" />
              {status.fa}
            </div>
          </div>
          {/* Gauge */}
          <div className="flex flex-col items-center gap-1">
            <div className="relative h-24 w-24">
              <svg width="96" height="96" viewBox="0 0 96 96" className="-rotate-90">
                <circle cx="48" cy="48" r="40" fill="none" stroke="#232c3a" strokeWidth="8" />
                <circle
                  cx="48"
                  cy="48"
                  r="40"
                  fill="none"
                  stroke={pct >= 90 ? "#f87171" : pct >= 70 ? "#fbbf24" : "#2ee0c4"}
                  strokeWidth="8"
                  strokeLinecap="round"
                  strokeDasharray="251.327"
                  strokeDashoffset={251.327 - (251.327 * pct) / 100}
                  style={{ transition: "stroke-dashoffset 0.8s cubic-bezier(0.32,0.72,0,1)" }}
                />
              </svg>
              <div className="absolute inset-0 grid place-items-center text-lg font-bold tabular-nums">
                {total ? `${pct}%` : "∞"}
              </div>
            </div>
            <div className="text-[10px] uppercase tracking-widest text-text-faint">مصرف</div>
          </div>
        </div>

        {/* Stats band */}
        <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Stat k="مصرف‌شده" v={bytes(used)} />
          <Stat k="حجم کل" v={total ? bytes(total) : "نامحدود"} />
          <Stat
            k="انقضا"
            v={info.expire ? formatDate(info.expire) : "بدون انقضا"}
            sub={info.expire && expiry ? expiry.text : undefined}
          />
        </div>
      </section>

      {/* ===== SUB URL ===== */}
      <section className="mt-5 rounded-lg border border-border bg-surface p-5 shadow-card">
        <div className="mb-3 text-[11px] font-bold uppercase tracking-widest text-text-faint">لینک اشتراک</div>
        <div className="flex flex-col items-center gap-5 sm:flex-row">
          <div className="rounded-xl bg-white p-3 shadow-sm">
            {subUrl ? <QR value={subUrl} size={148} /> : null}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-bold tracking-tight">اضافه‌کردن به اپلیکیشن</h2>
            <p className="mt-1 text-sm leading-relaxed text-text-dim">
              این لینک را در اپ مورد علاقه‌تان ایمپورت کنید یا QR را اسکن نمایید. تنظیمات بعداً خودکار به‌روز می‌شود.
            </p>
            <div className="mt-3 flex items-stretch overflow-hidden rounded-md border border-border-strong bg-surface-2">
              <input
                readOnly
                dir="ltr"
                value={subUrl}
                className="min-w-0 flex-1 bg-transparent px-3 py-2 font-mono text-xs text-text outline-none"
                onClick={(e) => (e.target as HTMLInputElement).select()}
              />
              <button
                type="button"
                onClick={handleCopySub}
                className={`border-s border-border px-4 text-xs font-bold transition ${
                  copied ? "bg-ok-soft text-ok" : "bg-surface-3 hover:bg-border-strong"
                }`}
              >
                {copied ? "✓ کپی شد" : "کپی"}
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* ===== PLATFORM TABS ===== */}
      <section className="mt-5">
        <div className="mb-3 flex items-center justify-between px-1">
          <div className="text-[11px] font-bold uppercase tracking-widest text-text-faint">
            انتخاب پلتفرم و اپ
          </div>
          <div className="text-[11px] text-text-faint">
            {apps.length} اپ پیشنهادی
          </div>
        </div>

        <div className="mb-3 flex flex-wrap gap-2">
          {PLATFORMS.map((p) => {
            const active = p.id === platform;
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => setPlatform(p.id)}
                className={`rounded-md border px-4 py-2 text-sm font-semibold transition ${
                  active
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border bg-surface text-text-dim hover:border-border-strong hover:text-text"
                }`}
              >
                {p.label}
              </button>
            );
          })}
        </div>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {apps.map((a) => (
            <AppTile
              key={a.id}
              app={a}
              platform={platform}
              subUrl={subUrl}
              profileName="NexusPanel"
              onToast={showToast}
            />
          ))}
        </div>
      </section>

      {/* ===== INDIVIDUAL CONFIGS ===== */}
      {info.links && info.links.length > 0 && (
        <section className="mt-5">
          <div className="mb-3 px-1 text-[11px] font-bold uppercase tracking-widest text-text-faint">
            کانفیگ‌های جداگانه ({info.links.length})
          </div>
          <div className="flex flex-col gap-2">
            {info.links.map((link, i) => (
              <ConfigRow key={i} link={link} onToast={showToast} />
            ))}
          </div>
        </section>
      )}

      <footer className="mt-8 border-t border-border pt-4 text-center text-[11px] text-text-faint">
        <div>NexusPanel · صفحه‌ی اشتراک</div>
        <div className="mt-1">
          اگر اپ مورد نظر در لیست نیست، لینک بالا را کپی کنید و دستی اضافه نمایید.
        </div>
      </footer>

      {/* TOAST */}
      {toast && (
        <div
          role="status"
          className={`fixed inset-x-0 bottom-4 z-50 mx-auto w-max max-w-[calc(100%-2rem)] rounded-md border-s-4 bg-surface px-4 py-2.5 text-sm shadow-pop ${
            toast.kind === "ok" ? "border-s-ok" : "border-s-danger"
          }`}
        >
          {toast.msg}
        </div>
      )}
    </main>
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

function ConfigRow({ link, onToast }: { link: string; onToast: (msg: string, kind?: "ok" | "error") => void }) {
  const [copied, setCopied] = useState(false);
  const [showQr, setShowQr] = useState(false);
  const proto = link.includes("://") ? link.split("://")[0] : "link";

  async function copy() {
    const ok = await copyToClipboard(link);
    if (ok) {
      setCopied(true);
      onToast("کپی شد");
      setTimeout(() => setCopied(false), 1500);
    } else {
      onToast("کپی ناموفق", "error");
    }
  }

  return (
    <div className="flex items-center gap-3 rounded-md border border-border bg-surface px-3 py-2.5">
      <span className="rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-bold uppercase text-accent">
        {proto}
      </span>
      <div dir="ltr" className="min-w-0 flex-1 truncate text-xs">{link}</div>
      <button
        type="button"
        onClick={() => setShowQr(true)}
        className="rounded-md border border-border-strong bg-surface-2 px-3 py-1.5 text-xs font-semibold hover:bg-surface-3"
      >
        QR
      </button>
      <button
        type="button"
        onClick={copy}
        className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
          copied ? "bg-ok-soft text-ok" : "border border-border-strong bg-surface-2 hover:bg-surface-3"
        }`}
      >
        {copied ? "✓" : "کپی"}
      </button>
      {showQr && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-5 backdrop-blur-sm"
          onClick={() => setShowQr(false)}
        >
          <div className="w-full max-w-xs rounded-lg border border-border bg-surface p-5 text-center" onClick={(e) => e.stopPropagation()}>
            <div className="inline-block rounded-lg bg-white p-3">
              <QR value={link} size={200} />
            </div>
            <div dir="ltr" className="mt-3 break-all text-[10px] text-text-faint">
              {link.length > 100 ? link.slice(0, 100) + "…" : link}
            </div>
            <button
              type="button"
              onClick={() => setShowQr(false)}
              className="mt-3 rounded-md bg-surface-3 px-4 py-2 text-xs font-semibold"
            >
              بستن
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function SubscribePage() {
  return (
    <Suspense fallback={<div className="p-6 text-center text-text-dim">در حال بارگذاری…</div>}>
      <SubscribeBody />
    </Suspense>
  );
}
