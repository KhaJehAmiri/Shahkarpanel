"use client";

import { useEffect, useMemo, useState } from "react";
import { Copy, Download, ExternalLink, KeyRound, QrCode, Link2, X } from "lucide-react";
import { QR } from "@/components/QR";
import { pt } from "@/lib/portal-i18n";
import { resolveSubscribeBrowserUrl } from "@/lib/subscribe-url";
import {
  buildFriendlyServers,
  groupServersByProtocol,
  isPlainWireguard,
  localizeServers,
  normalizeProtocol,
  protocolLabel,
} from "../servers";
import { usePortal } from "../PortalContext";
import type { FriendlyServer } from "../types";

async function downloadConfBlob(content: string, title: string): Promise<boolean> {
  const safeName =
    (title || "wireguard")
      .replace(/[^\w.\-()\u0600-\u06FF\s]+/g, "")
      .trim()
      .replace(/\s+/g, "-")
      .slice(0, 48) || "wireguard";
  const filename = safeName.endsWith(".conf") ? safeName : `${safeName}.conf`;
  const body = content.trim();
  if (!body) return false;

  const file = new File([body], filename, { type: "application/octet-stream" });
  const nav = navigator as Navigator & {
    canShare?: (data?: ShareData) => boolean;
    share?: (data?: ShareData) => Promise<void>;
  };
  try {
    if (typeof nav.canShare === "function" && nav.canShare({ files: [file] }) && nav.share) {
      await nav.share({ files: [file], title: filename });
      return true;
    }
  } catch {
    /* fall through to anchor download */
  }

  const url = URL.createObjectURL(new Blob([body], { type: "application/octet-stream" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return true;
}

/** Subscription-first connect panel for the selected account. */
export function ConnectPanel() {
  const {
    lang,
    activeUsername,
    configs,
    activeProfile: profile,
    copyText,
    setTab,
    setShopMode,
    setShopStep,
    setRenewUsername,
    busy,
    rotateSub,
    saveCustomSub,
    subMode,
    setSubMode,
    customToken,
    setCustomToken,
    showToast,
  } = usePortal();

  const [showQr, setShowQr] = useState(false);
  const [showIdEditor, setShowIdEditor] = useState(false);
  const [protoId, setProtoId] = useState<string>("");
  const [previewServer, setPreviewServer] = useState<FriendlyServer | null>(null);
  const [dlBusy, setDlBusy] = useState(false);

  useEffect(() => {
    setShowQr(false);
    setShowIdEditor(false);
    setPreviewServer(null);
    setProtoId("");
  }, [activeUsername]);

  const subUrl =
    configs?.public_subscription_url ||
    profile?.public_subscription_url ||
    profile?.subscription_url ||
    "";
  const subscribeBrowserUrl = resolveSubscribeBrowserUrl(subUrl);
  const openInAppHref = configs?.client_subscription_url || subscribeBrowserUrl || "";

  const serversLocalized = useMemo(
    () => localizeServers(buildFriendlyServers(configs), lang),
    [configs, lang],
  );
  const protoGroups = useMemo(() => groupServersByProtocol(serversLocalized), [serversLocalized]);

  useEffect(() => {
    if (!protoGroups.length) {
      setProtoId("");
      return;
    }
    if (!protoId || !protoGroups.some((g) => g.id === protoId)) {
      setProtoId(protoGroups[0].id);
    }
  }, [protoGroups, protoId]);

  const activeLocations = useMemo(() => {
    const g = protoGroups.find((x) => x.id === protoId);
    return g?.items || [];
  }, [protoGroups, protoId]);

  const previewIsWg = previewServer ? isPlainWireguard(previewServer) : false;

  async function handleDownloadConf(server: FriendlyServer) {
    setDlBusy(true);
    try {
      const ok = await downloadConfBlob(server.link, server.technicalTitle || server.country);
      if (ok) showToast(pt(lang, "confDownloaded"));
      else showToast(pt(lang, "confDownloadFailed"));
    } catch {
      showToast(pt(lang, "confDownloadFailed"));
    } finally {
      setDlBusy(false);
    }
  }

  if (!activeUsername) {
    return (
      <section className="p-card p-card-pad">
        <p className="p-muted">{pt(lang, "selectAccount")}</p>
      </section>
    );
  }

  if (!configs) {
    return (
      <section className="p-card p-card-pad">
        <p className="p-muted">{pt(lang, "loading")}</p>
      </section>
    );
  }

  if (!configs.config_available) {
    return (
      <section className="p-card p-card-pad">
        <div className="p-err">
          {pt(lang, "configsBlocked")}
          <div style={{ marginTop: 10 }}>
            <button
              type="button"
              className="p-btn"
              onClick={() => {
                setRenewUsername(activeUsername);
                setShopMode("renew");
                setShopStep("mode");
                setTab("shop");
              }}
            >
              {pt(lang, "goShop")}
            </button>
          </div>
        </div>
      </section>
    );
  }

  return (
    <div className="p-stack">
      <div className="p-page-header" style={{ marginBottom: 4 }}>
        <h2 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 800 }}>{pt(lang, "connectTitle")}</h2>
        <p style={{ margin: "4px 0 0", color: "var(--p-ink-soft)", fontSize: "0.9rem" }}>
          {pt(lang, "configsForAccount")}{" "}
          <strong dir="ltr">{activeUsername}</strong>
        </p>
      </div>

      <section className="p-sub-card">
        <div className="p-sub-card-head">
          <div className="p-sub-card-icon" aria-hidden>
            <Link2 size={22} />
          </div>
          <div className="p-sub-card-titles">
            <h3>{pt(lang, "subscription")}</h3>
            <p>{pt(lang, "subOnlyHint")}</p>
          </div>
        </div>

        <div className="p-sub-url" dir="ltr" title={subUrl}>
          {subUrl || "—"}
        </div>

        <div className="p-sub-actions">
          <button
            type="button"
            className="p-btn p-sub-copy"
            disabled={!subUrl}
            onClick={() => copyText(subUrl, pt(lang, "connectLinkCopied"))}
          >
            <Copy size={16} aria-hidden />
            {pt(lang, "copySub")}
          </button>
          <button
            type="button"
            className={`p-btn ghost${showQr ? " is-active" : ""}`}
            disabled={!subUrl}
            onClick={() => setShowQr((v) => !v)}
          >
            <QrCode size={16} aria-hidden />
            {showQr ? pt(lang, "hideQr") : pt(lang, "showQr")}
          </button>
          {openInAppHref ? (
            <a className="p-btn ghost" href={openInAppHref} target="_blank" rel="noreferrer">
              <ExternalLink size={16} aria-hidden />
              {pt(lang, "openInApp")}
            </a>
          ) : null}
          <button
            type="button"
            className={`p-btn ghost${showIdEditor ? " is-active" : ""}`}
            onClick={() => setShowIdEditor((v) => !v)}
          >
            <KeyRound size={16} aria-hidden />
            {pt(lang, "changeSubId")}
          </button>
        </div>

        {showQr && subUrl ? (
          <div className="p-sub-qr">
            <QR value={subUrl} size={200} />
            <p className="p-muted">{pt(lang, "qrHint")}</p>
          </div>
        ) : null}

        {showIdEditor ? (
          <div className="p-sub-id">
            <div className="p-sub-id-warn">{pt(lang, "subIdDangerHint")}</div>
            <div className="p-seg" role="group">
              <button type="button" className={subMode === "auto" ? "is-on" : ""} onClick={() => setSubMode("auto")}>
                {pt(lang, "subIdAuto")}
              </button>
              <button
                type="button"
                className={subMode === "custom" ? "is-on" : ""}
                onClick={() => setSubMode("custom")}
              >
                {pt(lang, "subIdCustom")}
              </button>
            </div>
            {subMode === "auto" ? (
              <div className="p-sub-id-body">
                <div className="p-sub-id-token" dir="ltr">
                  {profile?.sub_token || "—"}
                </div>
                <button type="button" className="p-btn danger" disabled={busy} onClick={rotateSub}>
                  {busy ? pt(lang, "loading") : pt(lang, "subIdAuto")}
                </button>
              </div>
            ) : (
              <div className="p-sub-id-body">
                <input
                  className="p-input"
                  dir="ltr"
                  value={customToken}
                  placeholder={pt(lang, "subIdPlaceholder")}
                  onChange={(e) => setCustomToken(e.target.value.toLowerCase())}
                />
                <button
                  type="button"
                  className="p-btn"
                  disabled={busy || customToken.trim().length < 8}
                  onClick={saveCustomSub}
                >
                  {busy ? pt(lang, "loading") : pt(lang, "subIdSave")}
                </button>
              </div>
            )}
          </div>
        ) : null}
      </section>

      <section className="p-card p-card-pad">
        <h2 className="p-section-title">{pt(lang, "pickProtocol")}</h2>
        <p className="p-section-desc">{pt(lang, "pickProtocolHint")}</p>

        {protoGroups.length === 0 ? (
          <p className="p-muted">{pt(lang, "noConfigs")}</p>
        ) : (
          <>
            <div className="p-proto-tabs" role="tablist" aria-label={pt(lang, "pickProtocol")}>
              {protoGroups.map((g) => (
                <button
                  key={g.id}
                  type="button"
                  role="tab"
                  aria-selected={protoId === g.id}
                  className={`p-proto-tab${protoId === g.id ? " is-on" : ""}`}
                  onClick={() => {
                    setProtoId(g.id);
                    setPreviewServer(null);
                  }}
                >
                  <span>{protocolLabel(lang, g.id)}</span>
                  <span className="p-proto-tab-count">{g.items.length}</span>
                </button>
              ))}
            </div>

            <div className="p-location-grid" role="list">
              {activeLocations.map((s) => {
                const sameCountry = activeLocations.filter((x) => x.country === s.country).length;
                const label =
                  sameCountry > 1
                    ? `${s.country} ${activeLocations.filter((x) => x.country === s.country).indexOf(s) + 1}`
                    : s.country;
                return (
                  <button
                    key={s.key}
                    type="button"
                    role="listitem"
                    className="p-location-card"
                    onClick={() => setPreviewServer(s)}
                  >
                    <span className="p-location-flag">{s.flag}</span>
                    <strong className="p-location-name">{label || s.technicalTitle}</strong>
                  </button>
                );
              })}
            </div>
          </>
        )}
      </section>

      {previewServer ? (
        <div
          className="p-preview-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label={previewServer.country}
          onClick={() => setPreviewServer(null)}
        >
          <div className="p-preview p-preview-rich" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="p-preview-close"
              aria-label={pt(lang, "cancel")}
              onClick={() => setPreviewServer(null)}
            >
              <X size={18} />
            </button>
            <div className="p-preview-flag">{previewServer.flag}</div>
            <h3>
              {previewServer.flag} {previewServer.country}
            </h3>
            <p className="p-preview-proto">
              {protocolLabel(lang, normalizeProtocol(previewServer.protocolRaw) || (previewServer.key.startsWith("wg-") ? "wireguard" : "other"))}
            </p>

            <div className="p-preview-qr">
              <QR value={previewServer.link} size={200} />
              <p className="p-muted">{pt(lang, "qrHint")}</p>
            </div>

            <div className="p-link-row" style={{ justifyContent: "center", marginTop: 4 }}>
              {previewIsWg ? (
                <button
                  type="button"
                  className="p-btn"
                  disabled={dlBusy}
                  onClick={() => void handleDownloadConf(previewServer)}
                >
                  <Download size={16} aria-hidden />
                  {dlBusy ? pt(lang, "loading") : pt(lang, "downloadConf")}
                </button>
              ) : (
                <button
                  type="button"
                  className="p-btn"
                  onClick={() => {
                    copyText(previewServer.link, pt(lang, "connectLinkCopied"));
                  }}
                >
                  <Copy size={16} aria-hidden />
                  {pt(lang, "copyLink")}
                </button>
              )}
              <button type="button" className="p-btn ghost" onClick={() => setPreviewServer(null)}>
                {pt(lang, "cancel")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
