import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { ApiKey, FeatureFlag, SystemStats } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { PageHeader } from "../components/Shell";
import { LANGUAGES, setLanguage } from "../i18n";
import {
  Button, Callout, Card, CardHead, EmptyState, Field, Input, Modal, Pill, SkeletonRows, Tabs, Toggle, useToast,
} from "../components/ui";
import { IcPlus, IcDownload, IcTrash, IcKey, IcSun, IcMoon } from "../components/icons";

export const System: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const [tab, setTab] = useState(admin?.is_sudo ? "flags" : "apikeys");
  const tabs = [
    ...(admin?.is_sudo ? [
      { id: "flags", label: t("system.tabFlags") },
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
              <div className="nx-muted" style={{ fontSize: 12.5, marginTop: 8 }}>{flag.description}</div>
              <div className="nx-faint" style={{ fontSize: 11, marginTop: 6 }}>{t("system.flagDefault", { v: flag.default ? "on" : "off" })}</div>
            </div>
            <Toggle on={flag.enabled} onChange={() => toggle(flag)} />
          </div>
        </Card>
      ))}
    </div>
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
          <span className="nx-muted">{t("overview.version")}</span>
          <span className="nx-code">{sys.data?.version || "…"}</span>
        </div>
      </Card>
    </div>
  );
};

const AdminsTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("reseller");
  const { data, loading, error, reload, status } = useFetch<{ username: string; is_sudo: boolean; role?: string }[]>(
    () => api.get("/admins"),
    [],
  );

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

  return (
    <>
      <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14 }}>
        <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("system.addAdmin")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={4} cols={3} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : (
            <table className="nx-table">
              <thead><tr><th>{t("common.username")}</th><th>{t("common.status")}</th><th>Role</th></tr></thead>
              <tbody>
                {(data || []).map((a) => (
                  <tr key={a.username}>
                    <td><code>{a.username}</code></td>
                    <td>{a.is_sudo ? "sudo" : "admin"}</td>
                    <td>{a.role || "—"}</td>
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
          <Field label="Role">
            <select className="nx-input" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="reseller">reseller</option>
              <option value="support">support</option>
            </select>
          </Field>
        </div>
      </Modal>
    </>
  );
};
