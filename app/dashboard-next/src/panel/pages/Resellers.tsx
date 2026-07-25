import { FC, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { Branding, SubResellerAccount, Tenant } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { formatBytes } from "../lib/format";
import { PageHeader } from "../components/Shell";
import {
  Button, Callout, Card, CardHead, EmptyState, Field, Input, Modal, Pager, Pill, SkeletonRows, Tabs, Textarea, usePagedList, useToast,
} from "../components/ui";
import { IcPlus, IcTrash, IcServer, IcEdit, IcWallet } from "../components/icons";
import { UserImportWizard } from "../components/UserImportWizard";

type ResellerAccount = {
  username: string;
  is_sudo: boolean;
  role?: string;
  max_users?: number | null;
  max_nodes?: number | null;
  max_total_traffic?: number | null;
  users_usage?: number | null;
  wallet_balance?: number | null;
  prepaid_traffic_remaining?: number | null;
};

export const Resellers: FC<{ embedded?: boolean }> = ({ embedded }) => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const [tab, setTab] = useState(admin?.is_sudo ? "accounts" : "branding");
  const tabs = [
    ...(admin?.is_sudo ? [
      { id: "accounts", label: t("resellers.tabAccounts") },
      { id: "tenants", label: t("resellers.tabTenants") },
    ] : [
      { id: "subaccounts", label: t("resellers.tabSubAccounts") },
      { id: "account", label: t("resellers.tabAccount") },
      { id: "migration", label: t("resellers.tabMigration") },
    ]),
    { id: "branding", label: t("resellers.tabBranding") },
    { id: "provision", label: t("infra.addNode") },
  ];
  return (
    <div>
      {!embedded && <PageHeader title={t("resellers.title")} subtitle={t("resellers.subtitle")} description={t("resellers.description")} />}
      <Tabs active={tab} onChange={setTab} tabs={tabs} />
      {tab === "accounts" && <ResellerAccountsTab />}
      {tab === "subaccounts" && <SubResellersTab />}
      {tab === "tenants" && <TenantsTab />}
      {tab === "branding" && <BrandingTab />}
      {tab === "account" && <AccountTab />}
      {tab === "migration" && <MigrationTab />}
      {tab === "provision" && <ProvisionTab />}
    </div>
  );
};

const SubResellersTab: FC = () => {
  const { t } = useTranslation();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<SubResellerAccount | null>(null);
  const { data, loading, error, reload } = useFetch<SubResellerAccount[]>(() => api.get("/reseller/sub-accounts"), []);

  return (
    <>
      <div style={{ marginBottom: 14 }}>
        <Callout tone="info">{t("resellers.subAccountsHint")}</Callout>
      </div>
      <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14 }}>
        <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("resellers.addSubAccount")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !data?.length ? <EmptyState title={t("resellers.noSubAccounts")} desc={t("resellers.subAccountsHint")} />
          : (
            <div className="nx-table-wrap">
              <table className="nx-table">
                <thead><tr>
                  <th>{t("common.username")}</th>
                  <th>{t("system.maxUsers")}</th>
                  <th>{t("system.maxNodes")}</th>
                  <th>{t("resellers.commission")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {data.map((a) => (
                    <tr key={a.username}>
                      <td><code>{a.username}</code></td>
                      <td>{a.max_users ?? "∞"}</td>
                      <td>{a.max_nodes ?? "∞"}</td>
                      <td>{a.commission_percent ?? 0}%</td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end" }}>
                          <Button size="sm" variant="ghost" onClick={() => setEdit(a)}><IcEdit className="nx-ico" /></Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      {show && <AddSubReseller onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
      {edit && <EditSubReseller account={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </>
  );
};

const EditSubReseller: FC<{ account: SubResellerAccount; onClose: () => void; onDone: () => void }> = ({ account, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [maxUsers, setMaxUsers] = useState(account.max_users != null ? String(account.max_users) : "");
  const [maxNodes, setMaxNodes] = useState(account.max_nodes != null ? String(account.max_nodes) : "");
  const [commission, setCommission] = useState(String(account.commission_percent ?? 0));
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        commission_percent: parseInt(commission, 10) || 0,
      };
      if (maxUsers.trim()) body.max_users = parseInt(maxUsers, 10);
      if (maxNodes.trim()) body.max_nodes = parseInt(maxNodes, 10);
      if (password.trim()) body.password = password;
      await api.patch(`/reseller/sub-accounts/${encodeURIComponent(account.username)}`, body);
      toast.push(t("common.saved"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open title={`${t("common.edit")} — ${account.username}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy} onClick={save}>{t("common.save")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("system.maxUsers")} hint={t("common.optional")}>
          <Input type="number" value={maxUsers} onChange={(e: any) => setMaxUsers(e.target.value)} placeholder="∞" />
        </Field>
        <Field label={t("system.maxNodes")} hint={t("common.optional")}>
          <Input type="number" value={maxNodes} onChange={(e: any) => setMaxNodes(e.target.value)} placeholder="∞" />
        </Field>
        <Field label={t("resellers.commission")} hint={t("resellers.commissionHint")}>
          <Input type="number" min={0} max={100} value={commission} onChange={(e: any) => setCommission(e.target.value)} />
        </Field>
        <Field label={t("system.newPassword")} hint={t("common.optional")}>
          <Input type="password" value={password} onChange={(e: any) => setPassword(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
};

const AddSubReseller: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [maxUsers, setMaxUsers] = useState("");
  const [maxNodes, setMaxNodes] = useState("");
  const [commission, setCommission] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = { username: username.trim(), password };
      if (maxUsers.trim()) body.max_users = parseInt(maxUsers, 10);
      if (maxNodes.trim()) body.max_nodes = parseInt(maxNodes, 10);
      if (commission.trim()) body.commission_percent = parseInt(commission, 10);
      await api.post("/reseller/sub-accounts", body);
      toast.push(t("common.created"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open title={t("resellers.addSubAccount")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !username.trim() || !password} onClick={submit}>{t("common.create")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("common.username")}><Input value={username} onChange={(e: any) => setUsername(e.target.value)} autoFocus /></Field>
        <Field label={t("common.password")}><Input type="password" value={password} onChange={(e: any) => setPassword(e.target.value)} /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={`${t("system.maxUsers")} (${t("common.optional")})`}>
            <Input type="number" value={maxUsers} onChange={(e: any) => setMaxUsers(e.target.value)} placeholder="∞" />
          </Field>
          <Field label={`${t("system.maxNodes")} (${t("common.optional")})`}>
            <Input type="number" value={maxNodes} onChange={(e: any) => setMaxNodes(e.target.value)} placeholder="∞" />
          </Field>
        </div>
        <Field label={`${t("resellers.commission")} (${t("common.optional")})`} hint={t("resellers.commissionHint")}>
          <Input type="number" min={0} max={100} value={commission} onChange={(e: any) => setCommission(e.target.value)} placeholder="0" />
        </Field>
      </div>
    </Modal>
  );
};

const ResellerAccountsTab: FC = () => {
  const { t } = useTranslation();
  const { isEnabled } = useApp();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<ResellerAccount | null>(null);
  const [credit, setCredit] = useState<ResellerAccount | null>(null);
  const [trafficCredit, setTrafficCredit] = useState<ResellerAccount | null>(null);
  const { data, loading, error, reload, status } = useFetch<ResellerAccount[]>(() => api.get("/admins"), []);
  const billingOn = isEnabled("billing");

  const [search, setSearch] = useState("");
  const accounts = (data || []).filter(
    (a) => !a.is_sudo && (!search.trim() || a.username.toLowerCase().includes(search.trim().toLowerCase())),
  );
  const pager = usePagedList(accounts, 20);

  if (status === 403) return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;

  const remove = async (a: ResellerAccount) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      await api.del(`/admin/${encodeURIComponent(a.username)}`);
      toast.push(t("common.deleted"), "success");
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  return (
    <>
      <div style={{ marginBottom: 14 }}>
        <Callout tone="info" title={t("resellers.accountsHintTitle")}>
          {t("resellers.accountsHint")}
        </Callout>
        {!billingOn && (
          <div style={{ marginTop: 10 }}>
            <Callout tone="warn">{t("resellers.billingDisabledHint")}</Callout>
          </div>
        )}
      </div>
      <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14, gap: 8 }}>
        {(data?.length ?? 0) > 8 && (
          <Input value={search} onChange={(e: any) => { setSearch(e.target.value); pager.setPage(0); }} placeholder={t("common.search")} style={{ maxWidth: 220 }} />
        )}
        <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("resellers.addAccount")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={4} cols={5} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !accounts.length ? (
            <EmptyState
              title={t("resellers.noAccounts")}
              desc={t("resellers.accountsHint")}
              action={<Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("resellers.addAccount")}</Button>}
            />
          ) : (
            <div className="nx-table-wrap">
              <table className="nx-table">
                <thead><tr>
                  <th>{t("common.username")}</th>
                  <th>{t("system.role")}</th>
                  <th>{t("billing.wallet")}</th>
                  <th>{t("billing.prepaidRemaining")}</th>
                  <th>{t("resellers.trafficUsed")}</th>
                  <th>{t("system.maxUsers")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {pager.slice.map((a) => (
                    <tr key={a.username}>
                      <td><code>{a.username}</code></td>
                      <td><Pill tone="default">{a.role || "reseller"}</Pill></td>
                      <td>{billingOn ? (a.wallet_balance ?? 0).toLocaleString() : "—"}</td>
                      <td>{billingOn ? formatBytes(a.prepaid_traffic_remaining ?? 0) : "—"}</td>
                      <td>
                        {formatBytes(a.users_usage ?? 0)}
                        <span className="nx-faint">
                          {" / "}
                          {a.max_total_traffic != null ? formatBytes(a.max_total_traffic) : "∞"}
                          {a.max_total_traffic != null
                            ? ` (${formatBytes(Math.max(0, (a.max_total_traffic ?? 0) - (a.users_usage ?? 0)))} left)`
                            : ""}
                        </span>
                      </td>
                      <td>{a.max_users ?? "∞"}</td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                          {billingOn && (
                            <>
                              <Button size="sm" variant="primary" title={t("resellers.adjustWallet")} onClick={() => setCredit(a)}>
                                <IcWallet className="nx-ico" /> {t("resellers.adjustWallet")}
                              </Button>
                              <Button size="sm" variant="ghost" title={t("resellers.creditTraffic")} onClick={() => setTrafficCredit(a)}>
                                {t("resellers.creditTraffic")}
                              </Button>
                            </>
                          )}
                          <Button size="sm" variant="ghost" title={t("common.edit")} onClick={() => setEdit(a)}><IcEdit className="nx-ico" /></Button>
                          <Button size="sm" variant="danger" title={t("common.delete")} onClick={() => remove(a)}><IcTrash className="nx-ico" /></Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      <Pager page={pager.page} pages={pager.pages} onPage={pager.setPage} />
      {show && <AddResellerAccount onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
      {edit && <EditResellerAccount account={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
      {credit && <CreditResellerAccount account={credit} onClose={() => setCredit(null)} onDone={() => { setCredit(null); reload(); }} />}
      {trafficCredit && (
        <CreditResellerTraffic
          account={trafficCredit}
          onClose={() => setTrafficCredit(null)}
          onDone={() => { setTrafficCredit(null); reload(); }}
        />
      )}
    </>
  );
};

const CreditResellerTraffic: FC<{ account: ResellerAccount; onClose: () => void; onDone: () => void }> = ({ account, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [gb, setGb] = useState("100");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const n = parseFloat(gb);
      if (!Number.isFinite(n) || n <= 0) throw new Error(t("billing.packageTrafficRequired"));
      const bytes = Math.round(n * (1024 ** 3));
      await api.post("/billing/traffic-packages/credit", {
        username: account.username,
        bytes,
        description: description.trim() || undefined,
      });
      toast.push(t("resellers.trafficCreditDone"), "success");
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open title={`${t("resellers.creditTraffic")} — ${account.username}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !gb} onClick={submit}>{t("common.save")}</Button></>}>
      <div className="nx-stack">
        <Callout tone="info">
          {t("resellers.prepaidHint", { remaining: formatBytes(account.prepaid_traffic_remaining ?? 0) })}
        </Callout>
        <Field label={t("billing.packageTrafficGb")} hint={t("resellers.creditTrafficHint")}>
          <Input type="number" value={gb} onChange={(e: any) => setGb(e.target.value)} autoFocus />
        </Field>
        <Field label={`${t("billing.description")} (${t("common.optional")})`}>
          <Input value={description} onChange={(e: any) => setDescription(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
};

const CreditResellerAccount: FC<{ account: ResellerAccount; onClose: () => void; onDone: () => void }> = ({ account, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [mode, setMode] = useState<"set" | "delta">("set");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const amt = parseInt(amount, 10);
      if (Number.isNaN(amt)) throw new Error(t("billing.creditAmountHint"));
      if (mode === "set" && amt < 0) throw new Error(t("resellers.setBalanceHint"));
      if (mode === "delta" && amt === 0) throw new Error(t("resellers.deltaAmountHint"));
      await api.post("/billing/adjust", {
        username: account.username,
        mode,
        amount: amt,
        description: description.trim() || undefined,
      });
      toast.push(t("billing.creditDone"), "success");
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open title={`${t("resellers.adjustWallet")} — ${account.username}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || amount === ""} onClick={submit}>{t("common.save")}</Button></>}>
      <div className="nx-stack">
        <Callout tone="info">
          {t("resellers.creditBalanceHint", { balance: (account.wallet_balance ?? 0).toLocaleString() })}
        </Callout>
        <Field label={t("resellers.adjustMode")}>
          <select className="nx-select" value={mode} onChange={(e: any) => setMode(e.target.value)}>
            <option value="set">{t("resellers.modeSetBalance")}</option>
            <option value="delta">{t("resellers.modeDelta")}</option>
          </select>
        </Field>
        <Field
          label={mode === "set" ? t("resellers.newBalance") : t("billing.creditAmount")}
          hint={mode === "set" ? t("resellers.setBalanceHint") : t("resellers.deltaAmountHint")}
        >
          <Input type="number" value={amount} onChange={(e: any) => setAmount(e.target.value)} autoFocus />
        </Field>
        <Field label={`${t("billing.description")} (${t("common.optional")})`}>
          <Input value={description} onChange={(e: any) => setDescription(e.target.value)} placeholder={t("resellers.creditNotePlaceholder")} />
        </Field>
      </div>
    </Modal>
  );
};

const AddResellerAccount: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("reseller");
  const [maxUsers, setMaxUsers] = useState("");
  const [maxNodes, setMaxNodes] = useState("");
  const [maxTraffic, setMaxTraffic] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = { username: username.trim(), password, is_sudo: false, role };
      if (maxUsers.trim()) body.max_users = parseInt(maxUsers, 10);
      if (maxNodes.trim()) body.max_nodes = parseInt(maxNodes, 10);
      if (maxTraffic.trim()) body.max_total_traffic = Math.round(parseFloat(maxTraffic) * 1024 ** 3);
      await api.post("/admin", body);
      toast.push(t("common.created"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open title={t("resellers.addAccount")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !username.trim() || !password} onClick={submit}>{t("common.create")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("common.username")} hint={t("resellers.loginUsernameHint")}>
          <Input value={username} onChange={(e: any) => setUsername(e.target.value)} autoFocus />
        </Field>
        <Field label={t("common.password")} hint={t("resellers.loginPasswordHint")}>
          <Input type="password" value={password} onChange={(e: any) => setPassword(e.target.value)} />
        </Field>
        <Field label={t("system.role")}>
          <select className="nx-input" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="reseller">reseller</option>
            <option value="support">support</option>
          </select>
        </Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={`${t("system.maxUsers")} (${t("common.optional")})`}>
            <Input type="number" min={1} value={maxUsers} onChange={(e: any) => setMaxUsers(e.target.value)} placeholder="∞" />
          </Field>
          <Field label={`${t("system.maxNodes")} (${t("common.optional")})`}>
            <Input type="number" min={1} value={maxNodes} onChange={(e: any) => setMaxNodes(e.target.value)} placeholder="∞" />
          </Field>
        </div>
        <Field label={`${t("system.maxTotalTraffic")} (${t("common.optional")})`} hint={t("system.maxTotalTrafficHint")}>
          <Input type="number" min={0} step="0.1" value={maxTraffic} onChange={(e: any) => setMaxTraffic(e.target.value)} placeholder="∞" />
        </Field>
      </div>
    </Modal>
  );
};

const BYTES_PER_GB = 1024 ** 3;

const EditResellerAccount: FC<{ account: ResellerAccount; onClose: () => void; onDone: () => void }> = ({ account, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [role, setRole] = useState(account.role || "reseller");
  const [maxUsers, setMaxUsers] = useState(account.max_users != null ? String(account.max_users) : "");
  const [maxNodes, setMaxNodes] = useState(account.max_nodes != null ? String(account.max_nodes) : "");
  const [maxTraffic, setMaxTraffic] = useState(
    account.max_total_traffic != null ? String(+(account.max_total_traffic / BYTES_PER_GB).toFixed(2)) : ""
  );
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = { is_sudo: false, role };
      if (maxUsers.trim()) body.max_users = parseInt(maxUsers, 10);
      if (maxNodes.trim()) body.max_nodes = parseInt(maxNodes, 10);
      body.max_total_traffic = maxTraffic.trim() ? Math.round(parseFloat(maxTraffic) * BYTES_PER_GB) : null;
      if (password.trim()) body.password = password;
      await api.put(`/admin/${encodeURIComponent(account.username)}`, body);
      toast.push(t("common.saved"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open title={`${t("common.edit")} — ${account.username}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy} onClick={save}>{t("common.save")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("system.role")}>
          <select className="nx-input" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="reseller">reseller</option>
            <option value="support">support</option>
          </select>
        </Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={`${t("system.maxUsers")} (${t("common.optional")})`}>
            <Input type="number" min={1} value={maxUsers} onChange={(e: any) => setMaxUsers(e.target.value)} placeholder="∞" />
          </Field>
          <Field label={`${t("system.maxNodes")} (${t("common.optional")})`}>
            <Input type="number" min={1} value={maxNodes} onChange={(e: any) => setMaxNodes(e.target.value)} placeholder="∞" />
          </Field>
        </div>
        <Field label={`${t("system.maxTotalTraffic")} (${t("common.optional")})`} hint={t("system.maxTotalTrafficHint")}>
          <Input type="number" min={0} step="0.1" value={maxTraffic} onChange={(e: any) => setMaxTraffic(e.target.value)} placeholder="∞" />
        </Field>
        <Field label={`${t("common.password")} (${t("common.optional")})`}>
          <Input type="password" value={password} onChange={(e: any) => setPassword(e.target.value)} placeholder={t("resellers.newPasswordPlaceholder")} />
        </Field>
      </div>
    </Modal>
  );
};

const TenantsTab: FC = () => {
  const { t } = useTranslation();
  const { isEnabled } = useApp();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<Tenant | null>(null);
  const { data, loading, error, status, reload } = useFetch<Tenant[]>(() => api.get("/tenants"), []);

  if (!isEnabled("tenants") || status === 404)
    return <Callout tone="warn" title={t("resellers.tenantsDisabled")}>{t("common.disabledFeature")}</Callout>;
  if (status === 403) return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;

  const remove = async (id: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try { await api.del(`/tenants/${id}`); toast.push(t("common.deleted"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <>
      <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14 }}>
        <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("resellers.addTenant")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !data?.length ? <EmptyState title={t("common.noData")} action={<Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("resellers.addTenant")}</Button>} />
          : (
            <div className="nx-table-wrap">
              <table className="nx-table">
                <thead><tr>
                  <th>{t("common.name")}</th><th>{t("resellers.slug")}</th><th>{t("common.status")}</th>
                  <th>{t("resellers.maxUsers")}</th><th>{t("resellers.maxNodes")}</th><th>{t("resellers.byoDiscount")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {data.map((tn) => (
                    <tr key={tn.id}>
                      <td style={{ fontWeight: 600 }}>{tn.name}</td>
                      <td className="nx-mono">{tn.slug}</td>
                      <td><Pill tone={tn.enabled ? "ok" : "danger"} dot>{tn.enabled ? t("common.enabled") : t("common.disabled")}</Pill></td>
                      <td>{tn.max_users ?? "∞"}</td>
                      <td>{tn.max_nodes ?? "∞"}</td>
                      <td>{tn.byo_node_discount_percent}%</td>
                      <td><div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                        <Button size="sm" variant="ghost" onClick={() => setEdit(tn)}><IcEdit className="nx-ico" /></Button>
                        <Button variant="danger" size="sm" onClick={() => remove(tn.id)}><IcTrash className="nx-ico" /></Button>
                      </div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      {show && <AddTenant onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
      {edit && <EditTenant tenant={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </>
  );
};

const EditTenant: FC<{ tenant: Tenant; onClose: () => void; onDone: () => void }> = ({ tenant, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState({
    name: tenant.name,
    enabled: tenant.enabled,
    maxUsers: tenant.max_users != null ? String(tenant.max_users) : "",
    maxNodes: tenant.max_nodes != null ? String(tenant.max_nodes) : "",
    discount: String(tenant.byo_node_discount_percent ?? 0),
  });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const submit = async () => {
    setBusy(true);
    try {
      await api.patch(`/tenants/${tenant.id}`, {
        name: f.name.trim(),
        enabled: f.enabled,
        max_users: f.maxUsers ? parseInt(f.maxUsers) : null,
        max_nodes: f.maxNodes ? parseInt(f.maxNodes) : null,
        byo_node_discount_percent: parseInt(f.discount) || 0,
      });
      toast.push(t("common.saved"), "success");
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open title={`${t("common.edit")} — ${tenant.name}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy} onClick={submit}>{t("common.save")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} /></Field>
        <label className="nx-row" style={{ gap: 8 }}><input type="checkbox" checked={f.enabled} onChange={upd("enabled")} /> {t("common.enabled")}</label>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("resellers.maxUsers")}><Input type="number" value={f.maxUsers} onChange={upd("maxUsers")} /></Field>
          <Field label={t("resellers.maxNodes")}><Input type="number" value={f.maxNodes} onChange={upd("maxNodes")} /></Field>
          <Field label={t("resellers.byoDiscount")}><Input type="number" value={f.discount} onChange={upd("discount")} /></Field>
        </div>
      </div>
    </Modal>
  );
};

const AddTenant: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState({ name: "", slug: "", owner: "", maxUsers: "", maxNodes: "", discount: "0" });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/tenants", {
        name: f.name.trim(),
        slug: f.slug.trim() || undefined,
        owner_username: f.owner.trim() || undefined,
        max_users: f.maxUsers ? parseInt(f.maxUsers) : undefined,
        max_nodes: f.maxNodes ? parseInt(f.maxNodes) : undefined,
        byo_node_discount_percent: parseInt(f.discount) || 0,
      });
      toast.push(t("common.created"), "success"); onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Modal open title={t("resellers.addTenant")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !f.name} onClick={submit}>{t("common.create")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={`${t("resellers.slug")} (${t("common.optional")})`}><Input value={f.slug} onChange={upd("slug")} /></Field>
          <Field label={`${t("resellers.ownerUsername")} (${t("common.optional")})`}><Input value={f.owner} onChange={upd("owner")} /></Field>
        </div>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("resellers.maxUsers")}><Input type="number" value={f.maxUsers} onChange={upd("maxUsers")} /></Field>
          <Field label={t("resellers.maxNodes")}><Input type="number" value={f.maxNodes} onChange={upd("maxNodes")} /></Field>
          <Field label={t("resellers.byoDiscount")}><Input type="number" value={f.discount} onChange={upd("discount")} /></Field>
        </div>
      </div>
    </Modal>
  );
};

type SubPortBlocked = {
  port: number;
  reason: string;
  inbound_tag?: string | null;
};

type SubPortInfo = {
  blocked: SubPortBlocked[];
  suggested: number[];
};

type SubSslStatus = {
  host?: string | null;
  https_ready?: boolean;
  dns_ok?: boolean;
  cert_present?: boolean;
  message?: string;
  resolved_ips?: string[];
  expected_ips?: string[];
  panel_ip?: string | null;
};

const BrandingTab: FC = () => {
  const { t } = useTranslation();
  const { isEnabled } = useApp();
  const toast = useToast();
  const { data, loading, status, reload } = useFetch<Branding>(() => api.get("/branding/mine"), []);
  const { data: portInfo } = useFetch<SubPortInfo>(
    () => api.get("/branding/subscription-ports"),
    [],
  );
  const {
    data: sslStatus,
    loading: sslLoading,
    reload: reloadSsl,
  } = useFetch<SubSslStatus>(() => api.get("/branding/mine/subscription-ssl"), []);
  const [f, setF] = useState<Branding | null>(null);
  const [busy, setBusy] = useState(false);
  const [sslBusy, setSslBusy] = useState(false);
  const model = f ?? data ?? {};

  const blockedByPort = useMemo(() => {
    const map = new Map<number, SubPortBlocked>();
    for (const row of portInfo?.blocked || []) {
      map.set(Number(row.port), row);
    }
    return map;
  }, [portInfo]);

  const portSuggest = (portInfo?.suggested || [2096]).slice(0, 3);
  const suggestText = portSuggest.length ? portSuggest.join(", ") : "2096";

  const formatPortConflict = (detail: any, fallback?: string) => {
    const port = Number(detail?.port);
    const tag = detail?.inbound_tag || "?";
    const suggest = Array.isArray(detail?.suggested) && detail.suggested.length
      ? detail.suggested.slice(0, 3).join(", ")
      : suggestText;
    const code = String(detail?.code || "");
    if (code === "sub_port_inbound") {
      return t("resellers.subPortBlockedInbound", { port, tag, suggest });
    }
    if (code === "sub_port_wireguard") {
      return t("resellers.subPortBlockedWireguard", { port, suggest });
    }
    if (code === "sub_port_busy") {
      return t("resellers.subPortBlockedBusy", { port, suggest });
    }
    return fallback || detail?.message || t("resellers.subPortBlockedBusy", { port: port || "?", suggest });
  };

  if (!isEnabled("white_label") || status === 404)
    return <Callout tone="warn">{t("common.disabledFeature")}</Callout>;

  const upd = (k: keyof Branding) => (e: any) => setF({ ...model, [k]: e.target.value });

  const save = async () => {
    const checkPort = Number(model.sub_port) > 0 ? Number(model.sub_port) : 443;
    const blocked = checkPort !== 443 && checkPort !== 80 ? blockedByPort.get(checkPort) : undefined;
    if (blocked) {
      toast.push(
        formatPortConflict({
          code: `sub_port_${blocked.reason}`,
          port: blocked.port,
          inbound_tag: blocked.inbound_tag,
          suggested: portSuggest,
        }),
        "error",
      );
      return;
    }
    setBusy(true);
    try {
      await api.put("/branding/mine", model);
      toast.push(t("common.saved"), "success"); setF(null); reload();
      // SSL runs in the background after save — refresh status so the UI
      // never shows a green "ready" while DNS/cert are still broken.
      setTimeout(() => reloadSsl(), 800);
      setTimeout(() => reloadSsl(), 4000);
    } catch (e: any) {
      const detail = e instanceof ApiError ? e.body?.detail : e?.body?.detail;
      if (detail && typeof detail === "object" && String(detail.code || "").startsWith("sub_port_")) {
        toast.push(formatPortConflict(detail, e.message), "error");
      } else {
        toast.push(e.message, "error");
      }
    } finally { setBusy(false); }
  };

  const enableSsl = async () => {
    setSslBusy(true);
    try {
      const res = await api.post<SubSslStatus>("/branding/mine/subscription-ssl", {});
      reloadSsl();
      if (res?.https_ready) {
        toast.push(t("resellers.subSslActive"), "success");
      } else {
        toast.push(res?.message || t("resellers.subSslDnsBad", {
          resolved: (res?.resolved_ips || []).join(", ") || "?",
          ip: res?.panel_ip || "?",
        }), "error");
      }
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setSslBusy(false);
    }
  };

  if (loading) return <Card><SkeletonRows rows={4} cols={2} /></Card>;

  const suggestedLogin = model.panel_url
    || (model.domain ? `https://${model.domain}` : "");
  const subPath = String(model.sub_path || "sub").replace(/^\/+|\/+$/g, "") || "sub";
  const subPort = Number(model.sub_port) > 0 ? Number(model.sub_port) : 443;
  const subPortSuffix = subPort === 443 || subPort === 80 ? "" : `:${subPort}`;
  const subScheme = subPort === 80 ? "http" : "https";
  const suggestedSub = model.domain
    ? `${subScheme}://${model.domain}${subPortSuffix}/${subPath}/<token>/`
    : "";
  const portConflict = subPort !== 443 && subPort !== 80 ? blockedByPort.get(subPort) : undefined;

  const updPort = (e: any) => {
    const raw = String(e.target.value ?? "").trim();
    if (!raw) {
      setF({ ...model, sub_port: null });
      return;
    }
    const n = parseInt(raw, 10);
    setF({ ...model, sub_port: Number.isFinite(n) ? n : null });
  };

  return (
    <Card style={{ maxWidth: 640 }}>
      <CardHead title={t("resellers.tabBranding")} desc={t("resellers.brandingDesc")} />
      <div className="nx-stack">
        <Callout tone="info">
          {sslStatus?.panel_ip
            ? t("resellers.domainDnsHintWithIp", { ip: sslStatus.panel_ip })
            : t("resellers.domainDnsHint")}
        </Callout>
        <Field label={t("resellers.panelTitle")}><Input value={model.panel_title || ""} onChange={upd("panel_title")} /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("resellers.logoUrl")}><Input value={model.logo_url || ""} onChange={upd("logo_url")} /></Field>
          <Field label={t("resellers.faviconUrl")}><Input value={model.favicon_url || ""} onChange={upd("favicon_url")} /></Field>
        </div>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("resellers.primaryColor")}><Input type="text" value={model.primary_color || ""} onChange={upd("primary_color")} placeholder="#2dd4bf" /></Field>
          <Field label={t("resellers.supportUrl")}><Input value={model.support_url || ""} onChange={upd("support_url")} /></Field>
        </div>
        <Field label={t("resellers.subProfileTitle")}><Input value={model.sub_profile_title || ""} onChange={upd("sub_profile_title")} /></Field>
        <Field label={t("resellers.domain")} hint={t("resellers.domainHint")}>
          <Input value={model.domain || ""} onChange={upd("domain")} placeholder="sub.example.com" />
        </Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("resellers.subPath")} hint={t("resellers.subPathHint")}>
            <Input value={model.sub_path || ""} onChange={upd("sub_path")} placeholder="sub" />
          </Field>
          <Field label={t("resellers.subPort")} hint={t("resellers.subPortHint")}>
            <Input
              type="number"
              min={1}
              max={65535}
              value={model.sub_port ?? ""}
              onChange={updPort}
              placeholder="443"
            />
          </Field>
        </div>
        {portConflict && (
          <Callout tone="danger" title={t("resellers.subPortBlockedTitle")}>
            {formatPortConflict({
              code: `sub_port_${portConflict.reason}`,
              port: portConflict.port,
              inbound_tag: portConflict.inbound_tag,
              suggested: portSuggest,
            })}
          </Callout>
        )}
        <Field label={t("resellers.panelUrl")} hint={t("resellers.panelUrlHint")}>
          <Input value={model.panel_url || ""} onChange={upd("panel_url")} placeholder="https://panel.example.com" />
        </Field>
        {suggestedLogin && (
          <Callout tone="info">
            {t("resellers.loginLinkHint")}: <code>{suggestedLogin}</code>
          </Callout>
        )}
        {suggestedSub && !portConflict && (
          <Callout
            tone={sslStatus?.https_ready ? "ok" : sslStatus?.dns_ok ? "warn" : "danger"}
            title={t("resellers.subDomainReadyTitle")}
          >
            <div className="nx-stack" style={{ gap: 8 }}>
              <div>
                {t("resellers.subDomainReadyHint")}: <code>{suggestedSub}</code>
              </div>
              {sslLoading && !sslStatus ? (
                <div>{t("resellers.subSslChecking")}</div>
              ) : sslStatus?.https_ready ? (
                <div>{t("resellers.subSslActive")}</div>
              ) : sslStatus?.dns_ok ? (
                <div>{t("resellers.subSslPending")}</div>
              ) : model.domain ? (
                <div>
                  {t("resellers.subSslDnsBad", {
                    resolved: (sslStatus?.resolved_ips || []).join(", ") || "—",
                    ip: sslStatus?.panel_ip || (sslStatus?.expected_ips || [])[0] || "—",
                  })}
                </div>
              ) : null}
              {model.domain && !sslStatus?.https_ready && (
                <div className="nx-row" style={{ justifyContent: "flex-start" }}>
                  <Button
                    variant="ghost"
                    disabled={busy || sslBusy || !!portConflict}
                    onClick={enableSsl}
                  >
                    {t("resellers.subSslEnable")}
                  </Button>
                </div>
              )}
            </div>
          </Callout>
        )}
        <div className="nx-row" style={{ justifyContent: "flex-end" }}>
          <Button variant="primary" disabled={busy || !!portConflict} onClick={save}>{t("resellers.saveBranding")}</Button>
        </div>
      </div>
    </Card>
  );
};

const AccountTab: FC = () => {
  const { t } = useTranslation();
  const { admin, logout } = useApp();
  const toast = useToast();
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [un, setUn] = useState({ next: "", password: "" });
  const [busyPw, setBusyPw] = useState(false);
  const [busyUn, setBusyUn] = useState(false);

  const changePassword = async () => {
    setBusyPw(true);
    try {
      if (pw.next.length < 6) throw new Error(t("resellers.passwordTooShort"));
      if (pw.next !== pw.confirm) throw new Error(t("resellers.passwordMismatch"));
      await api.put("/admin/me/password", {
        current_password: pw.current,
        new_password: pw.next,
      });
      toast.push(t("resellers.passwordChanged"), "success");
      setPw({ current: "", next: "", confirm: "" });
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusyPw(false);
    }
  };

  const changeUsername = async () => {
    setBusyUn(true);
    try {
      const res = await api.put<{ detail: string; username?: string }>("/admin/me/username", {
        new_username: un.next.trim(),
        current_password: un.password,
      });
      toast.push(res.detail || t("resellers.usernameChanged"), "success");
      logout?.();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusyUn(false);
    }
  };

  return (
    <div className="nx-stack" style={{ maxWidth: 560 }}>
      <Card>
        <CardHead title={t("resellers.changePassword")} desc={t("resellers.changePasswordDesc")} />
        <div className="nx-stack">
          <Field label={t("resellers.currentPassword")}>
            <Input type="password" value={pw.current} onChange={(e: any) => setPw({ ...pw, current: e.target.value })} />
          </Field>
          <Field label={t("resellers.newPassword")}>
            <Input type="password" value={pw.next} onChange={(e: any) => setPw({ ...pw, next: e.target.value })} />
          </Field>
          <Field label={t("resellers.confirmPassword")}>
            <Input type="password" value={pw.confirm} onChange={(e: any) => setPw({ ...pw, confirm: e.target.value })} />
          </Field>
          <div className="nx-row" style={{ justifyContent: "flex-end" }}>
            <Button variant="primary" disabled={busyPw || !pw.current || !pw.next} onClick={changePassword}>
              {t("resellers.changePassword")}
            </Button>
          </div>
        </div>
      </Card>
      <Card>
        <CardHead title={t("resellers.changeUsername")} desc={t("resellers.changeUsernameDesc")} />
        <div className="nx-stack">
          <Callout tone="info">{t("resellers.currentUsernameHint", { username: admin?.username || "" })}</Callout>
          <Field label={t("resellers.newUsername")} hint={t("resellers.usernameRules")}>
            <Input value={un.next} onChange={(e: any) => setUn({ ...un, next: e.target.value })} />
          </Field>
          <Field label={t("resellers.currentPassword")}>
            <Input type="password" value={un.password} onChange={(e: any) => setUn({ ...un, password: e.target.value })} />
          </Field>
          <div className="nx-row" style={{ justifyContent: "flex-end" }}>
            <Button variant="primary" disabled={busyUn || !un.next.trim() || !un.password} onClick={changeUsername}>
              {t("resellers.changeUsername")}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
};

const MigrationTab: FC = () => {
  const { t } = useTranslation();
  const [showImport, setShowImport] = useState(false);
  return (
    <Card style={{ maxWidth: 720 }}>
      <CardHead title={t("resellers.tabMigration")} desc={t("resellers.migrationDesc")} />
      <div className="nx-stack">
        <Callout tone="ok" title={t("resellers.migrationDumpTitle")}>
          {t("resellers.migrationDumpBody")}
        </Callout>
        <Callout tone="info" title={t("resellers.migrationFormatsTitle")}>
          <div>{t("users.importFmt3xuiDump")}</div>
          <div>{t("users.importFmtMarzban")}</div>
          <div>{t("users.importFmt3xui")}</div>
          <div>{t("users.importFmtCsv")}</div>
          <div>{t("users.importFmtLinks")}</div>
        </Callout>
        <p className="nx-faint" style={{ margin: 0 }}>{t("resellers.migrationHint")}</p>
        <div className="nx-row" style={{ justifyContent: "flex-start", gap: 10, flexWrap: "wrap" }}>
          <Button variant="primary" onClick={() => setShowImport(true)}>
            {t("resellers.openDumpImport")}
          </Button>
          <Link to="/users?import=1">
            <Button variant="ghost">{t("resellers.openImport")}</Button>
          </Link>
        </div>
      </div>
      {showImport && (
        <UserImportWizard
          dumpFocus
          onClose={() => setShowImport(false)}
          onDone={() => setShowImport(false)}
        />
      )}
    </Card>
  );
};

const ProvisionTab: FC = () => {
  const { t } = useTranslation();
  const { isEnabled } = useApp();
  const toast = useToast();
  const [f, setF] = useState({ name: "", host: "", username: "root", password: "", role: "direct" });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ status: string; install_command: string; detail?: string } | null>(null);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  if (!isEnabled("node_provisioning")) return <Callout tone="warn">{t("common.disabledFeature")}</Callout>;

  const provision = async () => {
    setBusy(true); setResult(null);
    try {
      const res = await api.post("/nodes/provision", {
        name: f.name.trim(), host: f.host.trim(), username: f.username.trim(),
        password: f.password, role: f.role, run: true,
      });
      setResult(res);
      toast.push(res.status === "provisioned" ? t("resellers.provisionStarted") : (res.detail || t("resellers.manualMode")), res.status === "provisioned" ? "success" : "info");
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  const getCommand = async () => {
    setBusy(true); setResult(null);
    try {
      const res = await api.get(`/nodes/install-command?name=${encodeURIComponent(f.name || "node")}&role=${f.role}`);
      setResult(res);
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Card style={{ maxWidth: 680 }}>
      <CardHead title={t("infra.addNode")} desc={t("resellers.provisionDesc")} />
      <div className="nx-stack">
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} /></Field>
          <Field label={t("resellers.roleLabel")}><select className="nx-select" value={f.role} onChange={upd("role")}>{["direct", "relay", "exit"].map((r) => <option key={r}>{r}</option>)}</select></Field>
        </div>
        <Field label={`${t("infra.address")} (${t("resellers.sshHost")})`}><Input value={f.host} onChange={upd("host")} placeholder="1.2.3.4" /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("resellers.sshUser")}><Input value={f.username} onChange={upd("username")} /></Field>
          <Field label={t("resellers.sshPassword")}><Input type="password" value={f.password} onChange={upd("password")} /></Field>
        </div>
        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 8 }}>
          <Button onClick={getCommand} disabled={busy}><IcServer className="nx-ico" /> {t("resellers.copyCommand")}</Button>
          <Button variant="primary" onClick={provision} disabled={busy || !f.host || !f.name}>{t("common.create")}</Button>
        </div>
        {result && (
          <Callout tone={result.status === "provisioned" ? "ok" : "info"} title={result.status}>
            {result.detail && <div style={{ marginBottom: 8 }}>{result.detail}</div>}
            <Textarea readOnly value={result.install_command} onFocus={(e: any) => e.target.select()} />
          </Callout>
        )}
      </div>
    </Card>
  );
};
