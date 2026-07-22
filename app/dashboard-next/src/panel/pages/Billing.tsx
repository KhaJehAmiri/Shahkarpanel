import { FC, useEffect, useState } from "react";
import {
  bytesToDataLimitValue, dataLimitToBytes, detectDataLimitUnit, type DataLimitUnit,
} from "../lib/data-limit";
import { useTranslation } from "react-i18next";
import { useSearchParams, Link } from "react-router-dom";
import { api } from "../api/client";
import { Invoice, Plan, Transaction, TrafficPackage, TrafficPurchase, UsageSummary, Wallet } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch, useLiveReload } from "../lib/useFetch";
import { formatBytes } from "../lib/format";
import { PageHeader } from "../components/Shell";
import {
  Button, Callout, Card, EmptyState, Field, Input, Modal, Pager, Pill, Select, SkeletonRows, Stat, Tabs, usePagedList, useToast,
} from "../components/ui";
import { CommercialSettings } from "../components/CommercialSettings";
import { IcPlus, IcTrash, IcWallet, IcEdit } from "../components/icons";

const BILLING_TABS = ["plans", "packages", "usage", "invoices", "transactions", "settings"] as const;

export const Billing: FC<{ embedded?: boolean }> = ({ embedded }) => {
  const { t } = useTranslation();
  const { admin, isEnabled } = useApp();
  const toast = useToast();
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
  useLiveReload(() => { wallet.reload(); providers.reload(); }, 30000);
  const canTopUp = !admin?.is_sudo && (providers.data?.length ?? 0) > 0;

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

  if (!isEnabled("billing"))
    return (<div>{!embedded && <PageHeader title={t("billing.title")} subtitle={t("billing.subtitle")} />}<Callout tone="warn">{t("billing.billingDisabled")}</Callout></div>);

  return (
    <div>
      {!embedded && <PageHeader title={t("billing.title")} subtitle={t("billing.subtitle")} description={t("billing.description")} />}
      {wallet.loading ? (
        <div style={{ marginBottom: 16, maxWidth: 280 }}><SkeletonRows rows={1} cols={1} /></div>
      ) : wallet.data && (
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
      <Tabs active={tab} onChange={onTabChange} tabs={[
        { id: "plans", label: t("billing.tabPlans") },
        { id: "packages", label: t("billing.tabTrafficPackages") },
        { id: "usage", label: t("billing.tabUsage") },
        { id: "invoices", label: t("billing.tabInvoices") },
        { id: "transactions", label: t("billing.tabTransactions") },
        ...(admin?.is_sudo ? [{ id: "settings", label: t("billing.tabSettings") }] : []),
      ]} />
      {tab === "plans" && <PlansTab canWrite={!!admin?.is_sudo || admin?.role === "reseller"} />}
      {tab === "packages" && <TrafficPackagesTab onPurchased={() => wallet.reload()} />}
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
                    <td>{p.data_limit ? formatBytes(p.data_limit) : t("users.unlimited")}</td>
                    <td>{p.duration_days ? t("users.unitDays", { n: p.duration_days }) : t("users.unlimited")}</td>
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
      <div className="nx-stack">
        <Field label={t("common.username")}><Input value={username} onChange={(e: any) => setUsername(e.target.value)} /></Field>
        <Field label={t("resellers.adjustMode")}>
          <select className="nx-select" value={mode} onChange={(e: any) => setMode(e.target.value)}>
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
    <div className="nx-stack" style={{ gap: 14 }}>
      <div className="nx-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
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
        <div className="nx-row" style={{ justifyContent: "flex-end" }}>
          <Button variant="primary" onClick={() => setShow(true)}>
            <IcPlus className="nx-ico" /> {t("billing.addTrafficPackage")}
          </Button>
        </div>
      )}
      <Card pad0>
        {packages.loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
          : packages.error ? <EmptyState title={t("common.error")} desc={packages.error} />
          : !packages.data?.length ? <EmptyState title={t("common.noData")} desc={t("billing.noTrafficPackages")} />
          : (
            <div className="nx-table-wrap">
              <table className="nx-table">
                <thead><tr>
                  <th>{t("common.name")}</th>
                  <th>{t("billing.packageTraffic")}</th>
                  <th>{t("billing.price")}</th>
                  <th>{t("common.status")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {packages.data.map((pkg) => (
                    <tr key={pkg.id}>
                      <td>{pkg.name}</td>
                      <td>{formatBytes(pkg.bytes)}</td>
                      <td>{pkg.price.toLocaleString()}</td>
                      <td><Pill tone={pkg.enabled ? "ok" : "default"}>{pkg.enabled ? t("common.enabled") : t("common.disabled")}</Pill></td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                          {!isSudo && pkg.enabled && (
                            <Button size="sm" variant="primary" onClick={() => buy(pkg)}>{t("billing.buyPackage")}</Button>
                          )}
                          {isSudo && (
                            <>
                              <Button size="sm" variant="ghost" onClick={() => setEdit(pkg)}><IcEdit className="nx-ico" /></Button>
                              <Button size="sm" variant="danger" onClick={() => remove(pkg.id)}><IcTrash className="nx-ico" /></Button>
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
      </Card>
      {(purchases.data?.length ?? 0) > 0 && (
        <Card pad0>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--nx-border, #e5e7eb)" }}>
            <strong>{t("billing.purchaseHistory")}</strong>
          </div>
          <div className="nx-table-wrap">
            <table className="nx-table">
              <thead><tr>
                <th>{t("billing.date")}</th>
                <th>{t("billing.packageTraffic")}</th>
                <th>{t("billing.price")}</th>
                <th>{t("billing.purchaseSource")}</th>
              </tr></thead>
              <tbody>
                {purchases.data!.map((p) => (
                  <tr key={p.id}>
                    <td>{p.created_at ? new Date(p.created_at).toLocaleString() : "—"}</td>
                    <td>{formatBytes(p.bytes)}</td>
                    <td>{p.price_paid.toLocaleString()}</td>
                    <td>{p.source === "manual" ? t("billing.sourceManual") : t("billing.sourcePurchase")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
  const unit0 = initial ? detectDataLimitUnit(initial.bytes) : "GB" as DataLimitUnit;
  const [f, setF] = useState({
    name: initial?.name || "",
    price: String(initial?.price ?? ""),
    trafficValue: initial ? String(bytesToDataLimitValue(initial.bytes, unit0)) : "100",
    trafficUnit: unit0,
    enabled: initial?.enabled ?? true,
  });
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
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("billing.price")}>
            <Input type="number" value={f.price} onChange={upd("price")} />
          </Field>
          <Field label={t("billing.packageTraffic")}>
            <div className="nx-row" style={{ gap: 8 }}>
              <Input type="number" value={f.trafficValue} onChange={upd("trafficValue")} style={{ flex: 1 }} />
              <Select value={f.trafficUnit} onChange={upd("trafficUnit")} style={{ width: 88 }}>
                <option value="MB">MB</option>
                <option value="GB">GB</option>
              </Select>
            </div>
          </Field>
        </div>
        <label className="nx-row" style={{ gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={f.enabled} onChange={upd("enabled")} />
          <span>{t("common.enabled")}</span>
        </label>
      </div>
    </Modal>
  );
};

const UsageTab: FC = () => {
  const { t } = useTranslation();
  const { data, loading, error, reload } = useFetch<UsageSummary>(() => api.get("/billing/usage"), []);
  useLiveReload(() => { reload(); }, 20000);
  const currency = data?.currency_label ? ` ${data.currency_label}` : "";

  if (loading && !data) return <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={3} /></div>;
  if (error) return <EmptyState title={t("common.error")} desc={error} />;
  if (!data) return <EmptyState title={t("common.noData")} />;

  return (
    <div className="nx-stack" style={{ gap: 14 }}>
      {(data.prepaid_traffic_remaining ?? 0) <= 0 ? (
        <Callout tone="warn" title={t("billing.packageExhaustedTitle")}>
          <div className="nx-stack" style={{ gap: 10 }}>
            <span>{t("billing.packageExhaustedHint")}</span>
            <div>
              <Link to="/business?tab=billing&billingTab=packages">
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
          <div className="nx-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
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
          <p className="nx-muted" style={{ fontSize: 12, margin: 0 }}>
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

const InvoicesTab: FC = () => {
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
    } catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <>
      {admin?.is_sudo && (
        <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14 }}>
          <Button variant="primary" onClick={() => setShowCreate(true)}><IcPlus className="nx-ico" /> {t("billing.createInvoice")}</Button>
        </div>
      )}
      {!admin?.is_sudo && (
        <div style={{ marginBottom: 14 }}>
          <Callout tone="info">{t("billing.payInvoiceHint")}</Callout>
        </div>
      )}
      {showCreate && <CreateInvoiceModal onClose={() => setShowCreate(false)} onDone={() => { setShowCreate(false); reload(); }} />}
    <Card pad0>
      {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={5} /></div>
        : error ? <EmptyState title={t("common.error")} desc={error} />
        : !data?.length ? <EmptyState title={t("common.noData")} />
        : (
          <div className="nx-table-wrap"><table className="nx-table">
            <thead><tr>
              <th>#</th>
              <th>{t("billing.amount")}</th>
              <th>{t("billing.description")}</th>
              <th>{t("billing.invoiceStatus")}</th>
              <th>{t("billing.provider")}</th>
              <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
            </tr></thead>
            <tbody>
              {pager.slice.map((inv) => (
                <tr key={inv.id}>
                  <td className="nx-faint">#{inv.id}</td>
                  <td style={{ fontWeight: 600 }}>{inv.amount.toLocaleString()}</td>
                  <td className="nx-muted" style={{ maxWidth: 280 }}>{inv.description || "—"}</td>
                  <td><Pill tone={inv.status === "paid" ? "ok" : "warn"} dot>{t(`billing.status.${inv.status}`, inv.status)}</Pill></td>
                  <td>{inv.provider || "—"}</td>
                  <td><div className="nx-row" style={{ justifyContent: "flex-end" }}>
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
      <div className="nx-stack">
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
          <div className="nx-table-wrap"><table className="nx-table">
            <thead>
              <tr>
                <th>#</th>
                <th>{t("billing.date")}</th>
                <th>{t("billing.type")}</th>
                <th>{t("billing.amount")}</th>
                <th>{t("billing.description")}</th>
              </tr>
            </thead>
            <tbody>
              {pager.slice.map((tx) => (
                <tr key={tx.id}>
                  <td className="nx-faint">#{tx.id}</td>
                  <td className="nx-muted">
                    {tx.created_at ? new Date(tx.created_at).toLocaleString() : "—"}
                  </td>
                  <td><Pill tone={tx.amount >= 0 ? "ok" : "danger"}>{tx.type}</Pill></td>
                  <td style={{ fontWeight: 600, color: tx.amount >= 0 ? "var(--nx-ok)" : "var(--nx-danger)" }}>
                    {tx.amount >= 0 ? "+" : ""}{tx.amount.toLocaleString()}
                  </td>
                  <td className="nx-muted">{tx.description || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
    </Card>
    <Pager page={pager.page} pages={pager.pages} onPage={pager.setPage} />
    </>
  );
};
