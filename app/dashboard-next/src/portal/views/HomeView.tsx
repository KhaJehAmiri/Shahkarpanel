"use client";

import { AlertTriangle, Radio, RefreshCw, ShoppingBag, Users } from "lucide-react";
import { bytes, formatDate } from "@/lib/format";
import { pt } from "@/lib/portal-i18n";
import {
  accountHealth,
  daysLeft,
  needsAttention,
  remainingBytes,
  usagePct,
} from "../format";
import { usePortal } from "../PortalContext";
import {
  AccountPickerStrip,
  EmptyState,
  PageHeader,
  StatusBadge,
  UsageMeter,
} from "../components/Shell";

export function HomeView() {
  const {
    lang,
    accounts,
    activeUsername,
    activeProfile: profile,
    setTab,
    setShopMode,
    setShopStep,
    setRenewUsername,
  } = usePortal();

  if (accounts.length === 0) {
    return (
      <div className="p-stack">
        <PageHeader title={pt(lang, "homeTitle")} hint={pt(lang, "homeHint")} />
        <EmptyState
          icon={<ShoppingBag size={24} />}
          title={pt(lang, "homeNoAccount")}
          hint={pt(lang, "homeNoAccountHint")}
          actionLabel={pt(lang, "homeQuickBuy")}
          onAction={() => {
            setShopMode("buy");
            setShopStep("mode");
            setTab("shop");
          }}
        />
      </div>
    );
  }

  const alert = needsAttention(profile);
  const pct = usagePct(profile);
  const rem = remainingBytes(profile);
  const days = daysLeft(profile?.expire);
  const health = profile
    ? accountHealth({
        status: profile.status,
        used_traffic: profile.used_traffic,
        data_limit: profile.data_limit,
        expire: profile.expire,
      })
    : "ok";

  return (
    <div className="p-stack">
      <PageHeader title={pt(lang, "homeTitle")} hint={pt(lang, "homeHint")} />

      <AccountPickerStrip />

      {alert === "expired" || health === "danger" ? (
        <div className="p-alert danger">
          <AlertTriangle size={20} />
          <div>
            {alert === "expired" ? pt(lang, "homeAlertExpired") : pt(lang, "homeAlertLowData")}
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
                {pt(lang, "homeQuickRenew")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {alert === "low_data" && health !== "danger" ? (
        <div className="p-alert warn">
          <AlertTriangle size={20} />
          <span>{pt(lang, "homeAlertLowData")}</span>
        </div>
      ) : null}
      {alert === "expiring" && health !== "danger" ? (
        <div className="p-alert warn">
          <AlertTriangle size={20} />
          <span>{pt(lang, "homeAlertExpiring")}</span>
        </div>
      ) : null}

      {profile ? (
        <div className="p-home-hero">
          <section className="p-card p-card-pad p-home-status">
            <div className="p-kicker">{pt(lang, "activeAccount")}</div>
            <h2 dir="ltr">{profile.username}</h2>
            <div className="p-home-meta">
              <StatusBadge status={profile.status} />
              <span className={`p-health-pill ${health}`}>
                {health === "danger"
                  ? pt(lang, "healthDanger")
                  : health === "warn"
                    ? pt(lang, "healthWarn")
                    : pt(lang, "healthOk")}
              </span>
              <span className={`p-chip ${profile.online ? "ok" : ""}`}>
                {profile.online ? pt(lang, "online") : pt(lang, "offline")}
              </span>
              {days != null ? (
                <span className={`p-chip ${days <= 7 ? "warn" : ""}`}>
                  {days > 0 ? `${days} ${pt(lang, "daysLeft")}` : pt(lang, "expired")}
                </span>
              ) : (
                <span className="p-chip">{pt(lang, "never")}</span>
              )}
            </div>
            {profile.note ? (
              <div className="p-note" style={{ marginBottom: 14 }}>
                <strong>{pt(lang, "supportNote")}: </strong>
                {profile.note}
              </div>
            ) : null}
            <UsageMeter
              pct={profile.data_limit ? pct : 0}
              usedLabel={bytes(profile.used_traffic)}
              limitLabel={profile.data_limit ? bytes(profile.data_limit) : pt(lang, "unlimited")}
            />
          </section>

          <section className="p-card p-card-pad">
            <div className="p-stats">
              <div className="p-stat">
                <div className="label">{pt(lang, "dataLeft")}</div>
                <div className="value">{rem != null ? bytes(rem) : pt(lang, "unlimited")}</div>
              </div>
              <div className="p-stat">
                <div className="label">{pt(lang, "timeLeft")}</div>
                <div className="value">
                  {days != null
                    ? days > 0
                      ? `${days} ${pt(lang, "days")}`
                      : pt(lang, "expired")
                    : pt(lang, "never")}
                </div>
              </div>
              <div className="p-stat">
                <div className="label">{pt(lang, "devices")}</div>
                <div className="value">
                  {profile.online_devices ?? 0}
                  {profile.device_limit ? ` / ${profile.device_limit}` : ""}
                </div>
              </div>
              <div className="p-stat">
                <div className="label">{pt(lang, "expire")}</div>
                <div className="value" style={{ fontSize: "0.88rem" }}>
                  {profile.expire ? formatDate(profile.expire) : pt(lang, "never")}
                </div>
              </div>
            </div>
            {!alert && health === "ok" ? (
              <p className="p-muted" style={{ marginTop: 14, marginBottom: 0 }}>
                {pt(lang, "allGood")}
              </p>
            ) : null}
          </section>
        </div>
      ) : null}

      <div className="p-quick-grid">
        <button type="button" className="p-quick-card cta" onClick={() => setTab("accounts")}>
          <span className="icon">
            <Radio size={22} />
          </span>
          {pt(lang, "homeQuickConnect")}
        </button>
        {health === "danger" ? (
          <button
            type="button"
            className="p-quick-card"
            onClick={() => {
              setRenewUsername(activeUsername);
              setShopMode("renew");
              setShopStep("mode");
              setTab("shop");
            }}
          >
            <span className="icon">
              <RefreshCw size={22} />
            </span>
            {pt(lang, "homeQuickRenew")}
          </button>
        ) : null}
        <button
          type="button"
          className="p-quick-card"
          onClick={() => {
            setShopMode("buy");
            setShopStep("mode");
            setTab("shop");
          }}
        >
          <span className="icon">
            <ShoppingBag size={22} />
          </span>
          {pt(lang, "homeQuickBuy")}
        </button>
      </div>

      <button type="button" className="p-btn ghost" onClick={() => setTab("accounts")}>
        <Users size={16} />
        {pt(lang, "homeViewAccounts")}
      </button>
    </div>
  );
}
