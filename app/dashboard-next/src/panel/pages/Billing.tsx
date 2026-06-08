import { FC, useState } from "react";
import {
  bytesToDataLimitValue, dataLimitToBytes, detectDataLimitUnit, type DataLimitUnit,
} from "../lib/data-limit";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { Invoice, Plan, Transaction, UsageSummary, Wallet } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { formatBytes } from "../lib/format";
import { PageHeader } from "../components/Shell";
import {
  Button, Callout, Card, EmptyState, Field, Input, Modal, Pill, Select, SkeletonRows, Stat, Tabs, useToast,
} from "../components/ui";
import { CommercialSettings } from "../components/CommercialSettings";
import { IcPlus, IcTrash, IcWallet, IcEdit } from "../components/icons";

export const Billing: FC = () => {
  const { t } = useTranslation();
  const { admin, isEnabled } = useApp();
  const toast = useToast();
  const [tab, setTab] = useState("plans");
  const [creditOpen, setCreditOpen] = useState(false);
  const [topupOpen, setTopupOpen] = useState(false);
  const wallet = useFetch<Wallet>(() => api.get("/billing/wallet"), []);
  const providers = useFetch<string[]>(() => api.get("/billing/payment-providers"), []);
  const canTopUp = !admin?.is_sudo && (providers.data?.length ?? 0) > 0;

  if (!isEnabled("billing"))
    return (<div><PageHeader title={t("billing.title")} subtitle={t("billing.subtitle")} /><Callout tone="warn">{t("billing.billingDisabled")}</Callout></div>);

  return (
    <div>
      <PageHeader title={t("billing.title")} subtitle={t("billing.subtitle")} description={t("billing.description")} />
      {wallet.data && (
        <div className="nx-row" style={{ marginBottom: 16, gap: 12, alignItems: "flex-end" }}>
          <div style={{ maxWidth: 280, flex: 1 }}>
            <Stat label={t("billing.wallet")} value={wallet.data.balance.toLocaleString()} icon={<IcWallet className="nx-stat-ico" />} />
          </div>
          {admin?.is_sudo ? (
            <Button variant="primary" size="sm" onClick={() => setCreditOpen(true)}>{t("billing.addCredit")}</Button>
          ) : canTopUp ? (
            <Button variant="primary" size="sm" onClick={() => setTopupOpen(true)}>{t("billing.topUp")}</Button>
          ) : (
            <Callout tone="info">{t("billing.resellerWalletHint")}</Callout>
          )}
        </div>
      )}
      {creditOpen && <CreditModal onClose={() => setCreditOpen(false)} onDone={() => { setCreditOpen(false); wallet.reload(); }} />}
      {topupOpen && providers.data && (
        <TopUpModal providers={providers.data} onClose={() => setTopupOpen(false)} onDone={() => { setTopupOpen(false); wallet.reload(); }} />
      )}
      <Tabs active={tab} onChange={setTab} tabs={[
        { id: "plans", label: t("billing.tabPlans") },
        { id: "usage", label: t("billing.tabUsage") },
        { id: "invoices", label: t("billing.tabInvoices") },
        { id: "transactions", label: t("billing.tabTransactions") },
        ...(admin?.is_sudo ? [{ id: "settings", label: t("billing.tabSettings") }] : []),
      ]} />
      {tab === "plans" && <PlansTab canWrite={!!admin?.is_sudo || admin?.role === "reseller"} />}
      {tab === "usage" && <UsageTab />}
      {tab === "settings" && admin?.is_sudo && <CommercialSettings />}
      {tab === "invoices" && <InvoicesTab />}
      {tab === "transactions" && <TransactionsTab />}
    </div>
  );
};

const PlansTab: FC<{ canWrite?: boolean }> = ({ canWrite = false }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<Plan | null>(null);
  const { data, loading, error, reload } = useFetch<Plan[]>(() => api.get("/plans"), []);

  const remove = async (id: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try { await api.del(`/plans/${id}`); toast.push(t("common.deleted"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <>
      {canWrite && (
        <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14 }}>
          <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("billing.addPlan")}</Button>
        </div>
      )}
      {!canWrite && (
        <div style={{ marginBottom: 14 }}>
          <Callout tone="info">{t("billing.plansReadOnly")}</Callout>
        </div>
      )}
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !data?.length ? <EmptyState title={t("common.noData")} desc={t("billing.plansReadOnly")} />
          : (
            <div className="nx-table-wrap"><table className="nx-table">
              <thead><tr><th>{t("common.name")}</th><th>{t("billing.price")}</th><th>{t("users.dataLimit")}</th><th>{t("billing.duration")}</th><th>{t("common.status")}</th><th style={{ textAlign: "end" }}>{t("common.actions")}</th></tr></thead>
              <tbody>
                {data.map((p) => (
                  <tr key={p.id}>
                    <td style={{ fontWeight: 600 }}>{p.name}</td>
                    <td>{p.price.toLocaleString()}</td>
                    <td>{p.data_limit ? formatBytes(p.data_limit) : "∞"}</td>
                    <td>{p.duration_days ? `${p.duration_days}d` : "∞"}</td>
                    <td><Pill tone={p.enabled ? "ok" : "default"} dot>{p.enabled ? t("common.enabled") : t("common.disabled")}</Pill></td>
                    <td>{canWrite ? (
                      <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                        <Button size="sm" variant="ghost" onClick={() => setEdit(p)}><IcEdit className="nx-ico" /></Button>
                        <Button variant="danger" size="sm" onClick={() => remove(p.id)}><IcTrash className="nx-ico" /></Button>
                      </div>
                    ) : null}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
      </Card>
      {show && <AddPlan onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
      {edit && <EditPlan plan={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </>
  );
};

const TopUpModal: FC<{ providers: string[]; onClose: () => void; onDone: () => void }> = ({ providers, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [amount, setAmount] = useState("");
  const [provider, setProvider] = useState(providers[0] || "demo");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const created = await api.post<{ payment_id: number; confirm_token?: string; checkout_url?: string }>("/billing/topup", {
        amount: parseInt(amount, 10) || 0,
        provider,
      });
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

  return (
    <Modal open title={t("billing.topUp")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !amount} onClick={submit}>{t("billing.topUpPay")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("billing.creditAmount")}><Input type="number" value={amount} onChange={(e: any) => setAmount(e.target.value)} autoFocus /></Field>
        <Field label={t("billing.provider")}>
          <Select value={provider} onChange={(e: any) => setProvider(e.target.value)}>
            {providers.map((p) => <option key={p} value={p}>{p}</option>)}
          </Select>
        </Field>
        <Callout tone="info">{t("billing.topUpHint")}</Callout>
      </div>
    </Modal>
  );
};

const CreditModal: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [username, setUsername] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/billing/credit", { username: username.trim(), amount: parseInt(amount, 10) || 0 });
      toast.push(t("common.saved"), "success");
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open title={t("billing.addCredit")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !username || !amount} onClick={submit}>{t("common.save")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("common.username")}><Input value={username} onChange={(e: any) => setUsername(e.target.value)} /></Field>
        <Field label={t("billing.creditAmount")}><Input type="number" value={amount} onChange={(e: any) => setAmount(e.target.value)} /></Field>
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
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} /></Field>
        <Field label={t("billing.price")}><Input type="number" value={f.price} onChange={upd("price")} /></Field>
        <Field label={t("billing.dataLimit")}>
          <div className="nx-row" style={{ gap: 8 }}>
            <Input type="number" value={f.dataLimitValue} onChange={upd("dataLimitValue")} style={{ flex: 1 }} />
            <Select value={f.dataLimitUnit} onChange={upd("dataLimitUnit")} style={{ width: 88 }}>
              <option value="MB">MB</option>
              <option value="GB">GB</option>
            </Select>
          </div>
        </Field>
        <label className="nx-row" style={{ gap: 8 }}><input type="checkbox" checked={f.enabled} onChange={upd("enabled")} /> {t("common.enabled")}</label>
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
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("billing.price")}><Input type="number" value={f.price} onChange={upd("price")} /></Field>
          <Field label={t("billing.dataLimit")}>
            <div className="nx-row" style={{ gap: 8 }}>
              <Input type="number" value={f.dataLimitValue} onChange={upd("dataLimitValue")} style={{ flex: 1 }} />
              <Select value={f.dataLimitUnit} onChange={upd("dataLimitUnit")} style={{ width: 88 }}>
                <option value="MB">MB</option>
                <option value="GB">GB</option>
              </Select>
            </div>
          </Field>
        </div>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("billing.duration")}><Input type="number" value={f.days} onChange={upd("days")} /></Field>
          <Field label={t("billing.deviceLimit")}><Input type="number" value={f.devices} onChange={upd("devices")} /></Field>
        </div>
      </div>
    </Modal>
  );
};

const UsageTab: FC = () => {
  const { t } = useTranslation();
  const { data, loading, error } = useFetch<UsageSummary>(() => api.get("/billing/usage"), []);

  if (loading) return <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={3} /></div>;
  if (error) return <EmptyState title={t("common.error")} desc={error} />;
  if (!data) return <EmptyState title={t("common.noData")} />;

  return (
    <div className="nx-stack" style={{ gap: 14 }}>
      {data.wallet_low ? (
        <Callout tone="warn" title={t("overview.lowWalletTitle")}>{t("overview.lowWalletHint")}</Callout>
      ) : null}
      {data.rate_per_gb <= 0 ? (
        <Callout tone="info">{t("billing.usageDisabled")}</Callout>
      ) : (
        <>
          <div className="nx-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
            <Stat label={t("billing.usageRate")} value={data.rate_per_gb.toLocaleString()} />
            <Stat label={t("billing.usageOwnGb")} value={String(data.owned_gb)} />
            <Stat label={t("billing.usageSharedGb")} value={String(data.foreign_gb)} />
            <Stat label={t("billing.usageEstimate")} value={data.estimated_cost.toLocaleString()} />
          </div>
          {data.discount_percent > 0 ? (
            <Callout tone="info">{t("billing.usageByoDiscount", { pct: data.discount_percent })}</Callout>
          ) : null}
          <p className="nx-muted" style={{ fontSize: 12, margin: 0 }}>
            {t("billing.usagePeriod", {
              since: new Date(data.period_since).toLocaleString(),
              until: new Date(data.period_until).toLocaleString(),
            })}
          </p>
        </>
      )}
    </div>
  );
};

const InvoicesTab: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const toast = useToast();
  const { data, loading, error, reload } = useFetch<Invoice[]>(() => api.get("/billing/invoices"), []);

  const pay = async (id: number) => {
    try { await api.post(`/billing/invoices/${id}/pay`); toast.push(t("common.saved"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <Card pad0>
      {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
        : error ? <EmptyState title={t("common.error")} desc={error} />
        : !data?.length ? <EmptyState title={t("common.noData")} />
        : (
          <div className="nx-table-wrap"><table className="nx-table">
            <thead><tr><th>#</th><th>{t("billing.amount")}</th><th>{t("billing.invoiceStatus")}</th><th>{t("billing.provider")}</th><th style={{ textAlign: "end" }}>{t("common.actions")}</th></tr></thead>
            <tbody>
              {data.map((inv) => (
                <tr key={inv.id}>
                  <td className="nx-faint">#{inv.id}</td>
                  <td style={{ fontWeight: 600 }}>{inv.amount.toLocaleString()}</td>
                  <td><Pill tone={inv.status === "paid" ? "ok" : "warn"} dot>{inv.status}</Pill></td>
                  <td>{inv.provider || "—"}</td>
                  <td><div className="nx-row" style={{ justifyContent: "flex-end" }}>
                    {admin?.is_sudo && inv.status !== "paid" && <Button size="sm" onClick={() => pay(inv.id)}>{t("billing.pay")}</Button>}
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
    </Card>
  );
};

const TransactionsTab: FC = () => {
  const { t } = useTranslation();
  const { data, loading, error } = useFetch<Transaction[]>(() => api.get("/billing/transactions"), []);
  return (
    <Card pad0>
      {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
        : error ? <EmptyState title={t("common.error")} desc={error} />
        : !data?.length ? <EmptyState title={t("common.noData")} />
        : (
          <div className="nx-table-wrap"><table className="nx-table">
            <thead><tr><th>#</th><th>{t("billing.type")}</th><th>{t("billing.amount")}</th><th>{t("billing.description")}</th></tr></thead>
            <tbody>
              {data.map((tx) => (
                <tr key={tx.id}>
                  <td className="nx-faint">#{tx.id}</td>
                  <td><Pill tone={tx.amount >= 0 ? "ok" : "danger"}>{tx.type}</Pill></td>
                  <td style={{ fontWeight: 600, color: tx.amount >= 0 ? "var(--nx-ok)" : "var(--nx-danger)" }}>{tx.amount >= 0 ? "+" : ""}{tx.amount.toLocaleString()}</td>
                  <td className="nx-muted">{tx.description || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
    </Card>
  );
};
