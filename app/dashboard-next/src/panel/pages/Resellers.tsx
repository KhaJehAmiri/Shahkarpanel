import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { Branding, Tenant } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { PageHeader } from "../components/Shell";
import {
  Button, Callout, Card, CardHead, EmptyState, Field, Input, Modal, Pill, SkeletonRows, Tabs, Textarea, useToast,
} from "../components/ui";
import { IcPlus, IcTrash, IcServer, IcEdit } from "../components/icons";

export const Resellers: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const [tab, setTab] = useState(admin?.is_sudo ? "tenants" : "branding");
  const tabs = [
    ...(admin?.is_sudo ? [{ id: "tenants", label: t("resellers.tabTenants") }] : []),
    { id: "branding", label: t("resellers.tabBranding") },
    { id: "provision", label: t("infra.addNode") },
  ];
  return (
    <div>
      <PageHeader title={t("resellers.title")} subtitle={t("resellers.subtitle")} description={t("resellers.description")} />
      <Tabs active={tab} onChange={setTab} tabs={tabs} />
      {tab === "tenants" && <TenantsTab />}
      {tab === "branding" && <BrandingTab />}
      {tab === "provision" && <ProvisionTab />}
    </div>
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
