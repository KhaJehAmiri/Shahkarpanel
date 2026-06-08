import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { Branding, SubResellerAccount, Tenant } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { PageHeader } from "../components/Shell";
import {
  Button, Callout, Card, CardHead, EmptyState, Field, Input, Modal, Pill, SkeletonRows, Tabs, Textarea, useToast,
} from "../components/ui";
import { IcPlus, IcTrash, IcServer, IcEdit, IcWallet } from "../components/icons";

type ResellerAccount = {
  username: string;
  is_sudo: boolean;
  role?: string;
  max_users?: number | null;
  max_nodes?: number | null;
};

export const Resellers: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const [tab, setTab] = useState(admin?.is_sudo ? "accounts" : "branding");
  const tabs = [
    ...(admin?.is_sudo ? [
      { id: "accounts", label: t("resellers.tabAccounts") },
      { id: "tenants", label: t("resellers.tabTenants") },
    ] : [
      { id: "subaccounts", label: t("resellers.tabSubAccounts") },
    ]),
    { id: "branding", label: t("resellers.tabBranding") },
    { id: "provision", label: t("infra.addNode") },
  ];
  return (
    <div>
      <PageHeader title={t("resellers.title")} subtitle={t("resellers.subtitle")} description={t("resellers.description")} />
      <Tabs active={tab} onChange={setTab} tabs={tabs} />
      {tab === "accounts" && <ResellerAccountsTab />}
      {tab === "subaccounts" && <SubResellersTab />}
      {tab === "tenants" && <TenantsTab />}
      {tab === "branding" && <BrandingTab />}
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
  const toast = useToast();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<ResellerAccount | null>(null);
  const [credit, setCredit] = useState<ResellerAccount | null>(null);
  const { data, loading, error, reload, status } = useFetch<ResellerAccount[]>(() => api.get("/admins"), []);

  if (status === 403) return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;

  const accounts = (data || []).filter((a) => !a.is_sudo);

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
      </div>
      <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14 }}>
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
                  <th>{t("system.maxUsers")}</th>
                  <th>{t("system.maxNodes")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {accounts.map((a) => (
                    <tr key={a.username}>
                      <td><code>{a.username}</code></td>
                      <td><Pill tone="default">{a.role || "reseller"}</Pill></td>
                      <td>{a.max_users ?? "∞"}</td>
                      <td>{a.max_nodes ?? "∞"}</td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                          <Button size="sm" variant="ghost" title={t("billing.addCredit")} onClick={() => setCredit(a)}><IcWallet className="nx-ico" /></Button>
                          <Button size="sm" variant="ghost" onClick={() => setEdit(a)}><IcEdit className="nx-ico" /></Button>
                          <Button size="sm" variant="danger" onClick={() => remove(a)}><IcTrash className="nx-ico" /></Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      {show && <AddResellerAccount onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
      {edit && <EditResellerAccount account={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
      {credit && <CreditResellerAccount account={credit} onClose={() => setCredit(null)} onDone={() => setCredit(null)} />}
    </>
  );
};

const CreditResellerAccount: FC<{ account: ResellerAccount; onClose: () => void; onDone: () => void }> = ({ account, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/billing/credit", { username: account.username, amount: parseInt(amount, 10) || 0 });
      toast.push(t("common.saved"), "success");
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open title={`${t("billing.addCredit")} — ${account.username}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !amount} onClick={submit}>{t("common.save")}</Button></>}>
      <Field label={t("billing.creditAmount")} hint={t("billing.creditAmountHint")}>
        <Input type="number" min={1} value={amount} onChange={(e: any) => setAmount(e.target.value)} autoFocus />
      </Field>
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
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = { username: username.trim(), password, is_sudo: false, role };
      if (maxUsers.trim()) body.max_users = parseInt(maxUsers, 10);
      if (maxNodes.trim()) body.max_nodes = parseInt(maxNodes, 10);
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
      </div>
    </Modal>
  );
};

const EditResellerAccount: FC<{ account: ResellerAccount; onClose: () => void; onDone: () => void }> = ({ account, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [role, setRole] = useState(account.role || "reseller");
  const [maxUsers, setMaxUsers] = useState(account.max_users != null ? String(account.max_users) : "");
  const [maxNodes, setMaxNodes] = useState(account.max_nodes != null ? String(account.max_nodes) : "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = { is_sudo: false, role };
      if (maxUsers.trim()) body.max_users = parseInt(maxUsers, 10);
      if (maxNodes.trim()) body.max_nodes = parseInt(maxNodes, 10);
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

const BrandingTab: FC = () => {
  const { t } = useTranslation();
  const { isEnabled } = useApp();
  const toast = useToast();
  const { data, loading, status, reload } = useFetch<Branding>(() => api.get("/branding/mine"), []);
  const [f, setF] = useState<Branding | null>(null);
  const [busy, setBusy] = useState(false);
  const model = f ?? data ?? {};

  if (!isEnabled("white_label") || status === 404)
    return <Callout tone="warn">{t("common.disabledFeature")}</Callout>;

  const upd = (k: keyof Branding) => (e: any) => setF({ ...model, [k]: e.target.value });

  const save = async () => {
    setBusy(true);
    try {
      await api.put("/branding/mine", model);
      toast.push(t("common.saved"), "success"); setF(null); reload();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  if (loading) return <Card><SkeletonRows rows={4} cols={2} /></Card>;

  return (
    <Card style={{ maxWidth: 640 }}>
      <CardHead title={t("resellers.tabBranding")} desc={t("resellers.brandingDesc")} />
      <div className="nx-stack">
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
        <Field label={`${t("resellers.domain")} (${t("common.optional")})`}><Input value={model.domain || ""} onChange={upd("domain")} /></Field>
        <div className="nx-row" style={{ justifyContent: "flex-end" }}>
          <Button variant="primary" disabled={busy} onClick={save}>{t("resellers.saveBranding")}</Button>
        </div>
      </div>
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
      toast.push(res.status === "provisioned" ? "OK" : (res.detail || "Manual"), res.status === "provisioned" ? "success" : "info");
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
      <CardHead title={t("infra.addNode")} desc="Provision a node on your own server via SSH, or copy the one-line install command." />
      <div className="nx-stack">
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} /></Field>
          <Field label="Role"><select className="nx-select" value={f.role} onChange={upd("role")}>{["direct", "relay", "exit"].map((r) => <option key={r}>{r}</option>)}</select></Field>
        </div>
        <Field label={`${t("infra.address")} (SSH host)`}><Input value={f.host} onChange={upd("host")} placeholder="1.2.3.4" /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label="SSH user"><Input value={f.username} onChange={upd("username")} /></Field>
          <Field label="SSH password"><Input type="password" value={f.password} onChange={upd("password")} /></Field>
        </div>
        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 8 }}>
          <Button onClick={getCommand} disabled={busy}><IcServer className="nx-ico" /> {t("common.copy")} command</Button>
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
