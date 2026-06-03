import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { Invoice, Plan, Transaction, Wallet } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { formatBytes } from "../lib/format";
import { PageHeader } from "../components/Shell";
import {
  Button, Callout, Card, EmptyState, Field, Input, Modal, Pill, SkeletonRows, Stat, Tabs, useToast,
} from "../components/ui";
import { IcPlus, IcTrash, IcWallet } from "../components/icons";

export const Billing: FC = () => {
  const { t } = useTranslation();
  const { isEnabled } = useApp();
  const [tab, setTab] = useState("plans");
  const wallet = useFetch<Wallet>(() => api.get("/billing/wallet"), []);

  if (!isEnabled("billing"))
    return (<div><PageHeader title={t("billing.title")} subtitle={t("billing.subtitle")} /><Callout tone="warn">{t("billing.billingDisabled")}</Callout></div>);

  return (
    <div>
      <PageHeader title={t("billing.title")} subtitle={t("billing.subtitle")} description={t("billing.description")} />
      {wallet.data && (
        <div style={{ marginBottom: 16, maxWidth: 280 }}>
          <Stat label={t("billing.wallet")} value={wallet.data.balance.toLocaleString()} icon={<IcWallet className="nx-stat-ico" />} />
        </div>
      )}
      <Tabs active={tab} onChange={setTab} tabs={[
        { id: "plans", label: t("billing.tabPlans") },
        { id: "invoices", label: t("billing.tabInvoices") },
        { id: "transactions", label: t("billing.tabTransactions") },
      ]} />
      {tab === "plans" && <PlansTab />}
      {tab === "invoices" && <InvoicesTab />}
      {tab === "transactions" && <TransactionsTab />}
    </div>
  );
};

const PlansTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const { data, loading, error, reload } = useFetch<Plan[]>(() => api.get("/plans"), []);

  const remove = async (id: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try { await api.del(`/plans/${id}`); toast.push(t("common.deleted"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <>
      <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14 }}>
        <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("billing.addPlan")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !data?.length ? <EmptyState title={t("common.noData")} action={<Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("billing.addPlan")}</Button>} />
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
                    <td><div className="nx-row" style={{ justifyContent: "flex-end" }}><Button variant="danger" size="sm" onClick={() => remove(p.id)}><IcTrash className="nx-ico" /></Button></div></td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
      </Card>
      {show && <AddPlan onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
    </>
  );
};

const AddPlan: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState({ name: "", price: "0", dataGb: "", days: "", devices: "" });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/plans", {
        name: f.name.trim(), price: parseInt(f.price) || 0,
        data_limit: f.dataGb ? Math.round(parseFloat(f.dataGb) * 1024 ** 3) : null,
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
          <Field label={t("billing.dataLimit")}><Input type="number" value={f.dataGb} onChange={upd("dataGb")} /></Field>
        </div>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("billing.duration")}><Input type="number" value={f.days} onChange={upd("days")} /></Field>
          <Field label={t("billing.deviceLimit")}><Input type="number" value={f.devices} onChange={upd("devices")} /></Field>
        </div>
      </div>
    </Modal>
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
