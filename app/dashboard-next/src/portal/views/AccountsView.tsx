"use client";

import { ShoppingBag } from "lucide-react";
import { bytes, formatDate } from "@/lib/format";
import { pt } from "@/lib/portal-i18n";
import { accountHealth, healthRemainingLabel, remainingDataPct } from "../format";
import { usePortal } from "../PortalContext";
import { ConnectPanel } from "../components/ConnectPanel";
import { EmptyState, PageHeader, StatusBadge } from "../components/Shell";

export function AccountsView() {
  const {
    lang,
    accounts,
    activeUsername,
    setActiveUsername,
    activeProfile: profile,
    setTab,
    setShopMode,
    setShopStep,
    setRenewUsername,
    deleteConfirm,
    setDeleteConfirm,
    deleteAccount,
    busy,
  } = usePortal();

  const selected = accounts.find((a) => a.username === activeUsername);
  const selectedHealth = selected ? accountHealth(selected) : "ok";

  return (
    <div className="p-stack">
      <PageHeader title={pt(lang, "nav_connect")} hint={pt(lang, "accountsMergedHint")} />

      {accounts.length === 0 ? (
        <EmptyState
          icon={<ShoppingBag size={24} />}
          title={pt(lang, "noAccounts")}
          actionLabel={pt(lang, "accountsEmptyCta")}
          onAction={() => {
            setShopMode("buy");
            setShopStep("mode");
            setTab("shop");
          }}
        />
      ) : (
        <>
          <section className="p-card p-card-pad">
            <div className="p-acct-list" role="listbox" aria-label={pt(lang, "chooseAccount")}>
              {accounts.map((a) => {
                const health = accountHealth(a);
                const dataRem = remainingDataPct(a.used_traffic, a.data_limit);
                const isSelected = activeUsername === a.username;
                return (
                  // Row is a div, not a button: it holds its own "renew" button
                  // and nested buttons are invalid HTML (breaks taps on mobile).
                  <div
                    key={a.username}
                    role="option"
                    tabIndex={0}
                    aria-selected={isSelected}
                    className={`p-acct-row health-${health}${isSelected ? " is-selected" : ""}`}
                    onClick={() => setActiveUsername(a.username)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setActiveUsername(a.username);
                      }
                    }}
                  >
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div className="p-acct-row-name" dir="ltr">
                        {a.username}
                      </div>
                      <div className="p-acct-row-meta">
                        <StatusBadge status={a.status} />
                        {a.is_portal_login ? (
                          <span className="p-chip ok">{pt(lang, "portalLoginBadge")}</span>
                        ) : null}
                        <span className={`p-chip ${a.online ? "ok" : ""}`}>
                          {a.online ? pt(lang, "online") : pt(lang, "offline")}
                        </span>
                        <span>
                          {bytes(a.used_traffic)} /{" "}
                          {a.data_limit ? bytes(a.data_limit) : pt(lang, "unlimited")}
                        </span>
                        {dataRem != null ? (
                          <span className={`p-chip ${health === "ok" ? "" : health}`}>
                            {Math.round(dataRem)}% {pt(lang, "remaining")}
                          </span>
                        ) : null}
                        {a.expire ? (
                          <span>
                            {pt(lang, "expire")}: {formatDate(a.expire)}
                          </span>
                        ) : null}
                      </div>
                      {health !== "ok" ? (
                        <div className="p-muted" style={{ marginTop: 6, fontSize: "0.78rem" }}>
                          {healthRemainingLabel(lang, a)}
                        </div>
                      ) : null}
                    </div>
                    <div className="p-acct-row-side">
                      <span className={`p-health-pill ${health}`}>
                        {health === "danger"
                          ? pt(lang, "healthDanger")
                          : health === "warn"
                            ? pt(lang, "healthWarn")
                            : pt(lang, "healthOk")}
                      </span>
                      {health === "danger" ? (
                        <button
                          type="button"
                          className="p-btn"
                          style={{ padding: "7px 12px", fontSize: "0.8rem" }}
                          onClick={(e) => {
                            e.stopPropagation();
                            setActiveUsername(a.username);
                            setRenewUsername(a.username);
                            setShopMode("renew");
                            setShopStep("mode");
                            setTab("shop");
                          }}
                        >
                          {pt(lang, "goRenew")}
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>

            {profile && selected ? (
              <div className="p-acct-actions">
                {selectedHealth === "danger" ? (
                  <button
                    type="button"
                    className="p-btn"
                    onClick={() => {
                      setRenewUsername(profile.username);
                      setShopMode("renew");
                      setShopStep("mode");
                      setTab("shop");
                    }}
                  >
                    {pt(lang, "goRenew")}
                  </button>
                ) : null}
                {!selected.is_portal_login ? (
                  deleteConfirm === profile.username ? (
                    <>
                      <span className="p-muted" style={{ fontSize: "0.82rem", alignSelf: "center" }}>
                        {pt(lang, "confirmDelete")}
                      </span>
                      <button
                        type="button"
                        className="p-btn danger"
                        disabled={busy}
                        onClick={() => deleteAccount(profile.username)}
                      >
                        {busy ? pt(lang, "loading") : pt(lang, "deleteAccount")}
                      </button>
                      <button type="button" className="p-btn ghost" onClick={() => setDeleteConfirm(null)}>
                        {pt(lang, "cancel")}
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className="p-btn danger"
                      onClick={() => setDeleteConfirm(profile.username)}
                    >
                      {pt(lang, "deleteAccount")}
                    </button>
                  )
                ) : null}
              </div>
            ) : null}
          </section>

          {activeUsername ? <ConnectPanel /> : null}
        </>
      )}
    </div>
  );
}
