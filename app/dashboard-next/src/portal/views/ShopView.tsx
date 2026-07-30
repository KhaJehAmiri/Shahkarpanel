"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, ChevronLeft, PackagePlus, RefreshCw } from "lucide-react";
import { bytes } from "@/lib/format";
import { pt } from "@/lib/portal-i18n";
import { usePortal } from "../PortalContext";
import type { ShopStep } from "../types";

export function ShopView() {
  const {
    lang,
    shopMode,
    setShopMode,
    shopStep,
    setShopStep,
    accounts,
    activeUsername,
    renewUsername,
    setRenewUsername,
    newUsername,
    setNewUsername,
    plans,
    payMethods,
    payProviders,
    checkoutMethod,
    setCheckoutMethod,
    provider,
    setProvider,
    cardCheckout,
    setCardCheckout,
    cardNote,
    setCardNote,
    cardReceipt,
    setCardReceipt,
    cardSubmittedOk,
    setCardSubmittedOk,
    busy,
    payPlan,
    submitCardPurchase,
    copyCardNumber,
    formatPrice,
    setTab,
  } = usePortal();

  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(null);

  const steps: { id: ShopStep; short: string; title: string }[] = [
    { id: "mode", short: pt(lang, "shopStepModeShort"), title: pt(lang, "shopStepModeTitle") },
    { id: "plan", short: pt(lang, "shopStepPlanShort"), title: pt(lang, "shopStepPlanTitle") },
    { id: "pay", short: pt(lang, "shopStepPayShort"), title: pt(lang, "shopStepPayTitle") },
  ];

  const stepIndex = steps.findIndex((s) => s.id === shopStep);
  const activeStep = steps[stepIndex] || steps[0];
  const selectedPlan = useMemo(
    () => plans.find((p) => p.id === selectedPlanId) || null,
    [plans, selectedPlanId],
  );

  useEffect(() => {
    setSelectedPlanId(null);
  }, [shopStep, shopMode]);

  const canContinueMode =
    shopMode === "buy" ? newUsername.trim().length >= 3 : Boolean(renewUsername || activeUsername);

  // Free plans and wallet-billed renewals need no gateway/card at all, so an
  // empty method list must not disable the whole shop.
  const needsCheckout = Boolean(selectedPlan && selectedPlan.price > 0);
  const canPayPlan =
    Boolean(selectedPlan) &&
    !busy &&
    !(needsCheckout && payMethods.length === 0 && shopMode === "buy") &&
    (shopMode === "buy" ? newUsername.trim().length >= 3 : Boolean(renewUsername || activeUsername));

  const contextHint =
    shopMode === "buy" ? pt(lang, "shopBuyCallout") : pt(lang, "shopRenewCallout");

  const goPaySelected = () => {
    if (!selectedPlan) return;
    setCardSubmittedOk(false);
    payPlan(selectedPlan.id, selectedPlan.name);
  };

  return (
    <div className="p-shop">
      <header className="p-shop-head">
        <div className="p-shop-progress" role="navigation" aria-label={pt(lang, "stepOf")}>
          {steps.map((s, i) => {
            const done = i < stepIndex;
            const on = shopStep === s.id;
            return (
              <button
                key={s.id}
                type="button"
                className={`p-shop-dot${on ? " is-on" : ""}${done ? " is-done" : ""}`}
                disabled={!done && !on}
                onClick={() => {
                  if (done) setShopStep(s.id);
                }}
                aria-current={on ? "step" : undefined}
              >
                <span className="p-shop-dot-num" aria-hidden>
                  {done ? <Check size={12} strokeWidth={3} /> : i + 1}
                </span>
                <span className="p-shop-dot-label">{s.short}</span>
              </button>
            );
          })}
        </div>
        <h1 className="p-shop-title">{activeStep.title}</h1>
        {shopStep === "mode" ? <p className="p-shop-hint">{contextHint}</p> : null}
        {shopStep === "plan" ? (
          <p className="p-shop-hint">
            {shopMode === "buy" ? (
              <>
                {pt(lang, "shopBuyCardTitle")} · <span dir="ltr">{newUsername || "—"}</span>
              </>
            ) : (
              <>
                {pt(lang, "shopRenewCardTitle")} ·{" "}
                <span dir="ltr">{renewUsername || activeUsername || "—"}</span>
              </>
            )}
          </p>
        ) : null}
      </header>

      <div className="p-shop-body" key={shopStep}>
        {shopStep === "mode" ? (
          <section className="p-shop-panel">
            <div className="p-shop-modes" role="radiogroup" aria-label={pt(lang, "shopStepModeTitle")}>
              <button
                type="button"
                role="radio"
                aria-checked={shopMode === "renew"}
                className={`p-shop-mode${shopMode === "renew" ? " is-on" : ""}`}
                onClick={() => {
                  setShopMode("renew");
                  setRenewUsername(activeUsername);
                  setCardSubmittedOk(false);
                  setCardCheckout(null);
                }}
              >
                <span className="p-shop-mode-icon" aria-hidden>
                  <RefreshCw size={18} />
                </span>
                <span className="p-shop-mode-copy">
                  <strong>{pt(lang, "shopRenewCardTitle")}</strong>
                  <span>{pt(lang, "shopRenewCardDesc")}</span>
                </span>
                <span className="p-shop-mode-check" aria-hidden>
                  {shopMode === "renew" ? <Check size={16} strokeWidth={3} /> : null}
                </span>
              </button>
              <button
                type="button"
                role="radio"
                aria-checked={shopMode === "buy"}
                className={`p-shop-mode${shopMode === "buy" ? " is-on" : ""}`}
                onClick={() => {
                  setShopMode("buy");
                  setCardSubmittedOk(false);
                  setCardCheckout(null);
                }}
              >
                <span className="p-shop-mode-icon" aria-hidden>
                  <PackagePlus size={18} />
                </span>
                <span className="p-shop-mode-copy">
                  <strong>{pt(lang, "shopBuyCardTitle")}</strong>
                  <span>{pt(lang, "shopBuyCardDesc")}</span>
                </span>
                <span className="p-shop-mode-check" aria-hidden>
                  {shopMode === "buy" ? <Check size={16} strokeWidth={3} /> : null}
                </span>
              </button>
            </div>

            {shopMode === "buy" ? (
              <div className="p-field p-shop-field">
                <label htmlFor="shop-new-user">{pt(lang, "newUsername")}</label>
                <input
                  id="shop-new-user"
                  className="p-input"
                  dir="ltr"
                  autoComplete="username"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value.toLowerCase())}
                  placeholder={pt(lang, "username")}
                />
              </div>
            ) : (
              <div className="p-field p-shop-field">
                <label htmlFor="shop-renew-user">{pt(lang, "renewTarget")}</label>
                {accounts.length <= 3 ? (
                  <div className="p-shop-accounts" role="listbox" aria-label={pt(lang, "renewTarget")}>
                    {accounts.map((a) => {
                      const val = renewUsername || activeUsername;
                      const on = a.username === val;
                      return (
                        <button
                          key={a.username}
                          type="button"
                          role="option"
                          aria-selected={on}
                          className={`p-shop-acct${on ? " is-on" : ""}`}
                          onClick={() => setRenewUsername(a.username)}
                        >
                          <span dir="ltr">{a.username}</span>
                          {a.is_portal_login ? (
                            <em>{pt(lang, "portalLoginBadge")}</em>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <select
                    id="shop-renew-user"
                    className="p-select"
                    value={renewUsername || activeUsername}
                    onChange={(e) => setRenewUsername(e.target.value)}
                  >
                    {accounts.map((a) => (
                      <option key={a.username} value={a.username}>
                        {a.username}
                        {a.is_portal_login ? ` (${pt(lang, "portalLoginBadge")})` : ""}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
          </section>
        ) : null}

        {shopStep === "plan" ? (
          <section className="p-shop-panel">
            {payMethods.length > 1 ? (
              <div className="p-shop-seg" role="group" aria-label={pt(lang, "payGateway")}>
                {payMethods.includes("gateway") ? (
                  <button
                    type="button"
                    className={checkoutMethod === "gateway" ? "is-on" : ""}
                    onClick={() => setCheckoutMethod("gateway")}
                  >
                    {pt(lang, "payGateway")}
                  </button>
                ) : null}
                {payMethods.includes("card") ? (
                  <button
                    type="button"
                    className={checkoutMethod === "card" ? "is-on" : ""}
                    onClick={() => setCheckoutMethod("card")}
                  >
                    {pt(lang, "payCard")}
                  </button>
                ) : null}
              </div>
            ) : null}

            {checkoutMethod === "gateway" && payProviders.length > 1 ? (
              <div className="p-field p-shop-field">
                <label htmlFor="shop-provider">{pt(lang, "provider")}</label>
                <select
                  id="shop-provider"
                  className="p-select"
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                >
                  {payProviders.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            {payMethods.length === 0 && plans.length > 0 ? (
              <p className="p-muted" style={{ marginBottom: 10 }}>
                {pt(lang, "noPayMethods")}
              </p>
            ) : null}

            {plans.length === 0 ? (
              <p className="p-muted">{pt(lang, "noPlans")}</p>
            ) : (
              <div className="p-shop-plans" role="radiogroup" aria-label={pt(lang, "selectPlan")}>
                {plans.map((p) => {
                  const on = selectedPlanId === p.id;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      className={`p-shop-plan${on ? " is-on" : ""}`}
                      onClick={() => setSelectedPlanId(p.id)}
                    >
                      <span className="p-shop-plan-main">
                        <strong>{p.name}</strong>
                        <span className="p-shop-plan-meta">
                          {p.data_limit ? bytes(p.data_limit) : pt(lang, "unlimited")}
                          {" · "}
                          {p.duration_days ? `${p.duration_days} ${pt(lang, "days")}` : pt(lang, "never")}
                          {" · "}
                          {pt(lang, "deviceLimit")}:{" "}
                          {p.device_limit && p.device_limit > 0 ? p.device_limit : pt(lang, "unlimited")}
                        </span>
                      </span>
                      <span className="p-shop-plan-side">
                        <span className="p-shop-plan-price">{formatPrice(p.price)}</span>
                        <span className={`p-shop-plan-radio${on ? " is-on" : ""}`} aria-hidden>
                          {on ? <Check size={12} strokeWidth={3} /> : null}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        ) : null}

        {shopStep === "pay" ? (
          <section className="p-shop-panel">
            {cardSubmittedOk && !cardCheckout ? (
              <div className="p-shop-success">
                <p>{pt(lang, "cardPendingBanner")}</p>
                <div className="p-shop-success-actions">
                  <button
                    type="button"
                    className="p-btn"
                    onClick={() => {
                      setCardSubmittedOk(false);
                      setTab("history");
                    }}
                  >
                    {pt(lang, "history")}
                  </button>
                  <button
                    type="button"
                    className="p-btn ghost"
                    onClick={() => setShopStep("mode")}
                  >
                    {pt(lang, "cancel")}
                  </button>
                </div>
              </div>
            ) : null}

            {cardCheckout ? (
              <div className="p-shop-pay">
                <div className="p-shop-pay-summary">
                  <span>{pt(lang, "cardPayTitle")}</span>
                  <strong>{formatPrice(cardCheckout.amount)}</strong>
                  {cardCheckout.plan_name ? <em>{cardCheckout.plan_name}</em> : null}
                  {cardCheckout.username ? (
                    <em dir="ltr">{cardCheckout.username}</em>
                  ) : null}
                </div>
                <p className="p-shop-hint">{pt(lang, "cardPayHint")}</p>
                <button
                  type="button"
                  className="p-bank-card"
                  onClick={copyCardNumber}
                  title={pt(lang, "cardTapCopy")}
                >
                  <div className="p-bank-card-top">
                    <span>{cardCheckout.card_bank || pt(lang, "payCard")}</span>
                    <span className="p-bank-card-chip" aria-hidden />
                  </div>
                  <div className="p-bank-card-number" dir="ltr">
                    {(cardCheckout.card_number || "")
                      .replace(/\D/g, "")
                      .replace(/(.{4})/g, "$1 ")
                      .trim() || "•••• •••• •••• ••••"}
                  </div>
                  <div className="p-bank-card-bottom">
                    <span>{cardCheckout.card_holder || "—"}</span>
                    <span>{pt(lang, "cardTapCopy")}</span>
                  </div>
                </button>
                <div className="p-field p-shop-field">
                  <label htmlFor="shop-card-note">{pt(lang, "cardNote")}</label>
                  <input
                    id="shop-card-note"
                    className="p-input"
                    value={cardNote}
                    onChange={(e) => setCardNote(e.target.value)}
                    placeholder={pt(lang, "cardNotePh")}
                  />
                </div>
                <div className="p-field p-shop-field">
                  <label htmlFor="shop-card-receipt">{pt(lang, "cardReceipt")}</label>
                  <input
                    id="shop-card-receipt"
                    className="p-input"
                    type="file"
                    accept="image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf"
                    onChange={(e) => setCardReceipt(e.target.files?.[0] || null)}
                  />
                  <p className="p-muted" style={{ marginTop: 6, fontSize: 12 }}>
                    {cardReceipt ? cardReceipt.name : pt(lang, "cardReceiptHint")}
                  </p>
                </div>
              </div>
            ) : !cardSubmittedOk ? (
              <p className="p-muted">{pt(lang, "shopStepPay")}</p>
            ) : null}
          </section>
        ) : null}
      </div>

      {shopStep === "mode" ? (
        <div className="p-shop-footer">
          <button
            type="button"
            className="p-btn p-shop-cta"
            disabled={!canContinueMode}
            onClick={() => setShopStep("plan")}
          >
            {pt(lang, "shopNext")}
          </button>
        </div>
      ) : null}

      {shopStep === "plan" ? (
        <div className="p-shop-footer">
          <button type="button" className="p-btn ghost p-shop-back" onClick={() => setShopStep("mode")}>
            <ChevronLeft size={18} aria-hidden />
            {pt(lang, "shopBack")}
          </button>
          <button
            type="button"
            className="p-btn p-shop-cta"
            disabled={!canPayPlan}
            onClick={goPaySelected}
          >
            {busy
              ? !needsCheckout || payMethods.length === 0
                ? pt(lang, "renewing")
                : pt(lang, "paying")
              : !needsCheckout || payMethods.length === 0
                ? shopMode === "buy"
                  ? pt(lang, "createFreeAccount")
                  : pt(lang, "renew")
                : checkoutMethod === "card"
                  ? shopMode === "buy"
                    ? pt(lang, "buyCard")
                    : pt(lang, "renewCard")
                  : shopMode === "buy"
                    ? pt(lang, "buy")
                    : pt(lang, "pay")}
          </button>
        </div>
      ) : null}

      {shopStep === "pay" && cardCheckout ? (
        <div className="p-shop-footer">
          <button
            type="button"
            className="p-btn ghost p-shop-back"
            disabled={busy}
            onClick={() => {
              setCardCheckout(null);
              setShopStep("plan");
            }}
          >
            <ChevronLeft size={18} aria-hidden />
            {pt(lang, "shopBack")}
          </button>
          <button
            type="button"
            className="p-btn p-shop-cta"
            disabled={busy || !cardReceipt}
            onClick={submitCardPurchase}
          >
            {busy ? pt(lang, "loading") : pt(lang, "cardSubmit")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
