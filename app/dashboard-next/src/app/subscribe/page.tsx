"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { ConnectCard } from "@/components/subscribe/ConnectCard";
import { SubAppTile } from "@/components/subscribe/SubAppTile";
import { SubWgAppTile } from "@/components/subscribe/SubWgAppTile";
import { SubQuicAppTile } from "@/components/subscribe/SubQuicAppTile";
import { UsageBar } from "@/components/subscribe/UsageBar";
import { QR } from "@/components/QR";
import { PLATFORMS, type Platform, appsFor, detectPlatform } from "@/lib/apps";
import { wgAppsFor } from "@/lib/wg-apps";
import { quicAppsFor, type QuicProtocol } from "@/lib/quic-apps";
import { copyToClipboard } from "@/lib/clipboard";
import { bytes, formatDate, relativeDays } from "@/lib/format";
import { SUB_LANGS, SubLang, detectSubLang, t as subT } from "@/lib/subscribe-i18n";
import { resolveClientImportUrl, resolvePublicSubUrl, resolveSingboxSubUrl, resolveWgUrl } from "@/lib/subscribe-url";
import { applySubTheme, detectSubTheme, type SubTheme } from "@/lib/sub-theme";

type ProtocolTab = "proxy" | "wireguard" | "quic";

interface SubInfo {
  username: string;
  status: string;
  used_traffic: number;
  overage_traffic?: number;
  data_limit: number | null;
  expire: number | null;
  links?: string[];
  link_items?: Array<{
    link: string;
    protocol: string;
    remark: string;
    region_flag?: string;
    region_name?: string;
    address_hint?: string;
  }>;
  proxies?: Record<string, unknown>;
  config_available?: boolean;
  block_reason?: string | null;
  public_subscription_url?: string;
  client_subscription_url?: string;
  subscription_profile_title?: string;
  hysteria2_link?: string | null;
  tuic_link?: string | null;
  anytls_link?: string | null;
  wireguard_uri?: string | null;
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
  const [copiedWgUri, setCopiedWgUri] = useState(false);
  const [copiedAwg, setCopiedAwg] = useState(false);
  const [copiedHy2, setCopiedHy2] = useState(false);
  const [copiedTuic, setCopiedTuic] = useState(false);
  const [copiedAnytls, setCopiedAnytls] = useState(false);
  const [hy2Fetched, setHy2Fetched] = useState("");
  const [tuicFetched, setTuicFetched] = useState("");
  const [anytlsFetched, setAnytlsFetched] = useState("");
  const [wgConfPlain, setWgConfPlain] = useState("");
  const [wgConfAwg, setWgConfAwg] = useState("");

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
  const clientImportUrl = useMemo(() => resolveClientImportUrl(info, token), [info, token]);
  const profileTitle = info?.subscription_profile_title?.trim() || "NexusPanel";
  const singboxSubUrl = useMemo(() => resolveSingboxSubUrl(subUrl), [subUrl]);
  const wgUrl = useMemo(() => resolveWgUrl(subUrl, "plain"), [subUrl]);
  const awgUrl = useMemo(() => resolveWgUrl(subUrl, "awg"), [subUrl]);
  const wgImportUri = info?.wireguard_uri?.trim() || "";
  const hy2ShareLink = (info?.hysteria2_link || hy2Fetched || "").trim();
  const tuicShareLink = (info?.tuic_link || tuicFetched || "").trim();
  const anytlsShareLink = (info?.anytls_link || anytlsFetched || "").trim();

  useEffect(() => {
    if (!token || !info || info.config_available === false) {
      setHy2Fetched("");
      setTuicFetched("");
      setAnytlsFetched("");
      return;
    }
    const hasHy2 = !!info.proxies && "hysteria2" in info.proxies;
    const hasT = !!info.proxies && "tuic" in info.proxies;
    const hasAt = !!info.proxies && "anytls" in info.proxies;
    if (hasHy2 && !info.hysteria2_link) {
      fetch(`/sub/${token}/hysteria2`)
        .then(async (r) => (r.ok ? r.text() : ""))
        .then((t) => setHy2Fetched(t.trim()))
        .catch(() => setHy2Fetched(""));
    } else {
      setHy2Fetched("");
    }
    if (hasT && !info.tuic_link) {
      fetch(`/sub/${token}/tuic`)
        .then(async (r) => (r.ok ? r.text() : ""))
        .then((t) => setTuicFetched(t.trim()))
        .catch(() => setTuicFetched(""));
    } else {
      setTuicFetched("");
    }
    if (hasAt && !info.anytls_link) {
      fetch(`/sub/${token}/anytls`)
        .then(async (r) => (r.ok ? r.text() : ""))
        .then((t) => setAnytlsFetched(t.trim()))
        .catch(() => setAnytlsFetched(""));
    } else {
      setAnytlsFetched("");
    }
  }, [token, info]);

  useEffect(() => {
    if (!token || !info || info.config_available === false) {
      setWgConfPlain("");
      setWgConfAwg("");
      return;
    }
    if (!info.proxies || !("wireguard" in info.proxies)) {
      setWgConfPlain("");
      setWgConfAwg("");
      return;
    }
    fetch(`/sub/${token}/wireguard`)
      .then(async (r) => (r.ok ? r.text() : ""))
      .then((t) => setWgConfPlain(t.trim()))
      .catch(() => setWgConfPlain(""));
    fetch(`/sub/${token}/wireguard?variant=awg`)
      .then(async (r) => (r.ok ? r.text() : ""))
      .then((t) => setWgConfAwg(t.trim()))
      .catch(() => setWgConfAwg(""));
  }, [token, info]);

  const hasWireguard = !!info?.proxies && "wireguard" in info.proxies;
  const hasHysteria2 = !!info?.proxies && "hysteria2" in info.proxies;
  const hasTuic = !!info?.proxies && "tuic" in info.proxies;
  const hasAnytls = !!info?.proxies && "anytls" in info.proxies;
  const hasQuic = hasHysteria2 || hasTuic || hasAnytls;
  const hasProxy = (info?.proxies
    ? Object.keys(info.proxies).filter((k) => !["wireguard", "hysteria2", "tuic", "anytls"].includes(k)).length > 0
    : false) || !!(info?.links?.length);

  useEffect(() => {
    if (!info) return;
    const modes = [hasProxy, hasWireguard, hasQuic].filter(Boolean).length;
    if (modes === 1) {
      if (hasWireguard) setProtocol("wireguard");
      else if (hasQuic) setProtocol("quic");
      else setProtocol("proxy");
    }
  }, [info, hasWireguard, hasProxy, hasQuic]);

  const configAvailable = info?.config_available !== false;
  const blockReason = info?.block_reason;
  const used = info?.used_traffic ?? 0;
  const overage = info?.overage_traffic ?? 0;
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
    const ok = await copyToClipboard(wgConfPlain || wgUrl);
    if (ok) { setCopiedWg(true); showToast(subT(lang, "copied")); setTimeout(() => setCopiedWg(false), 1500); }
    else showToast(subT(lang, "copyFailed"), "error");
  }

  async function copyWgUri() {
    const ok = await copyToClipboard(wgImportUri);
    if (ok) { setCopiedWgUri(true); showToast(subT(lang, "copied")); setTimeout(() => setCopiedWgUri(false), 1500); }
    else showToast(subT(lang, "copyFailed"), "error");
  }

  async function copyAwg() {
    const ok = await copyToClipboard(wgConfAwg || awgUrl);
    if (ok) { setCopiedAwg(true); showToast(subT(lang, "copied")); setTimeout(() => setCopiedAwg(false), 1500); }
    else showToast(subT(lang, "copyFailed"), "error");
  }

  async function copyHy2() {
    const ok = await copyToClipboard(hy2ShareLink);
    if (ok) { setCopiedHy2(true); showToast(subT(lang, "copied")); setTimeout(() => setCopiedHy2(false), 1500); }
    else showToast(subT(lang, "copyFailed"), "error");
  }

  async function copyTuic() {
    const ok = await copyToClipboard(tuicShareLink);
    if (ok) { setCopiedTuic(true); showToast(subT(lang, "copied")); setTimeout(() => setCopiedTuic(false), 1500); }
    else showToast(subT(lang, "copyFailed"), "error");
  }

  async function copyAnytls() {
    const ok = await copyToClipboard(anytlsShareLink);
    if (ok) { setCopiedAnytls(true); showToast(subT(lang, "copied")); setTimeout(() => setCopiedAnytls(false), 1500); }
    else showToast(subT(lang, "copyFailed"), "error");
  }

  const proxyApps = appsFor(platform);
  const wgApps = wgAppsFor(platform);
  const quicProtocols: QuicProtocol[] = [
    ...(hasHysteria2 ? (["hysteria2"] as QuicProtocol[]) : []),
    ...(hasTuic ? (["tuic"] as QuicProtocol[]) : []),
    ...(hasAnytls ? (["anytls"] as QuicProtocol[]) : []),
  ];
  const quicApps = quicAppsFor(platform, quicProtocols);
  const quicImportUrl = hasHysteria2 ? hy2ShareLink : hasTuic ? tuicShareLink : anytlsShareLink;
  const pasteFallback = (n: string) => subT(lang, "pasteFallback").replace("{app}", n);

  if (!token) {
    return <Shell rtl={rtl} lang={lang} onPick={pickLang}><EmptyState msg={subT(lang, "fetchError")} /></Shell>;
  }
  if (err) {
    return (
      <Shell rtl={rtl} lang={lang} onPick={pickLang}>
        <div className="sub-card sub-card-accent-rose p-6 text-center">
          <p className="sub-heading" style={{ color: "#be123c" }}>{subT(lang, "fetchError")}</p>
          <p className="sub-text-muted" style={{ marginTop: 4, fontSize: 13 }}>{err}</p>
          <button type="button" onClick={() => loadInfo(token)} className="sub-btn-primary" style={{ marginTop: 16 }}>{subT(lang, "refresh")}</button>
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

  const tabCount = [hasProxy, hasWireguard, hasQuic].filter(Boolean).length;
  const showProxy = hasProxy && (protocol === "proxy" || tabCount === 1);
  const showWg = hasWireguard && (protocol === "wireguard" || (tabCount === 1 && !hasProxy));
  const showQuic = hasQuic && (protocol === "quic" || (tabCount === 1 && !hasProxy && !hasWireguard));

  return (
    <Shell rtl={rtl} lang={lang} onPick={pickLang}>
      {/* ── Top bar: brand + account + usage (one compact row) ── */}
      <header className="sub-card sub-card-accent-indigo sub-hero-card">
        <div className="flex items-center gap-3">
          <div className="sub-avatar">{info.username.slice(0, 2).toUpperCase()}</div>
          <div>
            <h1 className="sub-mobile-title sub-hero-name">{info.username}</h1>
            <div className="sub-hero-meta">
              <span className={`sub-chip ${chip.cls}`}>
                <span className={`inline-block h-1.5 w-1.5 rounded-full bg-current ${configAvailable ? "animate-pulse" : ""}`} />
                {chip.label}
              </span>
              <span className="sub-text-dim" style={{ fontSize: 10 }}>
                {info.expire ? formatDate(info.expire) : subT(lang, "noExpiry")}
                {expiry ? ` · ${expiry.text}` : ""}
              </span>
            </div>
          </div>
        </div>

        <UsageBar
          used={used}
          total={total}
          usedLabel={subT(lang, "used")}
          totalLabel={subT(lang, "unlimited")}
          pct={pct}
          exhausted={!configAvailable && blockReason === "data_limit"}
          overage={overage}
          overageLabel={subT(lang, "overage")}
        />

        <span className="sub-badge-inline">◆ {subT(lang, "unifiedQuota")}</span>
      </header>

      {configAvailable && hasProxy && subUrl && (
        <div className="sub-callout-info" role="note">
          <strong>{subT(lang, "clientImportTitle")}</strong>
          <p style={{ margin: "6px 0 0", opacity: 0.9 }}>{subT(lang, "clientImportHint")}</p>
          <code dir="ltr">{subUrl}</code>
        </div>
      )}

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
          {tabCount > 1 && (
            <div className="sub-tabs">
              {hasProxy && (
                <button type="button" onClick={() => setProtocol("proxy")} className={`sub-tab ${protocol === "proxy" ? "active-proxy" : ""}`}>
                  {subT(lang, "tabProxy")}
                </button>
              )}
              {hasWireguard && (
                <button type="button" onClick={() => setProtocol("wireguard")} className={`sub-tab ${protocol === "wireguard" ? "active-wg" : ""}`}>
                  {subT(lang, "tabWireguard")}
                </button>
              )}
              {hasQuic && (
                <button type="button" onClick={() => setProtocol("quic")} className={`sub-tab ${protocol === "quic" ? "active-quic" : ""}`}>
                  {subT(lang, "tabQuic")}
                </button>
              )}
            </div>
          )}

          <div className={`sub-card sub-unified-panel ${showWg && !showProxy && !showQuic ? "sub-card-accent-rose" : showQuic && !showProxy && !showWg ? "sub-card-accent-violet" : "sub-card-accent-cyan"}`}>
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
                          <SubAppTile key={a.id} app={a} platform={platform} subUrl={clientImportUrl || subUrl} profileName={profileTitle}
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

              {showQuic && (
                <>
                  <div className="sub-panel-apps">
                    <AppsPanel
                      title={subT(lang, "quicAppsTitle")}
                      count={quicApps.length}
                      countLabel={subT(lang, "appsSuggested")}
                      platform={platform}
                      onPlatform={setPlatform}
                      embedded
                    >
                      <div className="sub-apps-grid">
                        {quicApps.map((a) => (
                          <SubQuicAppTile
                            key={a.id}
                            app={a}
                            platform={platform}
                            shareUrl={quicImportUrl}
                            singboxSubUrl={singboxSubUrl}
                            importLabel={subT(lang, "import")}
                            downloadLabel={subT(lang, "downloadApp")}
                            pasteFallback={pasteFallback}
                            clipboardHint={subT(lang, "clipboardHint")}
                            noResponse={subT(lang, "noAppResponse")}
                            onToast={showToast}
                          />
                        ))}
                      </div>
                    </AppsPanel>
                  </div>
                  <div className="sub-panel-connect sub-stack" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {hasHysteria2 && (
                      <ConnectCard
                        title={subT(lang, "hy2Title")}
                        hint={`${subT(lang, "hy2Hint")} ${subT(lang, "hy2InsecureHint")}`}
                        url={hy2ShareLink}
                        copyLabel={subT(lang, "copy")}
                        copiedLabel={subT(lang, "copied")}
                        copied={copiedHy2}
                        onCopy={copyHy2}
                        accent="indigo"
                        embedded
                      />
                    )}
                    {hasTuic && (
                      <div className="sub-callout-warn">
                        {subT(lang, "tuicIranWarning")}
                      </div>
                    )}
                    {hasTuic && (
                      <ConnectCard
                        title={subT(lang, "tuicTitle")}
                        hint={subT(lang, "tuicHint")}
                        url={tuicShareLink}
                        copyLabel={subT(lang, "copy")}
                        copiedLabel={subT(lang, "copied")}
                        copied={copiedTuic}
                        onCopy={copyTuic}
                        accent="indigo"
                        embedded
                      />
                    )}
                    {hasAnytls && (
                      <ConnectCard
                        title={subT(lang, "anytlsTitle")}
                        hint={subT(lang, "anytlsHint")}
                        url={anytlsShareLink}
                        copyLabel={subT(lang, "copy")}
                        copiedLabel={subT(lang, "copied")}
                        copied={copiedAnytls}
                        onCopy={copyAnytls}
                        accent="indigo"
                        embedded
                      />
                    )}
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
                  <div className="sub-panel-connect sub-connect-stack">
                    <ConnectCard
                      title={subT(lang, "wgTitle")}
                      hint={subT(lang, "wgHint")}
                      url={wgUrl}
                      qrValue={wgConfPlain || undefined}
                      displayValue={wgConfPlain ? subT(lang, "wgConfScan") : wgUrl}
                      copyLabel={subT(lang, "copy")}
                      copiedLabel={subT(lang, "copied")}
                      copied={copiedWg}
                      onCopy={copyWg}
                      accent="rose"
                      downloadHref={wgUrl}
                      downloadLabel={subT(lang, "wgDownload")}
                      qrLayout="stacked"
                      qrEnlargeLabel={subT(lang, "qrEnlarge")}
                      closeLabel={subT(lang, "close")}
                    />
                    {wgImportUri && (
                      <ConnectCard
                        title={subT(lang, "wgUriTitle")}
                        hint={subT(lang, "wgUriHint")}
                        url={wgImportUri}
                        copyLabel={subT(lang, "copy")}
                        copiedLabel={subT(lang, "copied")}
                        copied={copiedWgUri}
                        onCopy={copyWgUri}
                        accent="rose"
                        qrLayout="stacked"
                        qrEnlargeLabel={subT(lang, "qrEnlarge")}
                        closeLabel={subT(lang, "close")}
                      />
                    )}
                    <ConnectCard
                      title={subT(lang, "wgAwgTitle")}
                      hint={subT(lang, "wgAwgHint")}
                      url={awgUrl}
                      qrValue={wgConfAwg || undefined}
                      displayValue={wgConfAwg ? subT(lang, "wgConfScan") : awgUrl}
                      copyLabel={subT(lang, "copy")}
                      copiedLabel={subT(lang, "copied")}
                      copied={copiedAwg}
                      onCopy={copyAwg}
                      accent="rose"
                      downloadHref={awgUrl}
                      downloadLabel={subT(lang, "wgDownload")}
                      qrLayout="stacked"
                      qrEnlargeLabel={subT(lang, "qrEnlarge")}
                      closeLabel={subT(lang, "close")}
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
          <p className="sub-mobile-title sub-heading" style={{ fontSize: 16 }}>{subT(lang, "configsPaused")}</p>
          <p className="sub-mobile-text sub-text-muted" style={{ marginTop: 8, fontSize: 13 }}>{subT(lang, "configsPausedHint")}</p>
        </div>
      )}

      {/* Stats strip — compact horizontal */}
      <div className="mt-3 grid grid-cols-3 gap-2">
        <MiniStat label={subT(lang, "used")} value={bytes(used)} highlight={!configAvailable} />
        <MiniStat label={subT(lang, "total")} value={total ? bytes(total) : subT(lang, "unlimited")} />
        <MiniStat label={subT(lang, "usage")} value={total ? `${pct}%` : "∞"} />
      </div>

      {configAvailable && showProxy && (info.link_items?.length || (info.links && info.links.length > 0)) && (
        <section className="sub-card sub-card-accent-cyan" style={{ marginTop: 12, padding: 12 }}>
          <div className="sub-text-muted" style={{ marginBottom: 8, fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em" }}>
            {subT(lang, "separateConfigs")} ({(info.link_items?.length || info.links?.length || 0)})
          </div>
          <div className="sub-config-account-meta">
            <span>{subT(lang, "configQuota")}: <b>{bytes(used)}</b>{total ? ` / ${bytes(total)}` : ` · ${subT(lang, "unlimited")}`}</span>
            <span>{subT(lang, "configExpire")}: <b>{info.expire ? formatDate(info.expire) : subT(lang, "noExpiry")}</b></span>
          </div>
          <p className="sub-config-account-hint">{subT(lang, "configAccountMeta")}</p>
          <div className="flex flex-col gap-1.5">
            {(info.link_items?.length ? info.link_items : (info.links || []).map((link) => ({ link, protocol: link.split("://")[0] || "link", remark: "", region_flag: "", region_name: "", address_hint: "" }))).map((item, i) => (
              <ConfigRow key={i} item={item} copyLabel={subT(lang, "copy")} closeLabel={subT(lang, "close")} qrLabel={subT(lang, "qrLabel")} onToast={showToast} />
            ))}
          </div>
        </section>
      )}

      <footer className="sub-footer">
        {subT(lang, "footer")} · {subT(lang, "footerHint")}
      </footer>

      {toast && (
        <div role="status" className={`sub-toast ${toast.kind === "ok" ? "ok" : "error"}`}>
          {toast.msg}
        </div>
      )}
    </Shell>
  );
}

function Shell({ children, rtl, lang, onPick }: { children: React.ReactNode; rtl: boolean; lang: SubLang; onPick: (c: SubLang) => void }) {
  const [subTheme, setSubTheme] = useState<SubTheme>("light");

  useEffect(() => {
    setSubTheme(detectSubTheme());
  }, []);

  const toggleTheme = () => {
    const next = subTheme === "dark" ? "light" : "dark";
    setSubTheme(next);
    applySubTheme(next);
  };

  return (
    <main className="sub-shell" dir={rtl ? "rtl" : "ltr"} lang={lang}>
      <div className="sub-brand-row">
        <div className="sub-brand">
          <div className="sub-brand-mark" />
          <div>
            <div className="sub-brand-name">NexusPanel</div>
            <div className="sub-brand-tag">{subT(lang, "personalSub")}</div>
          </div>
        </div>
        <div className="sub-toolbar">
          <button type="button" className="sub-theme-btn" onClick={toggleTheme} aria-label="Theme">
            {subTheme === "dark" ? "☀" : "☾"}
          </button>
          <div className="sub-lang-switch">
            {SUB_LANGS.map((l) => (
              <button key={l.code} type="button" onClick={() => onPick(l.code)}
                className={`sub-lang-btn ${lang === l.code ? "active" : ""}`}>
                {l.label}
              </button>
            ))}
          </div>
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
        <span className="sub-mobile-title sub-heading" style={{ fontSize: 14 }}>{title}</span>
        <span className="sub-text-dim" style={{ fontSize: 10 }}>{count} {countLabel}</span>
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
    <div className={`sub-card sub-ministat ${highlight ? "highlight" : ""}`}>
      <div className="sub-ministat-k">{label}</div>
      <div className="sub-ministat-v">{value}</div>
    </div>
  );
}

function EmptyState({ msg }: { msg: string }) {
  return <div className="sub-card sub-ministat"><p className="sub-text-muted" style={{ fontSize: 13 }}>{msg}</p></div>;
}

function ConfigRow({ item, copyLabel, closeLabel, qrLabel, onToast }: {
  item: { link: string; protocol: string; remark: string; region_flag?: string; region_name?: string; address_hint?: string };
  copyLabel: string; closeLabel: string; qrLabel: string; onToast: (m: string, k?: "ok" | "error") => void;
}) {
  const [copied, setCopied] = useState(false);
  const [showQr, setShowQr] = useState(false);
  const link = item.link;
  const proto = (item.protocol || link.split("://")[0] || "link").toUpperCase();
  const title = item.remark || item.region_name || proto;
  const flag = item.region_flag || "";
  let addressHint = item.address_hint || "";
  if (!addressHint && link.includes("@")) {
    const hostPart = link.split("@")[1]?.split(/[?#]/)[0] || "";
    const host = hostPart.split(":")[0] || "";
    if (host.includes(".")) {
      const p = host.split(".");
      addressHint = p.length === 4 ? `${p[0]}.****.${p[3]}` : host;
    } else if (host) {
      addressHint = `${host.slice(0, 3)}****`;
    }
  }

  async function copy() {
    const ok = await copyToClipboard(link);
    if (ok) { setCopied(true); onToast(copyLabel); setTimeout(() => setCopied(false), 1500); }
    else onToast(copyLabel, "error");
  }

  return (
    <div className="sub-config-row">
      <span className="sub-config-proto">{proto}</span>
      {flag ? <span className="sub-config-flag" aria-hidden>{flag}</span> : null}
      <div className="sub-config-main">
        <div className="sub-config-title">{title}</div>
        {addressHint ? <div dir="ltr" className="sub-config-link">{addressHint}</div> : null}
      </div>
      <button type="button" onClick={() => setShowQr(true)} className="sub-config-btn">{qrLabel}</button>
      <button type="button" onClick={copy} className={`sub-config-btn copy ${copied ? "copied" : ""}`}>
        {copied ? "✓" : copyLabel}
      </button>
      {showQr && (
        <div className="sub-qr-modal" onClick={() => setShowQr(false)}>
          <div className="sub-qr-modal-inner" onClick={(e) => e.stopPropagation()}>
            <div className="sub-connect-qr-box"><QR value={link} size={180} /></div>
            <button type="button" onClick={() => setShowQr(false)} className="sub-btn-primary" style={{ marginTop: 12, width: "100%" }}>{closeLabel}</button>
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
