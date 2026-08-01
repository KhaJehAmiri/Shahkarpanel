import { FC, useEffect, useMemo, useState } from "react";
import {
  bytesToDataLimitValue, dataLimitToBytes, detectDataLimitUnit, type DataLimitUnit,
} from "../lib/data-limit";
import { useTranslation } from "react-i18next";
import { useSearchParams, Link } from "react-router-dom";
import { api } from "../api/client";
import { Invoice, Plan, Transaction, TrafficPackage, TrafficPurchase, UsageSummary, Wallet, GatewayIncome } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch, useLiveReload } from "../lib/useFetch";
import { formatBytes } from "../lib/format";
import { PageHeader, notifyBillingAttentionChanged } from "../components/Shell";
import {
  Button, Callout, Card, EmptyState, Field, Input, MCard, Modal, Pager, Pill, ResponsiveData, Select, SkeletonRows, Stat, Toggle, usePagedList, useToast,
} from "../components/ui";
import { SectionRail, type RailGroup } from "../components/SectionRail";
import { CommercialSettings } from "../components/CommercialSettings";
import { IcPlus, IcTrash, IcWallet, IcEdit, IcCopy } from "../components/icons";
import { copyToClipboard } from "../lib/clipboard";

const BILLING_TABS = ["plans", "packages", "usage", "orders", "income", "invoices", "transactions", "card", "settings"] as const;

export const Billing: FC<{ embedded?: boolean }> = ({ embedded }) => {
  const { t } = useTranslation();
  const { admin, isEnabled } = useApp();
  const [search, setSearch] = useSearchParams();
  const tabFromUrl = search.get("billingTab");
  const initialTab = tabFromUrl && (BILLING_TABS as readonly string[]).includes(tabFromUrl)
    ? tabFromUrl
    : "plans";
  const [tab, setTab] = useState(initialTab);
  const [creditOpen, setCreditOpen] = useState(false);
  const [topupOpen, setTopupOpen] = useState(false);
  const wallet = useFetch<Wallet>(() => api.get("/billing/wallet"), []);
  const providers = useFetch<string[]>(() => api.get("/billing/payment-providers"), []);
  const attention = useFetch<{ orders: number; invoices: number }>(
    () => api.get("/billing/attention-counts"),
    [],
  );
  useLiveReload(() => {
    wallet.reload();
    providers.reload();
    attention.reload();
  }, 30000);
  const canTopUp = !admin?.is_sudo && (providers.data?.length ?? 0) > 0;
  const toast = useToast();
  const ordersBadge = attention.data?.orders ?? 0;
  const invoicesBadge = attention.data?.invoices ?? 0;

  useEffect(() => {
    const pay = search.get("pay");
    if (pay !== "ok" && pay !== "fail") return;
    toast.push(
      pay === "ok" ? t("billing.payOk", { defaultValue: "Payment successful" }) : t("billing.payFail", { defaultValue: "Payment failed or was cancelled" }),
      pay === "ok" ? "success" : "error",
    );
    const next = new URLSearchParams(search);
    next.delete("pay");
    setSearch(next, { replace: true });
    if (pay === "ok") wallet.reload();
  }, [search.get("pay")]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (tabFromUrl && (BILLING_TABS as readonly string[]).includes(tabFromUrl) && tabFromUrl !== tab) {
      setTab(tabFromUrl);
    }
  }, [tabFromUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  const onTabChange = (id: string) => {
    setTab(id);
    const next = new URLSearchParams(search);
    next.set("billingTab", id);
    setSearch(next, { replace: true });
  };

  const canSeeGatewayIncome = !!admin?.is_sudo || !!admin?.centralpay_enabled;

  const railGroups: RailGroup[] = [
    {
      id: "commerce",
      label: t("billing.groupCommerce"),
      items: [
        { id: "plans", label: t("billing.tabPlans") },
        { id: "packages", label: t("billing.tabTrafficPackages") },
      ],
    },
    {
      id: "ledger",
      label: t("billing.groupLedger"),
      items: [
        { id: "usage", label: t("billing.tabUsage") },
        { id: "orders", label: t("billing.tabOrders"), badge: ordersBadge },
        ...(canSeeGatewayIncome
          ? [{ id: "income", label: t("billing.tabIncome") }]
          : []),
        { id: "invoices", label: t("billing.tabInvoices"), badge: invoicesBadge },
        { id: "transactions", label: t("billing.tabTransactions") },
      ],
    },
    {
      id: "config",
      label: t("billing.groupConfig"),
      items: [
        { id: "card", label: t("billing.tabCardSettings") },
        ...(admin?.is_sudo
          ? [{ id: "settings", label: t("billing.tabSettings") }]
          : []),
      ],
    },
  ];

  if (!isEnabled("billing")) {
    return (
      <div className="sk-page sk-biz">
        {!embedded && <PageHeader title={t("billing.title")} subtitle={t("billing.subtitle")} />}
        <Callout tone="warn">{t("billing.billingDisabled")}</Callout>
      </div>
    );
  }

  return (
    <div className="sk-page sk-biz">
      {!embedded && (
        <PageHeader
          title={t("billing.title")}
          subtitle={t("billing.subtitle")}
          description={t("billing.description")}
        />
      )}

      <div className="sk-money-bar">
        <div className="sk-money-bar-main">
          <span className="sk-money-bar-ico" aria-hidden><IcWallet className="sk-ico" /></span>
          <div className="sk-money-bar-copy">
            <span className="sk-money-bar-label">{t("billing.wallet")}</span>
            {wallet.loading ? (
              <span className="sk-money-bar-value sk-faint">…</span>
            ) : (
              <span className="sk-money-bar-value">
                {(wallet.data?.balance ?? 0).toLocaleString()}
              </span>
            )}
          </div>
        </div>
        <div className="sk-money-bar-actions">
          {admin?.is_sudo ? (
            <Button variant="primary" size="sm" onClick={() => setCreditOpen(true)}>{t("billing.addCredit")}</Button>
          ) : canTopUp ? (
            <Button variant="primary" size="sm" onClick={() => setTopupOpen(true)}>{t("billing.topUp")}</Button>
          ) : (
            <span className="sk-money-bar-hint">{t("billing.resellerWalletHint")}</span>
          )}
        </div>
      </div>

      {creditOpen && <CreditModal onClose={() => setCreditOpen(false)} onDone={() => { setCreditOpen(false); wallet.reload(); }} />}
      {topupOpen && providers.data && (
        <TopUpModal providers={providers.data} onClose={() => setTopupOpen(false)} onDone={() => { setTopupOpen(false); wallet.reload(); }} />
      )}

      <div className="sk-biz-layout">
        <SectionRail
          groups={railGroups}
          active={tab}
          onChange={onTabChange}
          label={t("billing.title")}
        />
        <div className="sk-section-panel">
          {tab === "plans" && <PlansTab canWrite={!!admin?.is_sudo || admin?.role === "reseller"} />}
          {tab === "packages" && <TrafficPackagesTab onPurchased={() => wallet.reload()} />}
          {tab === "usage" && <UsageTab />}
          {tab === "orders" && <PortalOrdersTab onChanged={() => { attention.reload(); notifyBillingAttentionChanged(); }} />}
          {tab === "income" && canSeeGatewayIncome && <GatewayIncomeTab />}
          {tab === "card" && <ResellerCardSettingsTab />}
          {tab === "settings" && admin?.is_sudo && <CommercialSettings />}
          {tab === "invoices" && <InvoicesTab onChanged={() => { attention.reload(); wallet.reload(); notifyBillingAttentionChanged(); }} />}
          {tab === "transactions" && <TransactionsTab />}
        </div>
      </div>
    </div>
  );
};

const PlansTab: FC<{ canWrite?: boolean }> = ({ canWrite = false }) => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<Plan | null>(null);
  const [ownerFilter, setOwnerFilter] = useState<string>("all");
  const { data, loading, error, reload } = useFetch<Plan[]>(() => api.get("/plans"), []);
  const isSudo = !!admin?.is_sudo;

  const remove = async (id: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try { await api.del(`/plans/${id}`); toast.push(t("common.deleted"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  type PlanGroup = { key: string; label: string; plans: Plan[] };

  const groups = useMemo((): PlanGroup[] => {
    if (!data?.length) return [];
    if (!isSudo) {
      return [{ key: "mine", label: t("billing.tabPlans"), plans: data }];
    }
    const platform = data.filter((p) => !p.owner_admin_id);
    const byReseller = new Map<string, Plan[]>();
    for (const p of data) {
      if (!p.owner_admin_id) continue;
      const key = p.owner_username || `id:${p.owner_admin_id}`;
      const list = byReseller.get(key) || [];
      list.push(p);
      byReseller.set(key, list);
    }
    const out: PlanGroup[] = [];
    if (platform.length) {
      out.push({ key: "platform", label: t("billing.platformPlans"), plans: platform });
    }
    Array.from(byReseller.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .forEach(([username, plans]) => {
        out.push({
          key: `reseller:${username}`,
          label: t("billing.resellerPlans", { name: username }),
          plans,
        });
      });
    return out;
  }, [data, isSudo, t]);

  const resellerOptions = useMemo(() => {
    if (!data) return [] as string[];
    const names = new Set<string>();
    data.forEach((p) => {
      if (p.owner_username) names.add(p.owner_username);
    });
    return Array.from(names).sort();
  }, [data]);

  const visibleGroups = useMemo(() => {
    if (!isSudo || ownerFilter === "all") return groups;
    if (ownerFilter === "platform") return groups.filter((g) => g.key === "platform");
    return groups.filter((g) => g.key === `reseller:${ownerFilter}`);
  }, [groups, isSudo, ownerFilter]);

  const renderPlanTable = (plans: Plan[]) => (
    <ResponsiveData
      table={(
        <div className="sk-table-wrap"><table className="sk-table">
          <thead><tr>
            <th>{t("common.name")}</th>
            {isSudo ? <th>{t("billing.planOwner")}</th> : null}
            <th className="sk-num">{t("billing.price")}</th>
            <th className="sk-num">{t("users.dataLimit")}</th>
            <th className="sk-num">{t("billing.duration")}</th>
            <th>{t("common.status")}</th>
            <th className="sk-actions">{t("common.actions")}</th>
          </tr></thead>
          <tbody>
            {plans.map((p) => (
              <tr key={p.id}>
                <td style={{ fontWeight: 600 }}>{p.name}</td>
                {isSudo ? (
                  <td>
                    {p.owner_username
                      ? <Pill tone="info">{p.owner_username}</Pill>
                      : <span className="sk-faint">{t("billing.platformOwner")}</span>}
                  </td>
                ) : null}
                <td className="sk-num">{p.price.toLocaleString()}</td>
                <td className="sk-num">{p.data_limit ? formatBytes(p.data_limit) : t("users.unlimited")}</td>
                <td className="sk-num">{p.duration_days ? t("users.unitDays", { n: p.duration_days }) : t("users.unlimited")}</td>
                <td><Pill tone={p.enabled ? "ok" : "default"} dot>{p.enabled ? t("common.enabled") : t("common.disabled")}</Pill></td>
                <td className="sk-actions">{canWrite ? (
                  <div className="sk-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                    <Button size="sm" variant="ghost" onClick={() => setEdit(p)}><IcEdit className="sk-ico" /></Button>
                    <Button variant="danger" size="sm" onClick={() => remove(p.id)}><IcTrash className="sk-ico" /></Button>
                  </div>
                ) : null}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
      cards={plans.map((p) => (
        <MCard
          key={p.id}
          title={p.name}
          subtitle={isSudo
            ? (p.owner_username
              ? t("billing.resellerPlans", { name: p.owner_username })
              : t("billing.platformPlans"))
            : undefined}
          badge={<Pill tone={p.enabled ? "ok" : "default"} dot>{p.enabled ? t("common.enabled") : t("common.disabled")}</Pill>}
          fields={[
            { label: t("billing.price"), value: p.price.toLocaleString() },
            { label: t("users.dataLimit"), value: p.data_limit ? formatBytes(p.data_limit) : t("users.unlimited") },
            { label: t("billing.duration"), value: p.duration_days ? t("users.unitDays", { n: p.duration_days }) : t("users.unlimited") },
          ]}
          actions={canWrite ? (
            <div className="sk-row" style={{ justifyContent: "flex-end", gap: 6 }}>
              <Button size="sm" variant="ghost" onClick={() => setEdit(p)}><IcEdit className="sk-ico" /></Button>
              <Button variant="danger" size="sm" onClick={() => remove(p.id)}><IcTrash className="sk-ico" /></Button>
            </div>
          ) : undefined}
        />
      ))}
    />
  );

  return (
    <>
      <div className="sk-row" style={{ justifyContent: "space-between", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
        {isSudo ? (
          <Select value={ownerFilter} onChange={(e: any) => setOwnerFilter(e.target.value)} style={{ maxWidth: 280 }}>
            <option value="all">{t("billing.allPlanCatalogs")}</option>
            <option value="platform">{t("billing.platformPlans")}</option>
            {resellerOptions.map((name) => (
              <option key={name} value={name}>{t("billing.resellerPlans", { name })}</option>
            ))}
          </Select>
        ) : <span />}
        {canWrite ? (
          <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="sk-ico" /> {t("billing.addPlan")}</Button>
        ) : null}
      </div>
      {!canWrite && (
        <div style={{ marginBottom: 14 }}>
          <Callout tone="info">{t("billing.plansReadOnly")}</Callout>
        </div>
      )}
      {loading ? <Card pad0><div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div></Card>
        : error ? <EmptyState title={t("common.error")} desc={error} />
        : !data?.length ? <EmptyState title={t("common.noData")} desc={t("billing.plansReadOnly")} />
        : !visibleGroups.length ? <EmptyState title={t("common.noData")} />
        : visibleGroups.map((g) => (
          <Card pad0 key={g.key} className="sk-mb-20">
            {isSudo ? (
              <div style={{ padding: "12px 16px", fontWeight: 600, borderBottom: "1px solid var(--sk-border)" }}>
                {g.label}
                <span className="sk-faint" style={{ fontWeight: 400, marginInlineStart: 8 }}>({g.plans.length})</span>
              </div>
            ) : null}
            {renderPlanTable(g.plans)}
          </Card>
        ))}
      {show && <AddPlan onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
      {edit && <EditPlan plan={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </>
  );
};

const TOPUP_MIN_AMOUNT = 1_000_000;

const formatAmountGrouped = (digits: string) => {
  const clean = (digits || "").replace(/[^\d]/g, "");
  if (!clean) return "";
  return clean.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
};

const parseAmountDigits = (value: string) => {
  const clean = (value || "").replace(/[^\d]/g, "");
  return clean ? parseInt(clean, 10) : 0;
};

const TopUpModal: FC<{ providers: string[]; onClose: () => void; onDone: () => void }> = ({ providers, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [amountDigits, setAmountDigits] = useState("");
  const [provider, setProvider] = useState(providers[0] || "");
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState<"form" | "card">("form");
  const [paymentId, setPaymentId] = useState<number | null>(null);
  const [cards, setCards] = useState<Array<{ id?: string; number?: string; holder?: string; bank?: string }>>([]);
  const [cardIndex, setCardIndex] = useState(0);
  const [note, setNote] = useState("");
  const [receipt, setReceipt] = useState<File | null>(null);

  const amountValue = parseAmountDigits(amountDigits);
  const amountDisplay = formatAmountGrouped(amountDigits);
  const card = cards[cardIndex] || cards[0] || {};

  const providerLabel = (p: string) => {
    if (p === "card") return t("billing.providerCard");
    if (p === "centralpay") return t("billing.providerCentralpay");
    if (p === "stripe") return t("billing.providerStripe");
    if (p === "demo") return t("billing.providerDemo");
    return p;
  };

  const onAmountChange = (raw: string) => {
    const digits = raw.replace(/[^\d]/g, "").replace(/^0+(?=\d)/, "");
    setAmountDigits(digits.slice(0, 12));
  };

  const startPay = async () => {
    if (amountValue < TOPUP_MIN_AMOUNT) {
      toast.push(
        t("billing.topUpMinAmount", { amount: TOPUP_MIN_AMOUNT.toLocaleString("en-US") }),
        "error",
      );
      return;
    }
    setBusy(true);
    try {
      const created = await api.post<{
        payment_id: number;
        confirm_token?: string;
        checkout_url?: string;
        card_id?: string;
        card_number?: string;
        card_holder?: string;
        card_bank?: string;
        cards?: Array<{ id?: string; number?: string; holder?: string; bank?: string }>;
        provider: string;
      }>("/billing/topup", {
        amount: amountValue,
        provider,
      });
      if (created.provider === "card" || created.card_number) {
        setPaymentId(created.payment_id);
        const list =
          created.cards && created.cards.length
            ? created.cards
            : created.card_number
              ? [{
                  id: created.card_id,
                  number: created.card_number,
                  holder: created.card_holder,
                  bank: created.card_bank,
                }]
              : [];
        setCards(list);
        const idx = Math.max(
          0,
          list.findIndex((c) => (created.card_id && c.id === created.card_id) || c.number === created.card_number),
        );
        setCardIndex(idx < 0 ? Math.floor(Math.random() * Math.max(list.length, 1)) : idx);
        setStep("card");
        return;
      }
      if (created.checkout_url) {
        window.location.href = created.checkout_url;
        return;
      }
      if (created.confirm_token) {
        await api.post(`/billing/payments/${created.payment_id}/complete`, { confirm_token: created.confirm_token });
      }
      toast.push(t("billing.topUpDone"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const selectCard = async (nextIndex: number) => {
    if (!paymentId || !cards.length) return;
    const next = ((nextIndex % cards.length) + cards.length) % cards.length;
    const target = cards[next];
    setCardIndex(next);
    if (!target?.id) return;
    try {
      await api.put(`/billing/payments/${paymentId}/card`, { card_id: target.id });
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  const submitReceipt = async () => {
    if (!paymentId || !receipt) return;
    if (receipt.size > 15 * 1024 * 1024) {
      toast.push(t("billing.topUpCardHint"), "error");
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("receipt", receipt);
      if (note.trim()) form.append("note", note.trim());
      await api.upload(`/billing/payments/${paymentId}/submit`, form);
      toast.push(t("billing.topUpSubmitted"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const copyCardNumber = async () => {
    const num = (card.number || "").replace(/\s+/g, "");
    if (!num) return;
    const ok = await copyToClipboard(num);
    toast.push(ok ? t("common.copied") : t("common.error"), ok ? "success" : "error");
  };

  if (step === "card") {
    const multi = cards.length > 1;
    const formatCard = (num?: string) =>
      (num || "").replace(/\D/g, "").replace(/(.{4})/g, "$1 ").trim() || "•••• •••• •••• ••••";
    return (
      <Modal open title={t("billing.topUpCardTitle")} onClose={onClose}
        footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={busy || !receipt} onClick={submitReceipt}>{t("billing.topUpSubmitReceipt")}</Button></>}>
        <div className="sk-stack sk-modal-stack">
          <Callout tone="info">{t("billing.topUpCardHint")}</Callout>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <button
              type="button"
              onClick={copyCardNumber}
              title={t("billing.copyCardNumber")}
              style={{
                position: "relative",
                width: "100%",
                aspectRatio: "1.86 / 1",
                minHeight: 148,
                maxHeight: 188,
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 16,
                padding: "14px 18px 12px",
                textAlign: "start",
                cursor: "pointer",
                color: "#f4f7fb",
                font: "inherit",
                overflow: "hidden",
                display: "grid",
                gridTemplateRows: "auto 1fr auto",
                alignItems: "center",
                background:
                  "radial-gradient(120% 80% at 100% 0%, rgba(96,165,250,0.28), transparent 55%), linear-gradient(145deg, #152238 0%, #1a2f55 48%, #1e3a6e 100%)",
                boxShadow: "0 1px 0 rgba(255,255,255,0.06) inset, 0 18px 40px rgba(0,0,0,0.28)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 12, fontWeight: 500, opacity: 0.86 }}>{card.bank || t("billing.cardBadge")}</span>
                <span
                  aria-hidden
                  style={{
                    width: 30,
                    height: 22,
                    borderRadius: 5,
                    background: "linear-gradient(145deg, #e8c56a 0%, #c9a227 55%, #a67c12 100%)",
                  }}
                />
              </div>
              <div
                dir="ltr"
                style={{
                  margin: 0,
                  fontFamily: "ui-monospace, SF Mono, Menlo, monospace",
                  fontSize: 22,
                  fontWeight: 600,
                  letterSpacing: "0.1em",
                  color: "#fff",
                  lineHeight: 1.15,
                  alignSelf: "center",
                }}
              >
                {formatCard(card.number)}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 12 }}>
                <span style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {card.holder || "—"}
                </span>
                <span style={{ fontSize: 11, opacity: 0.55, flexShrink: 0 }}>{t("billing.copyCardNumber")}</span>
              </div>
            </button>
            {multi ? (
              <div className="sk-row" style={{ justifyContent: "center", alignItems: "center", gap: 14 }}>
                <Button size="sm" variant="ghost" disabled={busy || cardIndex === 0} onClick={() => selectCard(cardIndex - 1)}>‹</Button>
                <div className="sk-row" style={{ gap: 6, alignItems: "center" }}>
                  {cards.map((_, i) => (
                    <button
                      key={`dot-${i}`}
                      type="button"
                      aria-label={`card ${i + 1}`}
                      onClick={() => selectCard(i)}
                      disabled={busy}
                      style={{
                        width: i === cardIndex ? 18 : 6,
                        height: 6,
                        borderRadius: 999,
                        border: 0,
                        padding: 0,
                        opacity: i === cardIndex ? 1 : 0.55,
                        background: i === cardIndex ? "var(--sk-accent, #3b82f6)" : "var(--sk-border, #334155)",
                        cursor: "pointer",
                        transition: "width 220ms ease",
                      }}
                    />
                  ))}
                </div>
                <Button size="sm" variant="ghost" disabled={busy || cardIndex === cards.length - 1} onClick={() => selectCard(cardIndex + 1)}>›</Button>
              </div>
            ) : null}
          </div>
          <div className="sk-row" style={{ justifyContent: "space-between" }}>
            <span className="sk-faint">{t("billing.creditAmount")}</span>
            <span dir="ltr" style={{ fontWeight: 700 }}>{amountValue.toLocaleString("en-US")}</span>
          </div>
          <Field label={t("billing.orderNote")}>
            <Input value={note} onChange={(e: any) => setNote(e.target.value)} placeholder={t("billing.topUpNotePlaceholder")} />
          </Field>
          <Field label={t("billing.orderReceipt")}>
            <Input type="file" accept="image/*,.pdf" onChange={(e: any) => setReceipt(e.target.files?.[0] || null)} />
          </Field>
        </div>
      </Modal>
    );
  }

  return (
    <Modal open title={t("billing.topUp")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || amountValue < TOPUP_MIN_AMOUNT} onClick={startPay}>
          {provider === "card" ? t("billing.topUpShowCard") : t("billing.topUpPay")}
        </Button></>}>
      <div className="sk-stack sk-modal-stack">
        <Field
          label={t("billing.creditAmount")}
          hint={t("billing.topUpMinAmountHint", { amount: TOPUP_MIN_AMOUNT.toLocaleString("en-US") })}
        >
          <Input
            type="text"
            inputMode="numeric"
            dir="ltr"
            value={amountDisplay}
            onChange={(e: any) => onAmountChange(e.target.value)}
            placeholder="1,000,000"
            autoFocus
          />
        </Field>
        <Field label={t("billing.provider")}>
          <Select value={provider} onChange={(e: any) => setProvider(e.target.value)}>
            {providers.map((p) => <option key={p} value={p}>{providerLabel(p)}</option>)}
          </Select>
        </Field>
        <p className="sk-modal-lede">
          {provider === "card" ? t("billing.topUpCardIntro") : t("billing.topUpHint")}
        </p>
      </div>
    </Modal>
  );
};

const money = (n: number, label?: string) =>
  `${(n || 0).toLocaleString()}${label ? ` ${label}` : ""}`;

type MyCardItem = {
  id?: string;
  number: string;
  holder: string;
  bank: string;
  enabled?: boolean;
};

type MyCardSettings = {
  card_enabled: boolean;
  card_number: string;
  card_holder: string;
  card_bank: string;
  cards?: MyCardItem[];
  uses_platform_settings?: boolean;
};

const emptyCard = (): MyCardItem => ({ id: "", number: "", holder: "", bank: "", enabled: true });

const ResellerCardSettingsTab: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const toast = useToast();
  const { data, loading, error, reload } = useFetch<MyCardSettings>(
    () => api.get("/billing/my-card-settings"),
    [],
  );
  const [enabled, setEnabled] = useState(false);
  const [cards, setCards] = useState<MyCardItem[]>([emptyCard()]);
  const [busy, setBusy] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (!data || hydrated) return;
    setEnabled(Boolean(data.card_enabled));
    if (data.cards && data.cards.length) {
      setCards(data.cards.map((c) => ({
        id: c.id || "",
        number: c.number || "",
        holder: c.holder || "",
        bank: c.bank || "",
        enabled: c.enabled !== false,
      })));
    } else if (data.card_number) {
      setCards([{
        id: "",
        number: data.card_number || "",
        holder: data.card_holder || "",
        bank: data.card_bank || "",
        enabled: true,
      }]);
    } else {
      setCards([emptyCard()]);
    }
    setHydrated(true);
  }, [data, hydrated]);

  const updateCard = (index: number, patch: Partial<MyCardItem>) => {
    setCards((prev) => prev.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  };

  const addCard = () => {
    if (cards.length >= 12) return;
    setCards((prev) => [...prev, emptyCard()]);
  };

  const removeCard = (index: number) => {
    setCards((prev) => (prev.length <= 1 ? [emptyCard()] : prev.filter((_, i) => i !== index)));
  };

  const save = async () => {
    setBusy(true);
    try {
      const payloadCards = cards
        .map((c) => ({
          id: (c.id || "").trim(),
          number: c.number.trim(),
          holder: c.holder.trim(),
          bank: c.bank.trim(),
          enabled: c.enabled !== false,
        }))
        .filter((c) => c.number);
      await api.put("/billing/my-card-settings", {
        card_enabled: enabled,
        cards: payloadCards,
        card_number: payloadCards[0]?.number || "",
        card_holder: payloadCards[0]?.holder || "",
        card_bank: payloadCards[0]?.bank || "",
      });
      toast.push(t("common.saved"), "success");
      setHydrated(false);
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  if (loading && !hydrated) return <Card><SkeletonRows rows={4} cols={2} /></Card>;
  if (error) return <EmptyState title={t("common.error")} desc={error} />;

  return (
    <div className="sk-stack" style={{ gap: 16 }}>
      <Callout tone="info">
        {admin?.is_sudo ? t("billing.cardSettingsSudoHint") : t("billing.cardSettingsResellerHint")}
      </Callout>
      <Callout tone="info">{t("billing.cardMultiHint")}</Callout>
      <Card>
        <div className="sk-stack" style={{ gap: 14, maxWidth: 560 }}>
          <div className="sk-row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{t("billing.cardEnabled")}</div>
              <div className="sk-faint" style={{ fontSize: 12, marginTop: 4 }}>{t("billing.cardEnabledHint")}</div>
            </div>
            <Toggle on={enabled} onChange={() => setEnabled((v) => !v)} />
          </div>
          {cards.map((card, index) => (
            <div
              key={card.id || `card-${index}`}
              className="sk-stack"
              style={{
                gap: 10,
                padding: 12,
                border: "1px solid var(--sk-border)",
                borderRadius: 10,
              }}
            >
              <div className="sk-row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                <strong style={{ fontSize: 13 }}>{t("billing.cardItemLabel", { n: index + 1 })}</strong>
                <div className="sk-row" style={{ gap: 8 }}>
                  <Toggle
                    on={card.enabled !== false}
                    onChange={() => updateCard(index, { enabled: card.enabled === false })}
                  />
                  <Button size="sm" variant="ghost" onClick={() => removeCard(index)} title={t("common.delete")}>
                    <IcTrash className="sk-ico" />
                  </Button>
                </div>
              </div>
              <Field label={t("billing.cardNumber")}>
                <Input
                  dir="ltr"
                  value={card.number}
                  onChange={(e: any) => updateCard(index, { number: e.target.value })}
                  placeholder="6037…"
                  disabled={!enabled && !card.number}
                />
              </Field>
              <Field label={t("billing.cardHolder")}>
                <Input value={card.holder} onChange={(e: any) => updateCard(index, { holder: e.target.value })} />
              </Field>
              <Field label={t("billing.cardBank")}>
                <Input value={card.bank} onChange={(e: any) => updateCard(index, { bank: e.target.value })} />
              </Field>
            </div>
          ))}
          <div className="sk-row" style={{ justifyContent: "space-between" }}>
            <Button variant="ghost" disabled={busy || cards.length >= 12} onClick={addCard}>
              <IcPlus className="sk-ico" /> {t("billing.cardAdd")}
            </Button>
            <Button variant="primary" disabled={busy} onClick={save}>{t("common.save")}</Button>
          </div>
        </div>
      </Card>
    </div>
  );
};

const GatewayIncomeTab: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const { data, loading, error, reload } = useFetch<GatewayIncome>(
    () => api.get("/billing/gateway-income?payments_limit=100"),
    [],
  );
  useLiveReload(() => { reload(); }, 60000);
  const cur = data?.currency_label || "";

  if (loading) return <Card><SkeletonRows rows={6} cols={4} /></Card>;
  if (error) return <EmptyState title={t("common.error")} desc={error} />;

  return (
    <div className="sk-stack" style={{ gap: 16 }}>
      <Callout tone="info">{t("billing.incomeHint")}</Callout>
      <div className="sk-stat-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12 }}>
        <Stat label={t("billing.incomeToday")} value={money(data?.today ?? 0, cur)} />
        <Stat label={t("billing.incomeYesterday")} value={money(data?.yesterday ?? 0, cur)} />
        <Stat label={t("billing.incomeWeek")} value={money(data?.week ?? 0, cur)} />
        <Stat label={t("billing.incomeTotal")} value={money(data?.total ?? 0, cur)} />
      </div>

      {admin?.is_sudo && (data?.resellers?.length ?? 0) > 0 && (
        <Card pad0>
          <div style={{ padding: "12px 16px", fontWeight: 600 }}>{t("billing.incomeByReseller")}</div>
          <ResponsiveData
            table={(
              <div className="sk-table-wrap">
                <table className="sk-table">
                  <thead>
                    <tr>
                      <th>{t("common.username")}</th>
                      <th className="sk-num">{t("billing.incomeToday")}</th>
                      <th className="sk-num">{t("billing.incomeYesterday")}</th>
                      <th className="sk-num">{t("billing.incomeWeek")}</th>
                      <th className="sk-num">{t("billing.incomeTotal")}</th>
                      <th className="sk-num">{t("billing.paymentsCount")}</th>
                      <th>{t("billing.provider")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data!.resellers.map((r) => (
                      <tr key={r.admin_id}>
                        <td>
                          <div className="sk-ra-user">
                            <span className="sk-ra-user-name">{r.username}</span>
                            {r.centralpay_enabled && (
                              <span className="sk-ra-user-role">CentralPay</span>
                            )}
                            {r.card_enabled && (
                              <span className="sk-ra-user-role">{t("billing.cardBadge")}</span>
                            )}
                          </div>
                        </td>
                        <td className="sk-num">{money(r.today)}</td>
                        <td className="sk-num">{money(r.yesterday)}</td>
                        <td className="sk-num">{money(r.week)}</td>
                        <td className="sk-num" style={{ fontWeight: 600 }}>{money(r.total)}</td>
                        <td className="sk-num">{r.payments_count}</td>
                        <td className="sk-muted">
                          {Object.entries(r.by_provider || {}).map(([p, a]) => `${p}: ${a.toLocaleString()}`).join(" · ") || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            cards={data!.resellers.map((r) => (
              <MCard
                key={r.admin_id}
                title={r.username}
                subtitle={[
                  r.centralpay_enabled ? "CentralPay" : null,
                  r.card_enabled ? t("billing.cardBadge") : null,
                ].filter(Boolean).join(" · ") || undefined}
                fields={[
                  { label: t("billing.incomeToday"), value: money(r.today) },
                  { label: t("billing.incomeYesterday"), value: money(r.yesterday) },
                  { label: t("billing.incomeWeek"), value: money(r.week) },
                  { label: t("billing.incomeTotal"), value: <strong>{money(r.total)}</strong> },
                  { label: t("billing.paymentsCount"), value: r.payments_count },
                  {
                    label: t("billing.provider"),
                    value: Object.entries(r.by_provider || {}).map(([p, a]) => `${p}: ${a.toLocaleString()}`).join(" · ") || "—",
                  },
                ]}
              />
            ))}
          />
        </Card>
      )}

      <Card pad0>
        <div style={{ padding: "12px 16px", fontWeight: 600 }}>{t("billing.incomeRecent")}</div>
        {!data?.recent_payments?.length ? (
          <EmptyState title={t("billing.incomeEmpty")} />
        ) : (
          <ResponsiveData
            table={(
              <div className="sk-table-wrap">
                <table className="sk-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>{t("billing.date")}</th>
                      <th>{t("billing.type")}</th>
                      <th>{t("billing.provider")}</th>
                      <th>{t("billing.orderUser")}</th>
                      <th>{t("billing.orderPlan")}</th>
                      <th className="sk-num">{t("billing.amount")}</th>
                      <th>{t("billing.reference")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_payments.map((p) => (
                      <tr key={p.id}>
                        <td className="sk-faint">#{p.id}</td>
                        <td className="sk-muted">
                          {p.completed_at ? new Date(p.completed_at).toLocaleString() : "—"}
                        </td>
                        <td>{t(`billing.kind_${p.kind}`, { defaultValue: p.kind })}</td>
                        <td>{p.provider}</td>
                        <td>{p.username || "—"}</td>
                        <td>{p.plan_name || "—"}</td>
                        <td className="sk-num" style={{ fontWeight: 600 }}>{money(p.amount, cur)}</td>
                        <td className="sk-muted" style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis" }}>
                          {p.reference != null ? String(p.reference) : (p.card || "—")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            cards={data.recent_payments.map((p) => (
              <MCard
                key={p.id}
                title={money(p.amount, cur)}
                subtitle={`#${p.id} · ${p.completed_at ? new Date(p.completed_at).toLocaleString() : "—"}`}
                badge={<Pill tone="ok">{t(`billing.kind_${p.kind}`, { defaultValue: p.kind })}</Pill>}
                fields={[
                  { label: t("billing.provider"), value: p.provider },
                  { label: t("billing.orderUser"), value: p.username || "—" },
                  { label: t("billing.orderPlan"), value: p.plan_name || "—" },
                  { label: t("billing.reference"), value: p.reference != null ? String(p.reference) : (p.card || "—") },
                ]}
              />
            ))}
          />
        )}
      </Card>
    </div>
  );
};

const PortalOrdersTab: FC<{ onChanged?: () => void }> = ({ onChanged }) => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const toast = useToast();
  const { data, loading, error, reload } = useFetch<Array<{
    id: number;
    kind?: string;
    status: string;
    provider: string;
    amount: number;
    plan_name?: string | null;
    username?: string | null;
    admin_username?: string | null;
    user_note?: string | null;
    has_receipt?: boolean;
    receipt_name?: string | null;
    created_at?: string | null;
  }>>(() => api.get("/billing/portal-payments"), []);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [receiptPreview, setReceiptPreview] = useState<{
    url: string;
    contentType: string;
    name: string;
  } | null>(null);
  const [receiptLoading, setReceiptLoading] = useState(false);

  const closeReceipt = () => {
    setReceiptPreview((prev) => {
      if (prev?.url) URL.revokeObjectURL(prev.url);
      return null;
    });
  };

  useEffect(() => () => {
    if (receiptPreview?.url) URL.revokeObjectURL(receiptPreview.url);
  }, [receiptPreview?.url]);

  const openReceipt = async (id: number, name?: string | null) => {
    setReceiptLoading(true);
    try {
      const { blob, contentType, filename } = await api.getBlob(`/billing/portal-payments/${id}/receipt`);
      const url = URL.createObjectURL(blob);
      setReceiptPreview((prev) => {
        if (prev?.url) URL.revokeObjectURL(prev.url);
        return {
          url,
          contentType: contentType || blob.type || "",
          name: filename || name || `receipt-${id}`,
        };
      });
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setReceiptLoading(false);
    }
  };

  const downloadReceipt = () => {
    if (!receiptPreview) return;
    const a = document.createElement("a");
    a.href = receiptPreview.url;
    a.download = receiptPreview.name || "receipt";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const approve = async (id: number, kind?: string) => {
    setBusyId(id);
    try {
      await api.post(`/billing/portal-payments/${id}/approve`, {});
      toast.push(
        kind === "topup" ? t("billing.topUpApproved") : t("billing.orderApproved"),
        "success",
      );
      reload();
      onChanged?.();
      try {
        const { syncAdminAppBadge } = await import("../lib/webPush");
        await syncAdminAppBadge();
      } catch {
        /* ignore */
      }
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusyId(null);
    }
  };

  const reject = async (id: number, kind?: string) => {
    if (!confirm(t("common.confirmDelete"))) return;
    setBusyId(id);
    try {
      await api.post(`/billing/portal-payments/${id}/reject`, {});
      toast.push(
        kind === "topup" ? t("billing.topUpRejected") : t("billing.orderRejected"),
        "success",
      );
      reload();
      onChanged?.();
      try {
        const { syncAdminAppBadge } = await import("../lib/webPush");
        await syncAdminAppBadge();
      } catch {
        /* ignore */
      }
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusyId(null);
    }
  };

  const statusLabel = (s: string) => t(`billing.${s}`, { defaultValue: s });
  const kindLabel = (k?: string) => {
    if (k === "topup") return t("billing.kind_topup");
    if (k === "portal_purchase") return t("billing.kind_portal_purchase");
    if (k === "portal_renew") return t("billing.kind_portal_renew");
    return k || "—";
  };

  const isImage = !!receiptPreview && /^image\//i.test(receiptPreview.contentType);
  const isPdf = !!receiptPreview && (
    /pdf/i.test(receiptPreview.contentType)
    || /\.pdf$/i.test(receiptPreview.name || "")
  );

  return (
    <>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={4} cols={5} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !data?.length ? <EmptyState title={t("common.noData")} desc={admin?.is_sudo ? t("billing.ordersEmptySudo") : t("billing.ordersEmpty")} />
          : (
            <ResponsiveData
              table={(
                <div className="sk-table-wrap"><table className="sk-table">
                  <thead><tr>
                    <th>{t("billing.orderUser")}</th>
                    <th>{t("billing.orderKind")}</th>
                    <th>{t("billing.orderPlan")}</th>
                    <th className="sk-num">{t("billing.price")}</th>
                    <th>{t("common.status")}</th>
                    <th>{t("billing.orderNote")}</th>
                    <th>{t("billing.orderReceipt")}</th>
                    <th />
                  </tr></thead>
                  <tbody>
                    {data.map((row) => (
                      <tr key={row.id}>
                        <td dir="ltr">{row.username || row.admin_username || "—"}</td>
                        <td>{kindLabel(row.kind)}</td>
                        <td>{row.kind === "topup" ? t("billing.wallet") : (row.plan_name || `#${row.id}`)}</td>
                        <td className="sk-num">{row.amount.toLocaleString()}</td>
                        <td><Pill tone={row.status === "awaiting_review" || row.status === "pending" ? "warn" : row.status === "completed" ? "ok" : "danger"}>{statusLabel(row.status)}</Pill></td>
                        <td className="sk-faint" style={{ maxWidth: 180 }}>{row.user_note || "—"}</td>
                        <td>
                          {row.has_receipt ? (
                            <Button size="sm" variant="ghost" disabled={receiptLoading} onClick={() => openReceipt(row.id, row.receipt_name)}>
                              {t("billing.viewReceipt")}
                            </Button>
                          ) : "—"}
                        </td>
                        <td>
                          {(row.status === "awaiting_review" || row.status === "pending") && row.provider === "card" ? (
                            <div className="sk-row" style={{ gap: 6, justifyContent: "flex-end" }}>
                              <Button size="sm" variant="primary" disabled={busyId === row.id} onClick={() => approve(row.id, row.kind)}>{t("billing.orderApprove")}</Button>
                              <Button size="sm" variant="ghost" disabled={busyId === row.id} onClick={() => reject(row.id, row.kind)}>{t("billing.orderReject")}</Button>
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              )}
              cards={data.map((row) => {
                const canReview = (row.status === "awaiting_review" || row.status === "pending") && row.provider === "card";
                const hasActions = !!row.has_receipt || canReview;
                return (
                  <MCard
                    key={row.id}
                    title={row.username || row.admin_username || "—"}
                    subtitle={kindLabel(row.kind)}
                    badge={(
                      <Pill tone={row.status === "awaiting_review" || row.status === "pending" ? "warn" : row.status === "completed" ? "ok" : "danger"}>
                        {statusLabel(row.status)}
                      </Pill>
                    )}
                    fields={[
                      { label: t("billing.orderPlan"), value: row.kind === "topup" ? t("billing.wallet") : (row.plan_name || `#${row.id}`) },
                      { label: t("billing.price"), value: row.amount.toLocaleString() },
                      { label: t("billing.orderNote"), value: row.user_note || "—" },
                    ]}
                    actions={hasActions ? (
                      <div className="sk-row" style={{ gap: 6, justifyContent: "flex-end", flexWrap: "wrap" }}>
                        {row.has_receipt ? (
                          <Button size="sm" variant="ghost" disabled={receiptLoading} onClick={() => openReceipt(row.id, row.receipt_name)}>
                            {t("billing.viewReceipt")}
                          </Button>
                        ) : null}
                        {canReview ? (
                          <>
                            <Button size="sm" variant="primary" disabled={busyId === row.id} onClick={() => approve(row.id, row.kind)}>{t("billing.orderApprove")}</Button>
                            <Button size="sm" variant="ghost" disabled={busyId === row.id} onClick={() => reject(row.id, row.kind)}>{t("billing.orderReject")}</Button>
                          </>
                        ) : null}
                      </div>
                    ) : undefined}
                  />
                );
              })}
            />
          )}
      </Card>

      {receiptPreview && (
        <Modal
          open
          wide
          title={t("billing.viewReceipt")}
          onClose={closeReceipt}
          footer={
            <>
              <Button variant="ghost" onClick={downloadReceipt}>{t("billing.downloadReceipt")}</Button>
              <Button variant="primary" onClick={closeReceipt}>{t("common.close")}</Button>
            </>
          }
        >
          <div className="sk-stack" style={{ gap: 10 }}>
            <div className="sk-faint" style={{ fontSize: 13 }}>{receiptPreview.name}</div>
            {isImage ? (
              <img
                src={receiptPreview.url}
                alt={receiptPreview.name}
                style={{
                  display: "block",
                  width: "100%",
                  maxHeight: "70vh",
                  objectFit: "contain",
                  borderRadius: 8,
                  background: "rgba(0,0,0,0.25)",
                }}
              />
            ) : isPdf ? (
              <iframe
                title={receiptPreview.name}
                src={receiptPreview.url}
                style={{
                  width: "100%",
                  height: "70vh",
                  border: 0,
                  borderRadius: 8,
                  background: "#fff",
                }}
              />
            ) : (
              <Callout tone="info">{t("billing.receiptPreviewUnsupported")}</Callout>
            )}
          </div>
        </Modal>
      )}
    </>
  );
};

const CreditModal: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [username, setUsername] = useState("");
  const [mode, setMode] = useState<"set" | "delta">("set");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const amt = parseInt(amount, 10);
      if (!username.trim()) throw new Error(t("common.username"));
      if (Number.isNaN(amt)) throw new Error(t("billing.creditAmountHint"));
      if (mode === "set" && amt < 0) throw new Error(t("resellers.setBalanceHint"));
      if (mode === "delta" && amt === 0) throw new Error(t("resellers.deltaAmountHint"));
      await api.post("/billing/adjust", { username: username.trim(), mode, amount: amt });
      toast.push(t("common.saved"), "success");
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open title={t("resellers.adjustWallet")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !username || amount === ""} onClick={submit}>{t("common.save")}</Button></>}>
      <div className="sk-stack sk-modal-stack">
        <Field label={t("common.username")}><Input value={username} onChange={(e: any) => setUsername(e.target.value)} /></Field>
        <Field label={t("resellers.adjustMode")}>
          <select className="sk-select" value={mode} onChange={(e: any) => setMode(e.target.value)}>
            <option value="set">{t("resellers.modeSetBalance")}</option>
            <option value="delta">{t("resellers.modeDelta")}</option>
          </select>
        </Field>
        <Field label={mode === "set" ? t("resellers.newBalance") : t("billing.creditAmount")}>
          <Input type="number" value={amount} onChange={(e: any) => setAmount(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
};

const EditPlan: FC<{ plan: Plan; onClose: () => void; onDone: () => void }> = ({ plan, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const planUnit = plan.data_limit ? detectDataLimitUnit(plan.data_limit) : "MB";
  const [f, setF] = useState({
    name: plan.name,
    price: String(plan.price),
    dataLimitValue: plan.data_limit ? bytesToDataLimitValue(plan.data_limit, planUnit) : "",
    dataLimitUnit: planUnit as DataLimitUnit,
    days: plan.duration_days ? String(plan.duration_days) : "",
    enabled: plan.enabled,
  });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const submit = async () => {
    setBusy(true);
    try {
      await api.put(`/plans/${plan.id}`, {
        name: f.name.trim(),
        price: parseInt(f.price) || 0,
        data_limit: f.dataLimitValue ? dataLimitToBytes(f.dataLimitValue, f.dataLimitUnit) : null,
        duration_days: f.days ? parseInt(f.days) : null,
        enabled: f.enabled,
      });
      toast.push(t("common.saved"), "success");
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open title={`${t("common.edit")} — ${plan.name}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy} onClick={submit}>{t("common.save")}</Button></>}>
      <div className="sk-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} /></Field>
        <Field label={t("billing.price")}><Input type="number" value={f.price} onChange={upd("price")} /></Field>
        <Field label={t("billing.dataLimit")}>
          <div className="sk-row" style={{ gap: 8 }}>
            <Input type="number" value={f.dataLimitValue} onChange={upd("dataLimitValue")} style={{ flex: 1 }} />
            <Select value={f.dataLimitUnit} onChange={upd("dataLimitUnit")} style={{ width: 88 }}>
              <option value="MB">MB</option>
              <option value="GB">GB</option>
            </Select>
          </div>
        </Field>
        <label className="sk-row" style={{ gap: 8 }}><input type="checkbox" checked={f.enabled} onChange={upd("enabled")} /> {t("common.enabled")}</label>
      </div>
    </Modal>
  );
};

const AddPlan: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState({ name: "", price: "0", dataLimitValue: "", dataLimitUnit: "MB" as DataLimitUnit, days: "", devices: "" });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/plans", {
        name: f.name.trim(), price: parseInt(f.price) || 0,
        data_limit: f.dataLimitValue ? dataLimitToBytes(f.dataLimitValue, f.dataLimitUnit) : null,
        duration_days: f.days ? parseInt(f.days) : null,
        device_limit: f.devices ? parseInt(f.devices) : null, enabled: true,
      });
      toast.push(t("common.created"), "success"); onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Modal open title={t("billing.addPlan")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !f.name} onClick={submit}>{t("common.create")}</Button></>}>
      <div className="sk-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <div className="sk-row" style={{ gap: 12 }}>
          <Field label={t("billing.price")}><Input type="number" value={f.price} onChange={upd("price")} /></Field>
          <Field
            label={t("billing.dataLimit")}
            hint={t("billing.dataLimitUnlimitedHint", {
              defaultValue: "Leave empty for unlimited volume. Use this with a price as the reseller tariff reference plan.",
            })}
          >
            <div className="sk-row" style={{ gap: 8 }}>
              <Input type="number" value={f.dataLimitValue} onChange={upd("dataLimitValue")} style={{ flex: 1 }} placeholder={t("billing.unlimited", { defaultValue: "Unlimited" })} />
              <Select value={f.dataLimitUnit} onChange={upd("dataLimitUnit")} style={{ width: 88 }}>
                <option value="MB">MB</option>
                <option value="GB">GB</option>
              </Select>
            </div>
          </Field>
        </div>
        <div className="sk-row" style={{ gap: 12 }}>
          <Field label={t("billing.duration")}><Input type="number" value={f.days} onChange={upd("days")} /></Field>
          <Field label={t("billing.deviceLimit")}><Input type="number" value={f.devices} onChange={upd("devices")} /></Field>
        </div>
      </div>
    </Modal>
  );
};

const TrafficPackagesTab: FC<{ onPurchased?: () => void }> = ({ onPurchased }) => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<TrafficPackage | null>(null);
  const packages = useFetch<TrafficPackage[]>(() => api.get("/billing/traffic-packages"), []);
  const usage = useFetch<UsageSummary>(() => api.get("/billing/usage"), []);
  const purchases = useFetch<TrafficPurchase[]>(() => api.get("/billing/traffic-packages/purchases?limit=20"), []);
  const isSudo = !!admin?.is_sudo;
  const prepaid = usage.data?.prepaid_traffic_remaining ?? 0;
  const packageEmpty = !isSudo && prepaid <= 0;

  const remove = async (id: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      await api.del(`/billing/traffic-packages/${id}`);
      toast.push(t("common.deleted"), "success");
      packages.reload();
    } catch (e: any) { toast.push(e.message, "error"); }
  };

  const buy = async (pkg: TrafficPackage) => {
    if (!confirm(t("billing.confirmBuyPackage", { name: pkg.name, price: pkg.price.toLocaleString() }))) return;
    try {
      await api.post<TrafficPurchase>(`/billing/traffic-packages/${pkg.id}/purchase`, {});
      toast.push(t("billing.packagePurchased"), "success");
      packages.reload();
      usage.reload();
      purchases.reload();
      onPurchased?.();
    } catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <div className="sk-stack" style={{ gap: 14 }}>
      <div className="sk-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
        <Stat label={t("billing.prepaidRemaining")} value={formatBytes(prepaid)} />
      </div>
      {packageEmpty ? (
        <Callout tone="danger" title={t("billing.packageExhaustedTitle")}>
          {t("billing.packageExhaustedHint")}
        </Callout>
      ) : (
        <Callout tone="info">{t("billing.trafficPackageHint")}</Callout>
      )}
      {isSudo && (
        <div className="sk-row" style={{ justifyContent: "flex-end" }}>
          <Button variant="primary" onClick={() => setShow(true)}>
            <IcPlus className="sk-ico" /> {t("billing.addTrafficPackage")}
          </Button>
        </div>
      )}
      <Card pad0>
        {packages.loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
          : packages.error ? <EmptyState title={t("common.error")} desc={packages.error} />
          : !packages.data?.length ? <EmptyState title={t("common.noData")} desc={t("billing.noTrafficPackages")} />
          : (
            <ResponsiveData
              table={(
                <div className="sk-table-wrap">
                  <table className="sk-table">
                    <thead><tr>
                      <th>{t("common.name")}</th>
                      <th className="sk-num">{t("billing.packageTraffic")}</th>
                      <th className="sk-num">{t("billing.price")}</th>
                      <th>{t("common.status")}</th>
                      <th className="sk-actions">{t("common.actions")}</th>
                    </tr></thead>
                    <tbody>
                      {packages.data.map((pkg) => (
                        <tr key={pkg.id}>
                          <td>{pkg.name}</td>
                          <td className="sk-num">{formatBytes(pkg.bytes)}</td>
                          <td className="sk-num">{pkg.price.toLocaleString()}</td>
                          <td><Pill tone={pkg.enabled ? "ok" : "default"}>{pkg.enabled ? t("common.enabled") : t("common.disabled")}</Pill></td>
                          <td className="sk-actions">
                            <div className="sk-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                              {!isSudo && pkg.enabled && (
                                <Button size="sm" variant="primary" onClick={() => buy(pkg)}>{t("billing.buyPackage")}</Button>
                              )}
                              {isSudo && (
                                <>
                                  <Button size="sm" variant="ghost" onClick={() => setEdit(pkg)}><IcEdit className="sk-ico" /></Button>
                                  <Button size="sm" variant="danger" onClick={() => remove(pkg.id)}><IcTrash className="sk-ico" /></Button>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              cards={packages.data.map((pkg) => (
                <MCard
                  key={pkg.id}
                  title={pkg.name}
                  badge={<Pill tone={pkg.enabled ? "ok" : "default"}>{pkg.enabled ? t("common.enabled") : t("common.disabled")}</Pill>}
                  fields={[
                    { label: t("billing.packageTraffic"), value: formatBytes(pkg.bytes) },
                    { label: t("billing.price"), value: pkg.price.toLocaleString() },
                  ]}
                  actions={(
                    <div className="sk-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                      {!isSudo && pkg.enabled && (
                        <Button size="sm" variant="primary" onClick={() => buy(pkg)}>{t("billing.buyPackage")}</Button>
                      )}
                      {isSudo && (
                        <>
                          <Button size="sm" variant="ghost" onClick={() => setEdit(pkg)}><IcEdit className="sk-ico" /></Button>
                          <Button size="sm" variant="danger" onClick={() => remove(pkg.id)}><IcTrash className="sk-ico" /></Button>
                        </>
                      )}
                    </div>
                  )}
                />
              ))}
            />
          )}
      </Card>
      {(purchases.data?.length ?? 0) > 0 && (
        <Card pad0>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--sk-border, #e5e7eb)" }}>
            <strong>{t("billing.purchaseHistory")}</strong>
          </div>
          <ResponsiveData
            table={(
              <div className="sk-table-wrap">
                <table className="sk-table">
                  <thead><tr>
                    <th>{t("billing.date")}</th>
                    <th className="sk-num">{t("billing.packageTraffic")}</th>
                    <th className="sk-num">{t("billing.price")}</th>
                    <th>{t("billing.purchaseSource")}</th>
                  </tr></thead>
                  <tbody>
                    {purchases.data!.map((p) => (
                      <tr key={p.id}>
                        <td>{p.created_at ? new Date(p.created_at).toLocaleString() : "—"}</td>
                        <td className="sk-num">{formatBytes(p.bytes)}</td>
                        <td className="sk-num">{p.price_paid.toLocaleString()}</td>
                        <td>{p.source === "manual" ? t("billing.sourceManual") : t("billing.sourcePurchase")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            cards={purchases.data!.map((p) => (
              <MCard
                key={p.id}
                title={formatBytes(p.bytes)}
                subtitle={p.created_at ? new Date(p.created_at).toLocaleString() : "—"}
                fields={[
                  { label: t("billing.price"), value: p.price_paid.toLocaleString() },
                  { label: t("billing.purchaseSource"), value: p.source === "manual" ? t("billing.sourceManual") : t("billing.sourcePurchase") },
                ]}
              />
            ))}
          />
        </Card>
      )}
      {show && (
        <TrafficPackageModal
          onClose={() => setShow(false)}
          onDone={() => { setShow(false); packages.reload(); }}
        />
      )}
      {edit && (
        <TrafficPackageModal
          initial={edit}
          onClose={() => setEdit(null)}
          onDone={() => { setEdit(null); packages.reload(); }}
        />
      )}
    </div>
  );
};

const TrafficPackageModal: FC<{
  initial?: TrafficPackage;
  onClose: () => void;
  onDone: () => void;
}> = ({ initial, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const defaults = useFetch<{ key: string; value: string | number | boolean | null }[]>(
    () => (initial ? Promise.resolve([]) : api.get("/platform-settings")),
    [initial?.id],
  );
  const defaultPrice = !initial
    ? Number(defaults.data?.find((s) => s.key === "billing.default_package_price")?.value ?? 0) || 0
    : 0;
  const defaultBytes = !initial
    ? Number(defaults.data?.find((s) => s.key === "billing.default_package_bytes")?.value ?? 0) || 0
    : 0;
  const unit0 = initial
    ? detectDataLimitUnit(initial.bytes)
    : (defaultBytes > 0 ? detectDataLimitUnit(defaultBytes) : "GB" as DataLimitUnit);
  const [f, setF] = useState({
    name: initial?.name || "",
    price: String(initial?.price ?? ""),
    trafficValue: initial
      ? String(bytesToDataLimitValue(initial.bytes, unit0))
      : (defaultBytes > 0 ? String(bytesToDataLimitValue(defaultBytes, unit0)) : "100"),
    trafficUnit: unit0,
    enabled: initial?.enabled ?? true,
  });
  const [defaultsApplied, setDefaultsApplied] = useState(!!initial);

  useEffect(() => {
    if (initial || defaultsApplied || defaults.loading) return;
    setF((s) => ({
      ...s,
      price: defaultPrice > 0 ? String(defaultPrice) : s.price,
      trafficValue: defaultBytes > 0
        ? String(bytesToDataLimitValue(defaultBytes, unit0))
        : s.trafficValue,
      trafficUnit: unit0,
    }));
    setDefaultsApplied(true);
  }, [initial, defaultsApplied, defaults.loading, defaultPrice, defaultBytes, unit0]);

  const upd = (k: string) => (e: any) => setF((s) => ({
    ...s,
    [k]: e?.target ? (e.target.type === "checkbox" ? e.target.checked : e.target.value) : e,
  }));

  const submit = async () => {
    setBusy(true);
    try {
      const bytes = dataLimitToBytes(f.trafficValue, f.trafficUnit);
      if (!bytes) throw new Error(t("billing.packageTrafficRequired"));
      const body = {
        name: f.name.trim(),
        price: parseInt(f.price || "0", 10) || 0,
        bytes,
        enabled: f.enabled,
      };
      if (initial) await api.put(`/billing/traffic-packages/${initial.id}`, body);
      else await api.post("/billing/traffic-packages", body);
      toast.push(initial ? t("common.saved") : t("common.created"), "success");
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Modal
      open
      title={initial ? t("billing.editTrafficPackage") : t("billing.addTrafficPackage")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={busy || !f.name.trim()} onClick={submit}>
            {initial ? t("common.save") : t("common.create")}
          </Button>
        </>
      }
    >
      <div className="sk-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <div className="sk-row" style={{ gap: 12 }}>
          <Field label={t("billing.price")}>
            <Input type="number" value={f.price} onChange={upd("price")} />
          </Field>
          <Field label={t("billing.packageTraffic")}>
            <div className="sk-row" style={{ gap: 8 }}>
              <Input type="number" value={f.trafficValue} onChange={upd("trafficValue")} style={{ flex: 1 }} />
              <Select value={f.trafficUnit} onChange={upd("trafficUnit")} style={{ width: 88 }}>
                <option value="MB">MB</option>
                <option value="GB">GB</option>
              </Select>
            </div>
          </Field>
        </div>
        <label className="sk-row" style={{ gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={f.enabled} onChange={upd("enabled")} />
          <span>{t("common.enabled")}</span>
        </label>
      </div>
    </Modal>
  );
};

const UsageTab: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const { data, loading, error, reload } = useFetch<UsageSummary>(() => api.get("/billing/usage"), []);
  useLiveReload(() => { reload(); }, 20000);
  const currency = data?.currency_label ? ` ${data.currency_label}` : "";
  const isMaster = !!admin?.is_sudo || data?.subject_to_usage_billing === false;

  if (loading && !data) return <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={3} /></div>;
  if (error) return <EmptyState title={t("common.error")} desc={error} />;
  if (!data) return <EmptyState title={t("common.noData")} />;

  if (isMaster) {
    return (
      <div className="sk-stack" style={{ gap: 14 }}>
        <Callout tone="info" title={t("billing.usageMasterTitle")}>
          {t("billing.usageMasterHint")}
        </Callout>
        <div className="sk-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
          <Stat
            label={t("billing.usageRateResellerDefault")}
            value={`${data.rate_per_gb.toLocaleString()}${currency}`}
          />
          <Stat label={t("billing.usageOwnTraffic")} value={formatBytes(data.owned_bytes || 0)} />
          <Stat label={t("billing.usageSharedTraffic")} value={formatBytes(data.foreign_bytes || 0)} />
        </div>
        <p className="sk-muted" style={{ fontSize: 12, margin: 0 }}>
          {t("billing.usageMasterTrafficNote")}
        </p>
      </div>
    );
  }

  return (
    <div className="sk-stack" style={{ gap: 14 }}>
      {(data.prepaid_traffic_remaining ?? 0) <= 0 ? (
        <Callout tone="warn" title={t("billing.packageExhaustedTitle")}>
          <div className="sk-stack" style={{ gap: 10 }}>
            <span>{t("billing.packageExhaustedHint")}</span>
            <div>
              <Link to="/billing?billingTab=packages">
                <Button variant="primary" size="sm">{t("overview.buyPackageCta")}</Button>
              </Link>
            </div>
          </div>
        </Callout>
      ) : null}
      {data.wallet_blocked ? (
        <Callout tone="danger" title={t("overview.walletBlockedTitle")}>
          {t("overview.walletBlockedHint", {
            cost: data.estimated_cost.toLocaleString(),
            balance: data.wallet_balance.toLocaleString(),
            currency: data.currency_label || "",
            traffic: formatBytes((data.owned_bytes || 0) + (data.foreign_bytes || 0)),
          })}
        </Callout>
      ) : data.wallet_low ? (
        <Callout tone="warn" title={t("overview.lowWalletTitle")}>{t("overview.lowWalletHint")}</Callout>
      ) : null}
      {data.rate_per_gb <= 0 ? (
        <Callout tone="info">{t("billing.usageDisabled")}</Callout>
      ) : (
        <>
          <div className="sk-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
            <Stat
              label={t("billing.usageRate")}
              value={`${data.rate_per_gb.toLocaleString()}${currency}`}
            />
            <Stat label={t("billing.prepaidRemaining")} value={formatBytes(data.prepaid_traffic_remaining || 0)} />
            <Stat label={t("billing.packageCovered")} value={formatBytes(data.package_covered_bytes || 0)} />
            <Stat label={t("billing.usageOwnTraffic")} value={formatBytes(data.owned_bytes || 0)} />
            <Stat label={t("billing.usageSharedTraffic")} value={formatBytes(data.foreign_bytes || 0)} />
            <Stat
              label={t("billing.usageEstimate")}
              value={`${data.estimated_cost.toLocaleString()}${currency}`}
            />
            <Stat
              label={t("billing.wallet")}
              value={`${data.wallet_balance.toLocaleString()}${currency}`}
            />
          </div>
          {data.discount_percent > 0 ? (
            <Callout tone="info">{t("billing.usageByoDiscount", { pct: data.discount_percent })}</Callout>
          ) : null}
          <p className="sk-muted" style={{ fontSize: 12, margin: 0 }}>
            {t("billing.usagePeriod", {
              since: new Date(data.period_since).toLocaleString(),
              until: new Date(data.period_until).toLocaleString(),
            })}
          </p>
          {data.estimated_cost > 0 && !data.wallet_blocked ? (
            <Callout tone="info">{t("billing.usagePendingHint")}</Callout>
          ) : null}
        </>
      )}
    </div>
  );
};

const InvoicesTab: FC<{ onChanged?: () => void }> = ({ onChanged }) => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const toast = useToast();
  const [showCreate, setShowCreate] = useState(false);
  const { data, loading, error, reload } = useFetch<Invoice[]>(() => api.get("/billing/invoices"), []);
  const pager = usePagedList(data, 20);

  const pay = async (id: number) => {
    if (!confirm(t("billing.payConfirm", { id }))) return;
    try {
      await api.post(`/billing/invoices/${id}/pay`);
      toast.push(t("billing.paidDone"), "success");
      reload();
      onChanged?.();
    } catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <>
      {admin?.is_sudo && (
        <div className="sk-row" style={{ justifyContent: "flex-end", marginBottom: 14 }}>
          <Button variant="primary" onClick={() => setShowCreate(true)}><IcPlus className="sk-ico" /> {t("billing.createInvoice")}</Button>
        </div>
      )}
      {!admin?.is_sudo && (
        <div style={{ marginBottom: 14 }}>
          <Callout tone="info">{t("billing.payInvoiceHint")}</Callout>
        </div>
      )}
      {showCreate && <CreateInvoiceModal onClose={() => setShowCreate(false)} onDone={() => { setShowCreate(false); reload(); onChanged?.(); }} />}
    <Card pad0>
      {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={5} /></div>
        : error ? <EmptyState title={t("common.error")} desc={error} />
        : !data?.length ? <EmptyState title={t("common.noData")} />
        : (
          <ResponsiveData
            table={(
              <div className="sk-table-wrap"><table className="sk-table">
                <thead><tr>
                  <th>#</th>
                  <th className="sk-num">{t("billing.amount")}</th>
                  <th>{t("billing.description")}</th>
                  <th>{t("billing.invoiceStatus")}</th>
                  <th>{t("billing.provider")}</th>
                  <th className="sk-actions">{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {pager.slice.map((inv) => (
                    <tr key={inv.id}>
                      <td className="sk-faint">#{inv.id}</td>
                      <td className="sk-num" style={{ fontWeight: 600 }}>{inv.amount.toLocaleString()}</td>
                      <td className="sk-muted" style={{ maxWidth: 280 }}>{inv.description || "—"}</td>
                      <td><Pill tone={inv.status === "paid" ? "ok" : "warn"} dot>{t(`billing.status.${inv.status}`, inv.status)}</Pill></td>
                      <td>{inv.provider || "—"}</td>
                      <td className="sk-actions"><div className="sk-row" style={{ justifyContent: "flex-end" }}>
                        {inv.status === "pending" && (
                          <Button size="sm" variant="primary" onClick={() => pay(inv.id)}>
                            {t("billing.payFromWallet")}
                          </Button>
                        )}
                      </div></td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )}
            cards={pager.slice.map((inv) => (
              <MCard
                key={inv.id}
                title={inv.amount.toLocaleString()}
                subtitle={`#${inv.id}${inv.description ? ` · ${inv.description}` : ""}`}
                badge={<Pill tone={inv.status === "paid" ? "ok" : "warn"} dot>{t(`billing.status.${inv.status}`, inv.status)}</Pill>}
                fields={[
                  { label: t("billing.provider"), value: inv.provider || "—" },
                ]}
                actions={inv.status === "pending" ? (
                  <Button size="sm" variant="primary" onClick={() => pay(inv.id)}>
                    {t("billing.payFromWallet")}
                  </Button>
                ) : undefined}
              />
            ))}
          />
        )}
    </Card>
    <Pager page={pager.page} pages={pager.pages} onPage={pager.setPage} />
    </>
  );
};

const CreateInvoiceModal: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [amount, setAmount] = useState("");
  const [username, setUsername] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/billing/invoices", {
        amount: parseInt(amount, 10) || 0,
        username: username.trim() || undefined,
        description: description.trim() || undefined,
        provider: "manual",
      });
      toast.push(t("common.created"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open title={t("billing.createInvoice")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !amount} onClick={submit}>{t("common.create")}</Button></>}>
      <div className="sk-stack">
        <Field label={t("billing.amount")}><Input type="number" min="1" value={amount} onChange={(e: any) => setAmount(e.target.value)} autoFocus /></Field>
        <Field label={t("common.username")} hint={t("billing.invoiceUserHint")}>
          <Input value={username} onChange={(e: any) => setUsername(e.target.value)} />
        </Field>
        <Field label={t("billing.description")} hint={t("billing.invoiceDescriptionHint")}>
          <Input value={description} onChange={(e: any) => setDescription(e.target.value)} placeholder={t("billing.invoiceDescriptionPlaceholder")} />
        </Field>
      </div>
    </Modal>
  );
};

const TransactionsTab: FC = () => {
  const { t } = useTranslation();
  const { data, loading, error, reload } = useFetch<Transaction[]>(() => api.get("/billing/transactions"), []);
  useLiveReload(() => { reload(); }, 20000);
  const pager = usePagedList(data, 25);
  return (
    <>
    <Card pad0>
      {loading && !data ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
        : error ? <EmptyState title={t("common.error")} desc={error} />
        : !data?.length ? <EmptyState title={t("common.noData")} desc={t("billing.transactionsEmpty")} />
        : (
          <ResponsiveData
            table={(
              <div className="sk-table-wrap"><table className="sk-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>{t("billing.date")}</th>
                    <th>{t("billing.type")}</th>
                    <th className="sk-num">{t("billing.amount")}</th>
                    <th>{t("billing.description")}</th>
                  </tr>
                </thead>
                <tbody>
                  {pager.slice.map((tx) => (
                    <tr key={tx.id}>
                      <td className="sk-faint">#{tx.id}</td>
                      <td className="sk-muted">
                        {tx.created_at ? new Date(tx.created_at).toLocaleString() : "—"}
                      </td>
                      <td><Pill tone={tx.amount >= 0 ? "ok" : "danger"}>{tx.type}</Pill></td>
                      <td className="sk-num" style={{ fontWeight: 600, color: tx.amount >= 0 ? "var(--sk-ok)" : "var(--sk-danger)" }}>
                        {tx.amount >= 0 ? "+" : ""}{tx.amount.toLocaleString()}
                      </td>
                      <td className="sk-muted">{tx.description || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )}
            cards={pager.slice.map((tx) => (
              <MCard
                key={tx.id}
                title={(
                  <span style={{ color: tx.amount >= 0 ? "var(--sk-ok)" : "var(--sk-danger)" }}>
                    {tx.amount >= 0 ? "+" : ""}{tx.amount.toLocaleString()}
                  </span>
                )}
                subtitle={`#${tx.id} · ${tx.created_at ? new Date(tx.created_at).toLocaleString() : "—"}`}
                badge={<Pill tone={tx.amount >= 0 ? "ok" : "danger"}>{tx.type}</Pill>}
                fields={[
                  { label: t("billing.description"), value: tx.description || "—" },
                ]}
              />
            ))}
          />
        )}
    </Card>
    <Pager page={pager.page} pages={pager.pages} onPage={pager.setPage} />
    </>
  );
};
