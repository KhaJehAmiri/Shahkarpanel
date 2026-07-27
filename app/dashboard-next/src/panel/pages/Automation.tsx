import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { PluginsStatus, Rule, Workflow } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { PageHeader } from "../components/Shell";
import {
  Button, Callout, Card, EmptyState, Field, Input, Modal, Pill, Select, SkeletonRows, Tabs, Textarea, Toggle, useToast,
} from "../components/ui";
import { IcPlus, IcTrash, IcShield, IcEdit } from "../components/icons";

const EVENTS = [
  "user_created", "user_updated", "user_deleted", "user_limited", "user_expired",
  "user_enabled", "user_disabled", "data_usage_reset", "reached_usage_percent", "reached_days_left",
  "node_created", "node_modified", "node_deleted", "node_connected", "node_error", "node_down",
  "heavy_user_detected", "usage_anomaly", "bandwidth_exhaustion_predicted", "node_at_risk",
];
const ACTIONS = ["log", "publish_event", "restart_node"];

export const Automation: FC<{ embedded?: boolean }> = ({ embedded }) => {
  const { t } = useTranslation();
  const { admin, isEnabled } = useApp();
  const [tab, setTab] = useState("rules");
  if (!admin?.is_sudo) {
    return (
      <div>
        {!embedded && <PageHeader title={t("automation.title")} subtitle={t("automation.subtitle")} description={t("automation.description")} />}
        <Callout tone="warn">{t("common.sudoOnly")}</Callout>
      </div>
    );
  }
  const tabs = [
    ...(isEnabled("rule_engine") ? [{ id: "rules", label: t("automation.tabRules") }] : []),
    ...(isEnabled("workflows") ? [{ id: "workflows", label: t("automation.tabWorkflows") }] : []),
    ...(isEnabled("plugin_marketplace") ? [{ id: "marketplace", label: t("automation.tabMarketplace") }] : []),
    { id: "plugins", label: t("automation.tabPlugins") },
  ];
  const activeTab = tabs.some((x) => x.id === tab) ? tab : (tabs[0]?.id ?? "plugins");
  return (
    <div>
      {!embedded && <PageHeader title={t("automation.title")} subtitle={t("automation.subtitle")} description={t("automation.description")} />}
      {tabs.length === 0 ? (
        <Callout tone="warn">{t("common.disabledFeature")}</Callout>
      ) : (
      <Tabs active={activeTab} onChange={setTab} tabs={tabs} />
      )}
      {activeTab === "rules" && <RulesTab />}
      {activeTab === "workflows" && <WorkflowsTab />}
      {activeTab === "marketplace" && <MarketplaceTab />}
      {activeTab === "plugins" && <PluginsTab />}
    </div>
  );
};

const parseJson = (s: string) => {
  if (!s.trim()) return null;
  return JSON.parse(s);
};

const RulesTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<Rule | null>(null);
  const { data, loading, error, status, reload } = useFetch<Rule[]>(() => api.get("/rules"), []);

  const { isEnabled } = useApp();
  if (!isEnabled("rule_engine") || status === 404) return <Callout tone="warn">{t("common.disabledFeature")}</Callout>;
  if (status === 403) return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;

  const toggle = async (r: Rule) => {
    try { await api.put(`/rules/${r.id}`, { enabled: !r.enabled }); toast.push(t("common.saved"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };
  const remove = async (id: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try { await api.del(`/rules/${id}`); toast.push(t("common.deleted"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <>
      <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14 }}>
        <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("automation.addRule")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} action={<Button onClick={reload}>{t("common.retry")}</Button>} />
          : !data?.length ? <EmptyState title={t("common.noData")} />
          : (
            <div className="nx-table-wrap"><table className="nx-table">
              <thead><tr><th>{t("common.name")}</th><th>{t("automation.trigger")}</th><th>{t("automation.action")}</th><th>{t("common.status")}</th><th className="nx-actions">{t("common.actions")}</th></tr></thead>
              <tbody>
                {data.map((r) => (
                  <tr key={r.id}>
                    <td style={{ fontWeight: 600 }}>{r.name}</td>
                    <td><Pill>{r.trigger_event}</Pill></td>
                    <td><span className="nx-code">{r.action}</span></td>
                    <td><Toggle on={r.enabled} onChange={() => toggle(r)} label={t("automation.toggleRule")} /></td>
                    <td><div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                      <Button variant="ghost" size="sm" title={t("common.edit")} onClick={() => setEdit(r)}><IcEdit className="nx-ico" /></Button>
                      <Button variant="danger" size="sm" title={t("common.delete")} onClick={() => remove(r.id)}><IcTrash className="nx-ico" /></Button>
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
      </Card>
      {show && <RuleFormModal onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
      {edit && <RuleFormModal rule={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </>
  );
};

const RuleFormModal: FC<{ rule?: Rule; onClose: () => void; onDone: () => void }> = ({ rule, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState({
    name: rule?.name || "",
    trigger_event: rule?.trigger_event || EVENTS[0],
    action: rule?.action || ACTIONS[0],
    condition: rule?.condition ? JSON.stringify(rule.condition, null, 2) : "",
    params: rule?.action_params ? JSON.stringify(rule.action_params, null, 2) : "",
    enabled: rule?.enabled ?? true,
  });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const submit = async () => {
    setBusy(true);
    try {
      const body = {
        name: f.name.trim(), trigger_event: f.trigger_event, action: f.action,
        condition: parseJson(f.condition), action_params: parseJson(f.params), enabled: f.enabled,
      };
      if (rule) {
        await api.put(`/rules/${rule.id}`, body);
        toast.push(t("common.saved"), "success");
      } else {
        await api.post("/rules", body);
        toast.push(t("common.created"), "success");
      }
      onDone();
    } catch (e: any) { toast.push(e.message?.includes("JSON") ? t("automation.invalidJson") : e.message, "error"); }
    finally { setBusy(false); }
  };

  return (
    <Modal open title={rule ? t("automation.editRule") : t("automation.addRule")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !f.name} onClick={submit}>{rule ? t("common.save") : t("common.create")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("automation.trigger")}><Select value={f.trigger_event} onChange={upd("trigger_event")}>{EVENTS.map((e) => <option key={e}>{e}</option>)}</Select></Field>
          <Field label={t("automation.action")}><Select value={f.action} onChange={upd("action")}>{ACTIONS.map((a) => <option key={a}>{a}</option>)}</Select></Field>
        </div>
        <Field label={t("automation.condition")}><Textarea value={f.condition} onChange={upd("condition")} placeholder='{"key": "value"}' /></Field>
        <Field label={t("automation.params")}><Textarea value={f.params} onChange={upd("params")} placeholder='{"message": "hi"}' /></Field>
        {rule && (
          <label className="nx-row" style={{ gap: 8 }}>
            <input type="checkbox" checked={f.enabled} onChange={upd("enabled")} /> {t("common.enabled")}
          </label>
        )}
      </div>
    </Modal>
  );
};

const WorkflowsTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { isEnabled } = useApp();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<Workflow | null>(null);
  const { data, loading, error, status, reload } = useFetch<Workflow[]>(() => api.get("/workflows"), []);

  if (!isEnabled("workflows") || status === 404) return <Callout tone="warn">{t("common.disabledFeature")}</Callout>;
  if (status === 403) return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;

  const remove = async (id: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try { await api.del(`/workflows/${id}`); toast.push(t("common.deleted"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <>
      <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14 }}>
        <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("automation.addWorkflow")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} action={<Button onClick={reload}>{t("common.retry")}</Button>} />
          : !data?.length ? <EmptyState title={t("common.noData")} />
          : (
            <div className="nx-table-wrap"><table className="nx-table">
              <thead><tr><th>{t("common.name")}</th><th>{t("automation.trigger")}</th><th>{t("automation.steps")}</th><th>{t("common.status")}</th><th className="nx-actions">{t("common.actions")}</th></tr></thead>
              <tbody>
                {data.map((w) => (
                  <tr key={w.id}>
                    <td style={{ fontWeight: 600 }}>{w.name}</td>
                    <td><Pill>{w.trigger_event}</Pill></td>
                    <td>{t("automation.stepCount", { n: w.steps?.length || 0 })}</td>
                    <td><Pill tone={w.enabled ? "ok" : "danger"} dot>{w.enabled ? t("common.enabled") : t("common.disabled")}</Pill></td>
                    <td><div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                      <Button variant="ghost" size="sm" title={t("common.edit")} onClick={() => setEdit(w)}><IcEdit className="nx-ico" /></Button>
                      <Button variant="danger" size="sm" title={t("common.delete")} onClick={() => remove(w.id)}><IcTrash className="nx-ico" /></Button>
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
      </Card>
      {show && <WorkflowFormModal onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
      {edit && <WorkflowFormModal workflow={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </>
  );
};

const WorkflowFormModal: FC<{ workflow?: Workflow; onClose: () => void; onDone: () => void }> = ({ workflow, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState({
    name: workflow?.name || "",
    trigger_event: workflow?.trigger_event || EVENTS[0],
    steps: workflow?.steps ? JSON.stringify(workflow.steps, null, 2) : '[{"action": "log", "params": {"message": "hi"}}]',
    enabled: workflow?.enabled ?? true,
  });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const submit = async () => {
    setBusy(true);
    try {
      const body = {
        name: f.name.trim(), trigger_event: f.trigger_event,
        steps: JSON.parse(f.steps), enabled: f.enabled,
      };
      if (workflow) {
        await api.put(`/workflows/${workflow.id}`, body);
        toast.push(t("common.saved"), "success");
      } else {
        await api.post("/workflows", body);
        toast.push(t("common.created"), "success");
      }
      onDone();
    } catch (e: any) { toast.push(e.message?.includes("JSON") ? t("automation.invalidJson") : e.message, "error"); }
    finally { setBusy(false); }
  };

  return (
    <Modal open title={workflow ? t("automation.editWorkflow") : t("automation.addWorkflow")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !f.name} onClick={submit}>{workflow ? t("common.save") : t("common.create")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <Field label={t("automation.trigger")}><Select value={f.trigger_event} onChange={upd("trigger_event")}>{EVENTS.map((e) => <option key={e}>{e}</option>)}</Select></Field>
        <Field label={`${t("automation.steps")} (JSON)`}><Textarea rows={6} value={f.steps} onChange={upd("steps")} /></Field>
        {workflow && (
          <label className="nx-row" style={{ gap: 8 }}>
            <input type="checkbox" checked={f.enabled} onChange={upd("enabled")} /> {t("common.enabled")}
          </label>
        )}
      </div>
    </Modal>
  );
};

type MktPlugin = {
  name: string; description?: string; version?: string; installed: boolean;
  enabled: boolean; rating: number; rating_count: number;
};

const MarketplaceTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { data, loading, error, reload } = useFetch<MktPlugin[]>(() => api.get("/marketplace/plugins"), []);

  const install = async (name: string) => {
    if (!confirm(t("automation.installConfirm", { name }))) return;
    try {
      await api.post(`/marketplace/plugins/${encodeURIComponent(name)}/install`);
      toast.push(t("automation.installedDone"), "success");
      reload();
    } catch (e: any) { toast.push(e.message, "error"); }
  };
  const uninstall = async (name: string) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      await api.post(`/marketplace/plugins/${encodeURIComponent(name)}/uninstall`);
      toast.push(t("common.deleted"), "success");
      reload();
    } catch (e: any) { toast.push(e.message, "error"); }
  };

  if (loading) return <Card><SkeletonRows rows={3} cols={2} /></Card>;
  if (error) return <EmptyState title={t("common.error")} desc={error} />;

  return (
    <Card>
      {!data?.length ? <div className="nx-muted">{t("automation.noPlugins")}</div>
        : (
          <div className="nx-stack" style={{ gap: 10 }}>
            {data.map((p) => (
              <div key={p.name} className="nx-card" style={{ background: "var(--nx-surface-2)", padding: 14 }}>
                <div className="nx-row" style={{ justifyContent: "space-between" }}>
                  <div>
                    <div style={{ fontWeight: 600 }}>{p.name}</div>
                    <div className="nx-muted" style={{ fontSize: 13 }}>
                      {t(`marketplace.${p.name}.desc`, { defaultValue: p.description || "—" })}
                    </div>
                    <div className="nx-faint" style={{ fontSize: 11, marginTop: 4 }}>
                      ★ {p.rating.toFixed(1)} ({p.rating_count}) · v{p.version || "?"}
                    </div>
                  </div>
                  <div className="nx-row" style={{ gap: 6 }}>
                    <Pill tone={p.installed ? "ok" : "default"}>{p.installed ? t("automation.installed") : t("automation.notInstalled")}</Pill>
                    {p.installed
                      ? <Button size="sm" variant="danger" onClick={() => uninstall(p.name)}>{t("automation.uninstall")}</Button>
                      : <Button size="sm" variant="primary" onClick={() => install(p.name)}>{t("automation.install")}</Button>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
    </Card>
  );
};

const PluginsTab: FC = () => {
  const { t } = useTranslation();
  const { data, loading, error, status } = useFetch<PluginsStatus>(() => api.get("/plugins"), []);
  if (status === 403) return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;
  if (loading) return <Card><SkeletonRows rows={3} cols={2} /></Card>;
  if (error) return <EmptyState title={t("common.error")} desc={error} />;

  return (
    <Card>
      <div className="nx-row" style={{ marginBottom: 16 }}>
        <IcShield className="nx-ico" style={{ color: "var(--nx-accent)" }} />
        <b>{t("automation.pluginSystem")}</b>
        <Pill tone={data?.enabled ? "ok" : "default"} dot>{data?.enabled ? t("common.enabled") : t("common.disabled")}</Pill>
      </div>
      {!data?.plugins.length ? (
        <div className="nx-muted">{t("automation.noPlugins")}</div>
      ) : (
        <div className="nx-stack">
          {data.plugins.map((p) => (
            <div key={p.name} className="nx-card" style={{ background: "var(--nx-surface-2)", padding: 14 }}>
              <div style={{ fontWeight: 600 }}>{p.name}</div>
              <div className="nx-muted" style={{ fontSize: 13 }}>
                {t(`marketplace.${p.name}.desc`, { defaultValue: p.description })}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
};
