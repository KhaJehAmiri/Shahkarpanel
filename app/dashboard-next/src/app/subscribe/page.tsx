"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { ConnectCard } from "@/components/subscribe/ConnectCard";
import { SubAppTile } from "@/components/subscribe/SubAppTile";
import { SubWgAppTile } from "@/components/subscribe/SubWgAppTile";
import { UsageBar } from "@/components/subscribe/UsageBar";
import { QR } from "@/components/QR";
import { PLATFORMS, type Platform, appsFor, detectPlatform } from "@/lib/apps";
import { wgAppsFor } from "@/lib/wg-apps";
import { copyToClipboard } from "@/lib/clipboard";
import { bytes, formatDate, relativeDays } from "@/lib/format";
import { SUB_LANGS, SubLang, detectSubLang, t as subT } from "@/lib/subscribe-i18n";
import { resolvePublicSubUrl, resolveWgUrl } from "@/lib/subscribe-url";

type ProtocolTab = "proxy" | "wireguard";

interface SubInfo {
  username: string;
  status: string;
  used_traffic: number;
  data_limit: number | null;
  expire: number | null;
  links?: string[];
  proxies?: Record<string, unknown>;
  config_available?: boolean;
  block_reason?: string | null;
  public_subscription_url?: string;
}

function getToken(): string {
  if (typeof window === "undefined") return "";
  const q = new URLSearchParams(window.location.search).get("token");
  if (q) return q;
  const m = window.location.pathname.match(/\/subscribe\/([^/]+)\/?$/);
  return m?.[1] ?? "";
}

function statusChip(lang: SubLang, s: string): { label: string; cls: string } {
  const label = subT(lang, s) !== s ? subT(lang, s) : s;
  const cls =
    s === "active" ? "ok" :
    s === "expired" ? "warn" :
    s === "limited" ? "danger" : "neutral";
  return { label, cls };
}

function SubscribeBody() {
  const [lang, setLang] = useState<SubLang>("en");
  const [token, setToken] = useState("");
  const [info, setInfo] = useState<SubInfo | null>(null);
  const [err, setErr] = useState("");
  const [platform, setPlatform] = useState<Platform>("android");
  const [protocol, setProtocol] = useState<ProtocolTab>("proxy");
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "error" } | null>(null);
  const [copiedProxy, setCopiedProxy] = useState(false);
  const [copiedWg, setCopiedWg] = useState(false);

  const loadInfo = useCallback((tok: string) => {
    if (!tok) return;
    setErr("");
    fetch(`/sub/${tok}/info`, { headers: { Accept: "application/json" } })
      .then(async (r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((data: SubInfo) => setInfo(data))
      .catch((e: Error) => setErr(e.message || subT(lang, "fetchError")));
  }, [lang]);

  useEffect(() => {
    setLang(detectSubLang());
    const tok = getToken();
    setToken(tok);
    setPlatform(detectPlatform(typeof navigator !== "undefined" ? navigator.userAgent : ""));
    loadInfo(tok);
  }, [loadInfo]);

  const subUrl = useMemo(() => resolvePublicSubUrl(info, token), [info, token]);
  const wgUrl = useMemo(() => resolveWgUrl(subUrl), [subUrl]);

  const hasWireguard = !!info?.proxies && "wireguard" in info.proxies;
  const hasProxy = (info?.proxies ? Object.keys(info.proxies).filter((k) => k !== "wireguard").length > 0 : false)
    || !!(info?.links?.length);

  useEffect(() => {
    if (!info) return;
    if (hasWireguard && !hasProxy) setProtocol("wireguard");
    else if (hasProxy && !hasWireguard) setProtocol("proxy");
  }, [info, hasWireguard, hasProxy]);

  const configAvailable = info?.config_available !== false;
  const blockReason = info?.block_reason;
  const used = info?.used_traffic ?? 0;
  const total = info?.data_limit || 0;
  const pct = total ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const chip = info ? statusChip(lang, info.status) : { label: "—", cls: "neutral" };
  const expiry = info ? relativeDays(info.expire) : null;
  const rtl = lang === "fa";

  const showToast = useCallback((msg: string, kind: "ok" | "error" = "ok") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 2400);
  }, []);

  const pickLang = (code: SubLang) => {
    setLang(code);
    const u = new URL(window.location.href);
    u.searchParams.set("lang", code);
    window.history.replaceState({}, "", u.toString());
  };

  async function copyProxy() {
    const ok = await copyToClipboard(subUrl);
    if (ok) { setCopiedProxy(true); showToast(subT(lang, "copied")); setTimeout(() => setCopiedProxy(false), 1500); }
    else showToast(subT(lang, "copyFailed"), "error");
  }

  async function copyWg() {
    const ok = await copyToClipboard(wgUrl);
    if (ok) { setCopiedWg(true); showToast(subT(lang, "copied")); setTimeout(() => setCopiedWg(false), 1500); }
    else showToast(subT(lang, "copyFailed"), "error");
  }

  const proxyApps = appsFor(platform);
  const wgApps = wgAppsFor(platform);
  const pasteFallback = (n: string) => subT(lang, "pasteFallback").replace("{app}", n);

  if (!token) {
    return <Shell rtl={rtl} lang={lang} onPick={pickLang}><EmptyState msg={subT(lang, "fetchError")} /></Shell>;
  }
  if (err) {
    return (
      <Shell rtl={rtl} lang={lang} onPick={pickLang}>
        <div className="sub-card sub-card-accent-rose p-6 text-center">
          <p className="font-bold text-rose-700">{subT(lang, "fetchError")}</p>
          <p className="mt-1 text-sm text-slate-500">{err}</p>
          <button type="button" onClick={() => loadInfo(token)} className="sub-btn-primary mt-4">{subT(lang, "refresh")}</button>
        </div>
      </Shell>
    );
  }
  if (!info) {
    return (
      <Shell rtl={rtl} lang={lang} onPick={pickLang}>
        <div className="sub-card h-24 animate-pulse" />
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <div className="sub-card h-36 animate-pulse" />
          <div className="sub-card h-36 animate-pulse" />
        </div>
      </Shell>
    );
  }

  const showProxy = hasProxy && (protocol === "proxy" || !hasWireguard);
  const showWg = hasWireguard && (protocol === "wireguard" || !hasProxy);

  return (
    <Shell rtl={rtl} lang={lang} onPick={pickLang}>
      {/* ── Top bar: brand + account + usage (one compact row) ── */}
      <header className="sub-card sub-card-accent-indigo mb-3 flex flex-wrap items-center gap-4 px-4 py-4 sm:px-5">
        <div className="flex items-center gap-3">
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 via-violet-500 to-cyan-500 text-base font-black text-white shadow-lg shadow-indigo-200/80">
            {info.username.slice(0, 2).toUpperCase()}
          </div>
          <div>
            <h1 className="sub-mobile-title text-lg font-extrabold leading-tight text-slate-800 sm:text-xl">{info.username}</h1>
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              <span className={`sub-chip ${chip.cls}`}>
                <span className={`h-1.5 w-1.5 rounded-full bg-current ${configAvailable ? "animate-pulse" : ""}`} />
                {chip.label}
              </span>
              <span className="text-[10px] text-slate-400">
                {info.expire ? formatDate(info.expire) : subT(lang, "noExpiry")}
                {expiry ? ` · ${expiry.text}` : ""}
              </span>
            </div>
          </div>
        </div>

        <div className="hidden h-8 w-px bg-slate-200 lg:block" />

        <UsageBar
          used={used}
          total={total}
          usedLabel={subT(lang, "used")}
          totalLabel={subT(lang, "unlimited")}
          pct={pct}
          exhausted={!configAvailable && blockReason === "data_limit"}
        />

        <div className="hidden items-center gap-2 text-[10px] font-semibold text-slate-400 xl:flex">
          <span className="rounded-md bg-indigo-50 px-2 py-1 text-indigo-600">◆ {subT(lang, "unifiedQuota")}</span>
        </div>
      </header>

      {!configAvailable && (
        <div className={`sub-alert mb-3 ${blockReason === "expired" ? "expired" : "danger"}`}>
          <span className="text-2xl">{blockReason === "expired" ? "⌛" : "⏸"}</span>
          <div className="sub-mobile-text">
            <strong className="sub-mobile-title">
              {blockReason === "data_limit" ? subT(lang, "quotaBannerTitle") :
               blockReason === "expired" ? subT(lang, "expiredBannerTitle") :
               subT(lang, "inactiveBannerTitle")}
            </strong>
            <p className="mt-1 opacity-90">
              {blockReason === "data_limit" ? subT(lang, "quotaBannerBody") :
               blockReason === "expired" ? subT(lang, "expiredBannerBody") :
               subT(lang, "inactiveBannerBody")}
            </p>
          </div>
        </div>
      )}

      {configAvailable && (
        <>
          {hasProxy && hasWireguard && (
            <div className="mb-3 flex gap-1.5 rounded-2xl border border-slate-200/80 bg-white/90 p-1.5 shadow-sm backdrop-blur-sm">
              <button type="button" onClick={() => setProtocol("proxy")} className={`sub-tab flex-1 ${protocol === "proxy" ? "active-proxy" : ""}`}>
                {subT(lang, "tabProxy")}
              </button>
              <button type="button" onClick={() => setProtocol("wireguard")} className={`sub-tab flex-1 ${protocol === "wireguard" ? "active-wg" : ""}`}>
                {subT(lang, "tabWireguard")}
              </button>
            </div>
          )}

          <div className={`sub-card sub-unified-panel ${showWg && !showProxy ? "sub-card-accent-rose" : "sub-card-accent-cyan"}`}>
            <div className="sub-panel-equal">
              {showProxy && (
                <>
                  <div className="sub-panel-apps">
                    <AppsPanel
                      title={subT(lang, "proxyAppsTitle")}
                      count={proxyApps.length}
                      countLabel={subT(lang, "appsSuggested")}
                      platform={platform}
                      onPlatform={setPlatform}
                      embedded
                    >
                      <div className="sub-apps-grid">
                        {proxyApps.map((a) => (
                          <SubAppTile key={a.id} app={a} platform={platform} subUrl={subUrl}
                            importLabel={subT(lang, "import")} downloadLabel={subT(lang, "downloadApp")}
                            pasteFallback={pasteFallback} streisandHint={subT(lang, "streisandHint")}
                            clipboardHint={subT(lang, "clipboardHint")}
                            noResponse={subT(lang, "noAppResponse")} onToast={showToast} />
                        ))}
                      </div>
                    </AppsPanel>
                  </div>
                  <div className="sub-panel-connect">
                    <ConnectCard
                      title={subT(lang, "addToApp")}
                      hint={subT(lang, "proxyAppsHint")}
                      url={subUrl}
                      copyLabel={subT(lang, "copy")}
                      copiedLabel={subT(lang, "copied")}
                      copied={copiedProxy}
                      onCopy={copyProxy}
                      accent="indigo"
                      embedded
                    />
                  </div>
                </>
              )}

              {showWg && (
                <>
                  <div className="sub-panel-apps">
                    <AppsPanel
                      title={subT(lang, "wgAppsTitle")}
                      count={wgApps.length}
                      countLabel={subT(lang, "appsSuggested")}
                      platform={platform}
                      onPlatform={setPlatform}
                      accent="rose"
                      embedded
                    >
                      <div className="sub-apps-grid">
                        {wgApps.map((a) => (
                          <SubWgAppTile key={a.id} app={a} platform={platform} downloadLabel={subT(lang, "downloadApp")} />
                        ))}
                      </div>
                    </AppsPanel>
                  </div>
                  <div className="sub-panel-connect">
                    <ConnectCard
                      title={subT(lang, "wgTitle")}
                      hint={subT(lang, "wgHint")}
                      url={wgUrl}
                      copyLabel={subT(lang, "copy")}
                      copiedLabel={subT(lang, "copied")}
                      copied={copiedWg}
                      onCopy={copyWg}
                      accent="rose"
                      downloadHref={wgUrl}
                      downloadLabel={subT(lang, "wgDownload")}
                      embedded
                    />
                  </div>
                </>
              )}
            </div>
          </div>
        </>
      )}

      {!configAvailable && (
        <div className="sub-card sub-status-only">
          <div className="icon">{blockReason === "expired" ? "⌛" : "🪫"}</div>
          <p className="sub-mobile-title text-base font-bold text-slate-700">{subT(lang, "configsPaused")}</p>
          <p className="sub-mobile-text mt-2 text-sm text-slate-500">{subT(lang, "configsPausedHint")}</p>
        </div>
      )}

      {/* Stats strip — compact horizontal */}
      <div className="mt-3 grid grid-cols-3 gap-2">
        <MiniStat label={subT(lang, "used")} value={bytes(used)} highlight={!configAvailable} />
        <MiniStat label={subT(lang, "total")} value={total ? bytes(total) : subT(lang, "unlimited")} />
        <MiniStat label={subT(lang, "usage")} value={total ? `${pct}%` : "∞"} />
      </div>

      {configAvailable && showProxy && info.links && info.links.length > 0 && (
        <section className="sub-card sub-card-accent-cyan mt-3 p-3">
          <div className="mb-2 text-[10px] font-bold uppercase tracking-widest text-slate-400">
            {subT(lang, "separateConfigs")} ({info.links.length})
          </div>
          <div className="flex flex-col gap-1.5">
            {info.links.map((link, i) => (
              <ConfigRow key={i} link={link} copyLabel={subT(lang, "copy")} closeLabel={subT(lang, "close")} onToast={showToast} />
            ))}
          </div>
        </section>
      )}

      <footer className="mt-4 text-center text-[10px] text-slate-400">
        {subT(lang, "footer")} · {subT(lang, "footerHint")}
      </footer>

      {toast && (
        <div role="status" className={`fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-xl border px-4 py-2.5 text-sm font-semibold shadow-xl ${toast.kind === "ok" ? "border-emerald-200 bg-white text-emerald-700" : "border-rose-200 bg-white text-rose-700"}`}>
          {toast.msg}
        </div>
      )}
    </Shell>
  );
}

function Shell({ children, rtl, lang, onPick }: { children: React.ReactNode; rtl: boolean; lang: SubLang; onPick: (c: SubLang) => void }) {
  return (
    <main className="mx-auto w-full max-w-7xl px-3 py-4 sm:px-5 lg:py-5" dir={rtl ? "rtl" : "ltr"} lang={lang}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-500 shadow-md" />
          <span className="text-sm font-extrabold tracking-tight text-slate-700">NexusPanel</span>
          <span className="hidden text-[10px] font-medium text-slate-400 sm:inline">{subT(lang, "personalSub")}</span>
        </div>
        <div className="flex gap-0.5 rounded-lg border border-slate-200 bg-white p-0.5 shadow-sm">
          {SUB_LANGS.map((l) => (
            <button key={l.code} type="button" onClick={() => onPick(l.code)}
              className={`rounded-md px-2 py-1 text-[10px] font-bold transition ${lang === l.code ? "bg-indigo-100 text-indigo-700" : "text-slate-400 hover:text-slate-600"}`}>
              {l.label}
            </button>
          ))}
        </div>
      </div>
      {children}
    </main>
  );
}

function AppsPanel({ title, count, countLabel, platform, onPlatform, children, accent, embedded }: {
  title: string; count: number; countLabel: string; platform: Platform; onPlatform: (p: Platform) => void;
  children: React.ReactNode; accent?: "rose"; embedded?: boolean;
}) {
  return (
    <div className={embedded ? "" : `sub-card p-3 sm:p-4 ${accent === "rose" ? "sub-card-accent-rose" : "sub-card-accent-cyan"}`}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="sub-mobile-title text-sm font-extrabold text-slate-800">{title}</span>
        <span className="text-[10px] font-medium text-slate-400">{count} {countLabel}</span>
      </div>
      <div className="mb-2 flex flex-wrap gap-1">
        {PLATFORMS.map((p) => (
          <button key={p.id} type="button" onClick={() => onPlatform(p.id)}
            className={`sub-platform-pill ${platform === p.id ? "active" : ""}`}>
            {p.label}
          </button>
        ))}
      </div>
      {children}
    </div>
  );
}

function MiniStat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className={`sub-card px-4 py-3 text-center ${highlight ? "border-rose-200 bg-rose-50/60" : ""}`}>
      <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 sm:text-xs">{label}</div>
      <div className={`mt-1 text-sm font-extrabold tabular-nums sm:text-base ${highlight ? "text-rose-600" : "text-slate-800"}`}>{value}</div>
    </div>
  );
}

function EmptyState({ msg }: { msg: string }) {
  return <div className="sub-card p-6 text-center text-sm text-slate-500">{msg}</div>;
}

function ConfigRow({ link, copyLabel, closeLabel, onToast }: { link: string; copyLabel: string; closeLabel: string; onToast: (m: string, k?: "ok" | "error") => void }) {
  const [copied, setCopied] = useState(false);
  const [showQr, setShowQr] = useState(false);
  const proto = link.includes("://") ? link.split("://")[0] : "link";

  async function copy() {
    const ok = await copyToClipboard(link);
    if (ok) { setCopied(true); onToast(copyLabel); setTimeout(() => setCopied(false), 1500); }
    else onToast(copyLabel, "error");
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-100 bg-slate-50 px-2 py-1.5">
      <span className="rounded-md bg-indigo-100 px-2 py-0.5 text-[10px] font-bold uppercase text-indigo-700">{proto}</span>
      <div dir="ltr" className="min-w-0 flex-1 truncate text-[10px] text-slate-600">{link}</div>
      <button type="button" onClick={() => setShowQr(true)} className="rounded-md bg-white px-2 py-1 text-[10px] font-bold text-slate-500 shadow-sm">QR</button>
      <button type="button" onClick={copy} className={`rounded-md px-2 py-1 text-[10px] font-bold ${copied ? "bg-emerald-100 text-emerald-700" : "bg-white text-indigo-600 shadow-sm"}`}>
        {copied ? "✓" : copyLabel}
      </button>
      {showQr && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/40 p-4 backdrop-blur-sm" onClick={() => setShowQr(false)}>
          <div className="rounded-2xl bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="rounded-xl border p-2"><QR value={link} size={180} /></div>
            <button type="button" onClick={() => setShowQr(false)} className="sub-btn-primary mt-3 w-full">{closeLabel}</button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function SubscribePage() {
  return (
    <Suspense fallback={<div className="p-6 text-center text-slate-400">…</div>}>
      <SubscribeBody />
    </Suspense>
  );
}
