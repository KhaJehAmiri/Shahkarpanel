import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { ApiKey, DeploymentInfo, FeatureFlag, SystemStats, UpdateCheck } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { PageHeader } from "../components/Shell";
import { LANGUAGES, setLanguage } from "../i18n";
import {
  Button, Callout, Card, CardHead, EmptyState, Field, Input, Modal, Pill, Select, SkeletonRows, Tabs, Toggle, useToast,
} from "../components/ui";
import { IcPlus, IcDownload, IcTrash, IcKey, IcSun, IcMoon, IcEdit } from "../components/icons";

export const System: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const [tab, setTab] = useState(admin?.is_sudo ? "flags" : "apikeys");
  const tabs = [
    ...(admin?.is_sudo ? [
      { id: "flags", label: t("system.tabFlags") },
      { id: "updates", label: t("system.tabUpdates") },
      { id: "deployment", label: t("system.tabDeployment") },
      { id: "xray", label: t("system.tabXray") },
      { id: "backup", label: t("system.tabBackup") },
      { id: "admins", label: t("system.tabAdmins") },
    ] : []),
    { id: "apikeys", label: t("system.tabApiKeys") },
    { id: "about", label: t("system.tabAbout") },
  ];
  return (
    <div>
      <PageHeader title={t("system.title")} subtitle={t("system.subtitle")} description={t("system.description")} />
      <Tabs active={tab} onChange={setTab} tabs={tabs} />
      {tab === "flags" && <FlagsTab />}
      {tab === "updates" && <UpdatesTab />}
      {tab === "deployment" && <DeploymentTab />}
      {tab === "xray" && <XrayCoreTab />}
      {tab === "backup" && <BackupTab />}
      {tab === "admins" && <AdminsTab />}
      {tab === "apikeys" && <ApiKeysTab />}
      {tab === "about" && <AboutTab />}
    </div>
  );
};

const FlagsTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { refreshFlags } = useApp();
  const { data, loading, error, status, reload } = useFetch<FeatureFlag[]>(() => api.get("/feature-flags"), []);

  if (status === 403) return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;

  const toggle = async (flag: FeatureFlag) => {
    try {
      await api.put(`/feature-flags/${flag.name}`, { enabled: !flag.enabled });
      toast.push(t("common.saved"), "success");
      reload(); refreshFlags();
    } catch (e: any) { toast.push(e.message, "error"); }
  };

  if (loading) return <Card><SkeletonRows rows={6} cols={2} /></Card>;
  if (error) return <EmptyState title={t("common.error")} desc={error} />;

  return (
    <div className="nx-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
      {data?.map((flag) => (
        <Card key={flag.name}>
          <div className="nx-row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
            <div style={{ flex: 1 }}>
              <div className="nx-row" style={{ gap: 8 }}>
                <span className="nx-code">{flag.name}</span>
                {flag.enabled !== flag.default && <Pill tone="accent">override</Pill>}
              </div>
              <div className="nx-muted" style={{ fontSize: 12.5, marginTop: 8 }}>
                {t(flag.label_key, { defaultValue: flag.description || flag.name })}
              </div>
              <div className="nx-faint" style={{ fontSize: 11, marginTop: 6 }}>{t("system.flagDefault", { v: flag.default ? "on" : "off" })}</div>
            </div>
            <Toggle on={flag.enabled} onChange={() => toggle(flag)} />
          </div>
        </Card>
      ))}
    </div>
  );
};

const DeploymentTab: FC = () => {
  const { t } = useTranslation();
  const { data, loading, error } = useFetch<DeploymentInfo>(() => api.get("/system/deployment"), []);
  if (loading) return <Card><SkeletonRows rows={4} cols={2} /></Card>;
  if (error) return <EmptyState title={t("common.error")} desc={error} />;
  return (
    <Card>
      <div className="nx-stack" style={{ gap: 10 }}>
        <div className="nx-row" style={{ justifyContent: "space-between" }}>
          <span className="nx-muted">{t("system.panelRegion")}</span>
          <Pill tone="accent">{data?.panel_region}</Pill>
        </div>
        <div className="nx-row" style={{ justifyContent: "space-between" }}>
          <span className="nx-muted">{t("system.detectedBy")}</span>
          <span className="nx-code">{data?.detected_by}</span>
        </div>
        <div className="nx-row" style={{ justifyContent: "space-between" }}>
          <span className="nx-muted">IP</span>
          <span className="nx-code">{data?.public_ip || "—"}</span>
        </div>
        <div className="nx-row" style={{ justifyContent: "space-between" }}>
          <span className="nx-muted">{t("system.gitSha")}</span>
          <span className="nx-code">{data?.git_sha || "—"}</span>
        </div>
        <div className="nx-row" style={{ justifyContent: "space-between" }}>
          <span className="nx-muted">{t("system.xrayLocal")}</span>
          <span className="nx-faint" style={{ fontSize: 12 }}>{data?.xray_local_version || "—"}</span>
        </div>
      </div>
    </Card>
  );
};

const XrayCoreTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const deploy = useFetch<DeploymentInfo>(() => api.get("/system/deployment"), []);
  const releases = useFetch<{ tag: string }[]>(() => api.get("/xray/releases"), []);
  const [tag, setTag] = useState("");
  const [scope, setScope] = useState<"panel" | "node">("panel");
  const [nodeId, setNodeId] = useState("");
  const nodes = useFetch<{ id: number; name: string; core_kind?: string }[]>(() => api.get("/nodes"), []);
  const [busy, setBusy] = useState(false);

  const apply = async () => {
    if (!tag) return;
    if (!confirm(t("infra.xrayUpgradeConfirm"))) return;
    setBusy(true);
    try {
      if (scope === "panel") {
        const res = await api.post<{ version: string }>("/system/xray/upgrade", { tag });
        toast.push(res.version, "success");
      } else {
        const id = parseInt(nodeId, 10);
        const res = await api.post<{ version: string }>(`/nodes/${id}/xray/version`, { version: tag });
        toast.push(res.version, "success");
      }
      deploy.reload();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Card>
      <CardHead title={t("system.tabXray")} desc={t("system.xrayTabDesc")} />
      <div className="nx-stack" style={{ gap: 14 }}>
        <div className="nx-row" style={{ justifyContent: "space-between" }}>
          <span className="nx-muted">{t("system.xrayPanelLocal")}</span>
          <span className="nx-code" style={{ fontSize: 12 }}>{deploy.data?.xray_local_version || "—"}</span>
        </div>
        <Field label={t("system.xrayUpgradeScope")}>
          <Select value={scope} onChange={(e: any) => setScope(e.target.value)}>
            <option value="panel">{t("system.xrayScopePanel")}</option>
            <option value="node">{t("system.xrayScopeNode")}</option>
          </Select>
        </Field>
        {scope === "node" && (
          <Field label={t("infra.relayNode")}>
            <Select value={nodeId} onChange={(e: any) => setNodeId(e.target.value)}>
              <option value="">—</option>
              {(nodes.data || []).filter((n) => n.core_kind !== "wireguard").map((n) => (
                <option key={n.id} value={n.id}>{n.name} (#{n.id})</option>
              ))}
            </Select>
          </Field>
        )}
        <Field label={t("infra.xrayPickRelease")}>
          <Select value={tag} onChange={(e: any) => setTag(e.target.value)} disabled={releases.loading}>
            <option value="">—</option>
            {(releases.data || []).map((r) => <option key={r.tag} value={r.tag}>{r.tag}</option>)}
          </Select>
        </Field>
        <div className="nx-row" style={{ justifyContent: "flex-end" }}>
          <Button variant="primary" disabled={busy || !tag || (scope === "node" && !nodeId)} onClick={apply}>
            {t("infra.xraySetVersion")}
          </Button>
        </div>
        <Callout tone="info">{t("system.xrayAlsoInInfra")}</Callout>
      </div>
    </Card>
  );
};

const UpdatesTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [check, setCheck] = useState<UpdateCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);

  const runCheck = async () => {
    setBusy(true);
    try {
      const res = await api.get<UpdateCheck>("/system/updates/check");
      setCheck(res);
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  const runApply = async () => {
    if (!confirm(t("system.updateConfirm"))) return;
    setBusy(true);
    try {
      const res = await api.post<{ job_id: string }>("/system/updates/apply");
      setJobId(res.job_id);
      toast.push(t("system.updateJobRunning"), "info");
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  useEffect(() => {
    if (!jobId) return;
    const id = setInterval(async () => {
      try {
        const j = await api.get<{ status: string; log: string[]; finished: boolean }>(`/system/updates/jobs/${jobId}`);
        setLog(j.log);
        if (j.finished) {
          clearInterval(id);
          toast.push(j.status === "success" ? t("common.saved") : t("common.error"), j.status === "success" ? "success" : "error");
        }
      } catch { /* ignore poll errors */ }
    }, 2000);
    return () => clearInterval(id);
  }, [jobId, toast, t]);

  return (
    <Card>
      <CardHead
        title={t("system.tabUpdates")}
        actions={<>
          <Button variant="ghost" disabled={busy} onClick={runCheck}>{t("system.checkUpdates")}</Button>
          <Button variant="primary" disabled={busy || !check?.commits_behind} onClick={runApply}>{t("system.applyUpdates")}</Button>
        </>}
      />
      {check && (
        <div className="nx-stack" style={{ marginTop: 12, gap: 8 }}>
          <div className="nx-row" style={{ gap: 8 }}>
            <span className="nx-muted">local</span><span className="nx-code">{check.current_sha || "—"}</span>
            <span className="nx-muted">remote</span><span className="nx-code">{check.remote_sha || "—"}</span>
          </div>
          {check.breaking && <Callout tone="warn">{t("system.updatesBreaking")}</Callout>}
          {check.commits_behind > 0
            ? <Callout tone="warn">{t("system.updatesBehind", { n: check.commits_behind })}</Callout>
            : <Callout tone="ok">{t("system.updatesUpToDate")}</Callout>}
          {check.changelog_md && (
            <pre className="nx-code" style={{ fontSize: 11, maxHeight: 200, overflow: "auto", whiteSpace: "pre-wrap" }}>{check.changelog_md}</pre>
          )}
        </div>
      )}
      {log.length > 0 && (
        <pre className="nx-code" style={{ marginTop: 14, fontSize: 11, maxHeight: 240, overflow: "auto" }}>{log.join("\n")}</pre>
      )}
    </Card>
  );
};

const BackupTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const { data, loading, reload } = useFetch<string[]>(() => api.get("/backups"), []);

  const create = async () => {
    setBusy(true);
    try { await api.post("/backup"); toast.push(t("system.backupCreated"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Card>
      <CardHead title={t("system.tabBackup")} actions={<Button variant="primary" disabled={busy} onClick={create}><IcDownload className="nx-ico" /> {t("system.createBackup")}</Button>} />
      <div className="nx-card-desc" style={{ marginBottom: 14 }}>{t("system.backupList")}</div>
      {loading ? <SkeletonRows rows={3} cols={1} />
        : !data?.length ? <div className="nx-muted">{t("common.noData")}</div>
        : <div className="nx-stack" style={{ gap: 8 }}>
            {data.map((b) => (
              <div key={b} className="nx-row" style={{ justifyContent: "space-between", background: "var(--nx-surface-2)", padding: "10px 14px", borderRadius: 8 }}>
                <span className="nx-mono" style={{ fontSize: 12 }}>{b}</span>
                <Button size="sm" variant="danger" onClick={async () => {
                  if (!confirm(t("system.restoreConfirm"))) return;
                  try {
                    await api.post(`/backups/${encodeURIComponent(b)}/restore`);
                    toast.push(t("system.restoreDone"), "success");
                  } catch (e: any) { toast.push(e.message, "error"); }
                }}>{t("system.restore")}</Button>
              </div>
            ))}
          </div>}
    </Card>
  );
};

const ApiKeysTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const { data, loading, error, reload } = useFetch<ApiKey[]>(() => api.get("/api-keys"), []);

  const revoke = async (id: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try { await api.del(`/api-keys/${id}`); toast.push(t("common.deleted"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <>
      <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14 }}>
        <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("system.createKey")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={3} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !data?.length ? <EmptyState title={t("common.noData")} action={<Button variant="primary" onClick={() => setShow(true)}><IcKey className="nx-ico" /> {t("system.createKey")}</Button>} />
          : (
            <div className="nx-table-wrap"><table className="nx-table">
              <thead><tr><th>{t("common.name")}</th><th>{t("system.prefix")}</th><th>{t("system.scopes")}</th><th>{t("common.status")}</th><th style={{ textAlign: "end" }}>{t("common.actions")}</th></tr></thead>
              <tbody>
                {data.map((k) => (
                  <tr key={k.id}>
                    <td style={{ fontWeight: 600 }}>{k.name}</td>
                    <td><span className="nx-code">{k.prefix}…</span></td>
                    <td className="nx-faint" style={{ fontSize: 12 }}>{k.scopes?.join(", ") || "—"}</td>
                    <td><Pill tone={k.revoked ? "danger" : "ok"} dot>{k.revoked ? "revoked" : "active"}</Pill></td>
                    <td><div className="nx-row" style={{ justifyContent: "flex-end" }}>{!k.revoked && <Button variant="danger" size="sm" onClick={() => revoke(k.id)}>{t("system.revoke")}</Button>}</div></td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
      </Card>
      {show && <CreateKey onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
    </>
  );
};

const CreateKey: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState("");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    try {
      const res = await api.post<{ key: string }>("/api-keys", {
        name: name.trim(),
        scopes: scopes.trim() ? scopes.split(",").map((s) => s.trim()) : null,
      });
      setCreated(res.key);
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Modal open title={t("system.createKey")} onClose={created ? onDone : onClose}
      footer={created
        ? <Button variant="primary" onClick={onDone}>{t("common.close")}</Button>
        : <><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" disabled={busy || !name} onClick={submit}>{t("common.create")}</Button></>}>
      {created ? (
        <Callout tone="ok" title={t("system.keyOnceWarning")}>
          <code className="nx-mono" style={{ wordBreak: "break-all", display: "block", marginTop: 8 }}>{created}</code>
        </Callout>
      ) : (
        <div className="nx-stack">
          <Field label={t("system.keyName")}><Input value={name} onChange={(e: any) => setName(e.target.value)} autoFocus /></Field>
          <Field label={`${t("system.scopes")} (${t("common.optional")})`}><Input value={scopes} onChange={(e: any) => setScopes(e.target.value)} placeholder="users:read, nodes:read" /></Field>
        </div>
      )}
    </Modal>
  );
};

const AboutTab: FC = () => {
  const { t, i18n } = useTranslation();
  const { theme, setTheme } = useApp();
  const sys = useFetch<SystemStats>(() => api.get("/system"), []);

  return (
    <div className="nx-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
      <Card>
        <CardHead title={t("system.appearance")} />
        <Field label={t("system.theme")}>
          <div className="nx-row">
            <Button variant={theme === "dark" ? "primary" : "default"} onClick={() => setTheme("dark")}><IcMoon className="nx-ico" /> {t("system.themeDark")}</Button>
            <Button variant={theme === "light" ? "primary" : "default"} onClick={() => setTheme("light")}><IcSun className="nx-ico" /> {t("system.themeLight")}</Button>
          </div>
        </Field>
        <div style={{ height: 14 }} />
        <Field label={t("system.language")}>
          <div className="nx-row" style={{ flexWrap: "wrap" }}>
            {LANGUAGES.map((l) => (
              <Button key={l.code} variant={i18n.language === l.code ? "primary" : "default"} size="sm" onClick={() => setLanguage(l.code)}>{l.flag} {l.label}</Button>
            ))}
          </div>
        </Field>
      </Card>
      <Card>
        <CardHead title={t("system.tabAbout")} />
        <div className="nx-muted" style={{ fontSize: 13, marginBottom: 14 }}>{t("system.aboutText")}</div>
        <div className="nx-row" style={{ justifyContent: "space-between" }}>
          <span className="nx-muted">{t("system.panelVersion")}</span>
          <span className="nx-code">{sys.data?.version || "…"}</span>
        </div>
      </Card>
    </div>
  );
};

type AdminRow = { username: string; is_sudo: boolean; role?: string; max_users?: number | null };

const AdminsTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<AdminRow | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("reseller");
  const { data, loading, error, reload, status } = useFetch<AdminRow[]>(() => api.get("/admins"), []);

  if (status === 403) return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;

  const create = async () => {
    try {
      await api.post("/admin", { username, password, is_sudo: false, role });
      toast.push(t("common.created"), "success");
      setShow(false);
      setUsername("");
      setPassword("");
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  const remove = async (a: AdminRow) => {
    if (a.is_sudo) { toast.push(t("system.cannotDeleteSudo"), "error"); return; }
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
      <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14 }}>
        <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("system.addAdmin")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={4} cols={4} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : (
            <table className="nx-table">
              <thead><tr>
                <th>{t("common.username")}</th><th>{t("common.status")}</th><th>{t("system.role")}</th>
                <th>{t("system.maxUsers")}</th><th style={{ textAlign: "end" }}>{t("common.actions")}</th>
              </tr></thead>
              <tbody>
                {(data || []).map((a) => (
                  <tr key={a.username}>
                    <td><code>{a.username}</code></td>
                    <td>{a.is_sudo ? "sudo" : "admin"}</td>
                    <td>{a.role || "—"}</td>
                    <td>{a.max_users ?? "—"}</td>
                    <td>
                      <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                        {!a.is_sudo && (
                          <>
                            <Button size="sm" variant="ghost" onClick={() => setEdit(a)}><IcEdit className="nx-ico" /></Button>
                            <Button size="sm" variant="danger" onClick={() => remove(a)}><IcTrash className="nx-ico" /></Button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </Card>
      <Modal open={show} title={t("system.addAdmin")} onClose={() => setShow(false)}
        footer={<><Button variant="ghost" onClick={() => setShow(false)}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={!username || !password} onClick={create}>{t("common.create")}</Button></>}>
        <div className="nx-stack">
          <Field label={t("common.username")}><Input value={username} onChange={(e: any) => setUsername(e.target.value)} /></Field>
          <Field label={t("common.password")}><Input type="password" value={password} onChange={(e: any) => setPassword(e.target.value)} /></Field>
          <Field label={t("system.role")}>
            <select className="nx-input" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="reseller">reseller</option>
              <option value="support">support</option>
            </select>
          </Field>
        </div>
      </Modal>
      {edit && (
        <EditAdminModal admin={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />
      )}
    </>
  );
};

const EditAdminModal: FC<{ admin: AdminRow; onClose: () => void; onDone: () => void }> = ({ admin, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [role, setRole] = useState(admin.role || "reseller");
  const [maxUsers, setMaxUsers] = useState(admin.max_users != null ? String(admin.max_users) : "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = { is_sudo: false, role };
      if (maxUsers.trim()) body.max_users = parseInt(maxUsers, 10);
      if (password.trim()) body.password = password;
      await api.put(`/admin/${encodeURIComponent(admin.username)}`, body);
      toast.push(t("common.saved"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open title={`${t("common.edit")} — ${admin.username}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy} onClick={save}>{t("common.save")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("system.role")}>
          <select className="nx-input" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="reseller">reseller</option>
            <option value="support">support</option>
          </select>
        </Field>
        <Field label={t("system.maxUsers")} hint={t("common.optional")}>
          <Input type="number" min="0" value={maxUsers} onChange={(e: any) => setMaxUsers(e.target.value)} />
        </Field>
        <Field label={t("system.newPassword")} hint={t("common.optional")}>
          <Input type="password" value={password} onChange={(e: any) => setPassword(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
};
