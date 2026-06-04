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
import { IcPlus, IcTrash, IcShield } from "../components/icons";

const EVENTS = [
  "user_created", "user_updated", "user_deleted", "user_limited", "user_expired",
  "user_enabled", "user_disabled", "data_usage_reset", "reached_usage_percent", "reached_days_left",
  "node_created", "node_modified", "node_deleted", "node_connected", "node_error", "node_down",
  "heavy_user_detected", "usage_anomaly", "bandwidth_exhaustion_predicted", "node_at_risk",
];
const ACTIONS = ["log", "publish_event", "restart_node"];

export const Automation: FC = () => {
  const { t } = useTranslation();
  const { admin, isEnabled } = useApp();
  const [tab, setTab] = useState("rules");
  if (!admin?.is_sudo) {
    return (
      <div>
        <PageHeader title={t("automation.title")} subtitle={t("automation.subtitle")} description={t("automation.description")} />
        <Callout tone="warn">{t("common.sudoOnly")}</Callout>
      </div>
    );
  }
  const tabs = [
    ...(isEnabled("rule_engine") ? [{ id: "rules", label: t("automation.tabRules") }] : []),
    ...(isEnabled("workflows") ? [{ id: "workflows", label: t("automation.tabWorkflows") }] : []),
    { id: "plugins", label: t("automation.tabPlugins") },
  ];
  const activeTab = tabs.some((x) => x.id === tab) ? tab : (tabs[0]?.id ?? "plugins");
  return (
    <div>
      <PageHeader title={t("automation.title")} subtitle={t("automation.subtitle")} description={t("automation.description")} />
      {tabs.length === 0 ? (
        <Callout tone="warn">{t("common.disabledFeature")}</Callout>
      ) : (
      <Tabs active={activeTab} onChange={setTab} tabs={tabs} />
      )}
      {activeTab === "rules" && <RulesTab />}
      {activeTab === "workflows" && <WorkflowsTab />}
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
  const { data, loading, error, status, reload } = useFetch<Rule[]>(() => api.get("/rules"), []);

  const { isEnabled } = useApp();
  if (!isEnabled("rule_engine") || status === 404) return <Callout tone="warn">{t("common.disabledFeature")}</Callout>;
  if (status === 403) return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;

  const toggle = async (r: Rule) => {
    try { await api.put(`/rules/${r.id}`, { enabled: !r.enabled }); reload(); }
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
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !data?.length ? <EmptyState title={t("common.noData")} />
          : (
            <div className="nx-table-wrap"><table className="nx-table">
              <thead><tr><th>{t("common.name")}</th><th>{t("automation.trigger")}</th><th>{t("automation.action")}</th><th>{t("common.status")}</th><th style={{ textAlign: "end" }}>{t("common.actions")}</th></tr></thead>
              <tbody>
                {data.map((r) => (
                  <tr key={r.id}>
                    <td style={{ fontWeight: 600 }}>{r.name}</td>
                    <td><Pill>{r.trigger_event}</Pill></td>
                    <td><span className="nx-code">{r.action}</span></td>
                    <td><Toggle on={r.enabled} onChange={() => toggle(r)} /></td>
                    <td><div className="nx-row" style={{ justifyContent: "flex-end" }}><Button variant="danger" size="sm" onClick={() => remove(r.id)}><IcTrash className="nx-ico" /></Button></div></td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
      </Card>
      {show && <AddRule onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
    </>
  );
};

const AddRule: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState({ name: "", trigger_event: EVENTS[0], action: ACTIONS[0], condition: "", params: "" });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/rules", {
        name: f.name.trim(), trigger_event: f.trigger_event, action: f.action,
        condition: parseJson(f.condition), action_params: parseJson(f.params), enabled: true,
      });
      toast.push(t("common.created"), "success"); onDone();
    } catch (e: any) { toast.push(e.message?.includes("JSON") ? "Invalid JSON" : e.message, "error"); }
    finally { setBusy(false); }
  };

  return (
    <Modal open title={t("automation.addRule")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !f.name} onClick={submit}>{t("common.create")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("automation.trigger")}><Select value={f.trigger_event} onChange={upd("trigger_event")}>{EVENTS.map((e) => <option key={e}>{e}</option>)}</Select></Field>
          <Field label={t("automation.action")}><Select value={f.action} onChange={upd("action")}>{ACTIONS.map((a) => <option key={a}>{a}</option>)}</Select></Field>
        </div>
        <Field label={t("automation.condition")}><Textarea value={f.condition} onChange={upd("condition")} placeholder='{"key": "value"}' /></Field>
        <Field label={t("automation.params")}><Textarea value={f.params} onChange={upd("params")} placeholder='{"message": "hi"}' /></Field>
      </div>
    </Modal>
  );
};

const WorkflowsTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { isEnabled } = useApp();
  const [show, setShow] = useState(false);
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
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !data?.length ? <EmptyState title={t("common.noData")} />
          : (
            <div className="nx-table-wrap"><table className="nx-table">
              <thead><tr><th>{t("common.name")}</th><th>{t("automation.trigger")}</th><th>{t("automation.steps")}</th><th>{t("common.status")}</th><th style={{ textAlign: "end" }}>{t("common.actions")}</th></tr></thead>
              <tbody>
                {data.map((w) => (
                  <tr key={w.id}>
                    <td style={{ fontWeight: 600 }}>{w.name}</td>
                    <td><Pill>{w.trigger_event}</Pill></td>
                    <td>{t("automation.stepCount", { n: w.steps?.length || 0 })}</td>
                    <td><Pill tone={w.enabled ? "ok" : "danger"} dot>{w.enabled ? t("common.enabled") : t("common.disabled")}</Pill></td>
                    <td><div className="nx-row" style={{ justifyContent: "flex-end" }}><Button variant="danger" size="sm" onClick={() => remove(w.id)}><IcTrash className="nx-ico" /></Button></div></td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
      </Card>
      {show && <AddWorkflow onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
    </>
  );
};

const AddWorkflow: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState({ name: "", trigger_event: EVENTS[0], steps: '[{"action": "log", "params": {"message": "hi"}}]' });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/workflows", {
        name: f.name.trim(), trigger_event: f.trigger_event,
        steps: JSON.parse(f.steps), enabled: true,
      });
      toast.push(t("common.created"), "success"); onDone();
    } catch (e: any) { toast.push(e.message?.includes("JSON") ? "Invalid JSON" : e.message, "error"); }
    finally { setBusy(false); }
  };

  return (
    <Modal open title={t("automation.addWorkflow")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !f.name} onClick={submit}>{t("common.create")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <Field label={t("automation.trigger")}><Select value={f.trigger_event} onChange={upd("trigger_event")}>{EVENTS.map((e) => <option key={e}>{e}</option>)}</Select></Field>
        <Field label={`${t("automation.steps")} (JSON)`}><Textarea rows={6} value={f.steps} onChange={upd("steps")} /></Field>
      </div>
    </Modal>
  );
};

const PluginsTab: FC = () => {
  const { t } = useTranslation();
  const { data, loading, status } = useFetch<PluginsStatus>(() => api.get("/plugins"), []);
  if (status === 403) return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;
  if (loading) return <Card><SkeletonRows rows={3} cols={2} /></Card>;

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
              <div className="nx-muted" style={{ fontSize: 13 }}>{p.description}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
};
