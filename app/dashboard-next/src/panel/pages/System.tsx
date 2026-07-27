import { FC, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { ApiKey, AgentUpdateCheck, AgentUpdateJobInfo, DeploymentInfo, FeatureFlag, SystemStats } from "../api/types";
import { useApp } from "../context/AppContext";
import { usePanelUpdate } from "../context/UpdateContext";
import { useFetch, useLiveReload } from "../lib/useFetch";
import { PageHeader } from "../components/Shell";
import { LANGUAGES, setLanguage } from "../i18n";
import {
  Button, Callout, Card, CardHead, EmptyState, Field, Input, Modal, Pill, Select, SkeletonRows, Tabs, Toggle, useToast,
} from "../components/ui";
import { CommercialSettings } from "../components/CommercialSettings";
import { MigrationWizard } from "../components/MigrationWizard";
import { IcPlus, IcDownload, IcTrash, IcKey, IcSun, IcMoon, IcEdit } from "../components/icons";

export const System: FC = () => {
  const { t } = useTranslation();
  const { admin, isEnabled, hasPermission } = useApp();
  const groups = useMemo(() => {
    const general = {
      id: "general",
      label: t("system.groupGeneral"),
      tabs: [
        { id: "about", label: t("system.tabAbout") },
        { id: "apikeys", label: t("system.tabApiKeys") },
      ],
    };
    const maintenanceTabs = [
      ...(admin?.is_sudo
        ? [
            { id: "flags", label: t("system.tabFlags") },
            { id: "updates", label: t("system.tabUpdates") },
            { id: "deployment", label: t("system.tabDeployment") },
            { id: "migration", label: t("system.tabMigration", { defaultValue: "3x-ui migration" }) },
            { id: "xray", label: t("system.tabXray") },
          ]
        : []),
      ...(hasPermission("backup:read") ? [{ id: "backup", label: t("system.tabBackup") }] : []),
    ];
    const accessTabs = admin?.is_sudo
      ? [
          { id: "admins", label: t("system.tabAdmins") },
          { id: "audit", label: t("system.tabAudit", { defaultValue: "Audit log" }) },
          { id: "rbac", label: t("system.tabRbac", { defaultValue: "Access matrix" }) },
          ...(isEnabled("billing") ? [{ id: "commercial", label: t("system.tabCommercial") }] : []),
        ]
      : [];
    const out = [general];
    if (maintenanceTabs.length) {
      out.push({ id: "maintenance", label: t("system.groupMaintenance"), tabs: maintenanceTabs });
    }
    if (accessTabs.length) {
      out.push({ id: "access", label: t("system.groupAccess"), tabs: accessTabs });
    }
    return out;
  }, [admin?.is_sudo, hasPermission, isEnabled, t]);

  const [searchParams] = useSearchParams();
  const [group, setGroup] = useState(groups[0]?.id || "general");
  const activeGroup = groups.find((g) => g.id === group) || groups[0];
  const tabFromUrl = searchParams.get("tab");
  const [tab, setTab] = useState(
    tabFromUrl && groups.some((g) => g.tabs.some((x) => x.id === tabFromUrl))
      ? tabFromUrl
      : (activeGroup?.tabs[0]?.id || "about"),
  );

  useEffect(() => {
    if (!tabFromUrl) return;
    const g = groups.find((gr) => gr.tabs.some((x) => x.id === tabFromUrl));
    if (g) {
      setGroup(g.id);
      setTab(tabFromUrl);
    }
  }, [tabFromUrl, groups]);

  useEffect(() => {
    if (!groups.some((g) => g.id === group)) setGroup(groups[0]?.id || "general");
  }, [groups, group]);

  useEffect(() => {
    const g = groups.find((x) => x.id === group) || groups[0];
    if (g && !g.tabs.some((x) => x.id === tab)) setTab(g.tabs[0]?.id || "about");
  }, [group, groups, tab]);

  const onGroup = (id: string) => {
    setGroup(id);
    const g = groups.find((x) => x.id === id);
    if (g) setTab(g.tabs[0]?.id || "about");
  };

  return (
    <div className="nx-page">
      <PageHeader title={t("system.title")} subtitle={t("system.subtitle")} description={t("system.description")} />
      {groups.length > 1 && (
        <div className="nx-system-groups">
          {groups.map((g) => (
            <button
              key={g.id}
              type="button"
              className={`nx-system-group-btn ${group === g.id ? "active" : ""}`}
              onClick={() => onGroup(g.id)}
            >
              {g.label}
            </button>
          ))}
        </div>
      )}
      <Tabs active={tab} onChange={setTab} tabs={activeGroup?.tabs || []} />
      {tab === "flags" && <FlagsTab />}
      {tab === "commercial" && <CommercialSettings />}
      {tab === "updates" && (
        <div className="nx-stack" style={{ gap: 16 }}>
          <UpdatesTab />
          <AgentAgentsTab />
        </div>
      )}
      {tab === "deployment" && <DeploymentTab />}
      {tab === "migration" && admin?.is_sudo && <MigrationWizard />}
      {tab === "xray" && <XrayCoreTab />}
      {tab === "backup" && <BackupTab />}
      {tab === "admins" && <AdminsTab />}
      {tab === "audit" && <AuditTab />}
      {tab === "rbac" && <RbacTab />}
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
                {flag.enabled !== flag.default && <Pill tone="accent">{t("system.flagOverride")}</Pill>}
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
          <span className="nx-muted">{t("system.deployIp")}</span>
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
  const autoSchedule = useFetch<{ enabled: boolean; interval_seconds: number; include_prerelease: boolean }>(
    () => api.get("/system/xray/auto-upgrade/schedule"),
    [],
  );
  const [tag, setTag] = useState("");
  const [scope, setScope] = useState<"panel" | "node">("panel");
  const [nodeId, setNodeId] = useState("");
  const [autoEnabled, setAutoEnabled] = useState(true);
  const [autoIntervalHours, setAutoIntervalHours] = useState("6");
  const [autoPrerelease, setAutoPrerelease] = useState(true);
  const nodes = useFetch<{ id: number; name: string; core_kind?: string; xray_version?: string | null }[]>(() => api.get("/nodes"), []);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!autoSchedule.data) return;
    setAutoEnabled(!!autoSchedule.data.enabled);
    setAutoIntervalHours(String(Math.round((autoSchedule.data.interval_seconds || 21600) / 3600)));
    setAutoPrerelease(autoSchedule.data.include_prerelease !== false);
  }, [autoSchedule.data]);

  const saveAutoSchedule = async () => {
    setBusy(true);
    try {
      const hours = parseFloat(autoIntervalHours) || 6;
      await api.put("/system/xray/auto-upgrade/schedule", {
        enabled: autoEnabled,
        interval_seconds: Math.max(3600, Math.round(hours * 3600)),
        include_prerelease: autoPrerelease,
      });
      toast.push(t("common.saved"), "success");
      autoSchedule.reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const triggerAutoUpgrade = async () => {
    if (!confirm(t("system.xrayAutoUpgradeConfirm", { defaultValue: "Run fleet Xray auto-upgrade now?" }))) return;
    setBusy(true);
    try {
      const res = await api.post<Record<string, unknown>>("/system/xray/auto-upgrade");
      toast.push(JSON.stringify(res).slice(0, 120), "success");
      deploy.reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

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
              {(nodes.data || []).map((n) => (
                <option key={n.id} value={n.id}>{n.name} (#{n.id}){n.core_kind === "wireguard" ? " · WG" : ""} · {n.xray_version || "—"}</option>
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
        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 8 }}>
          <Button
            variant="ghost"
            disabled={busy}
            onClick={async () => {
              if (!confirm(t("system.restartCoreConfirm"))) return;
              setBusy(true);
              try {
                await api.post("/core/restart");
                toast.push(t("system.restartCoreDone"), "success");
                deploy.reload();
              } catch (e: any) {
                toast.push(e.message, "error");
              } finally {
                setBusy(false);
              }
            }}
          >
            {t("system.restartCore")}
          </Button>
          <Button variant="primary" disabled={busy || !tag || (scope === "node" && !nodeId)} onClick={apply}>
            {t("infra.xraySetVersion")}
          </Button>
        </div>
        <Callout tone="info">{t("system.xrayAlsoInInfra")}</Callout>

        <Card style={{ marginTop: 8 }}>
          <CardHead title={t("system.xrayAutoUpgrade", { defaultValue: "Fleet auto-upgrade" })} />
          <div className="nx-stack" style={{ gap: 12 }}>
            <label className="nx-row" style={{ gap: 8 }}>
              <input type="checkbox" checked={autoEnabled} onChange={(e) => setAutoEnabled(e.target.checked)} />
              {t("system.xrayAutoUpgradeEnabled", { defaultValue: "Enable scheduled auto-upgrade" })}
            </label>
            <Field label={t("system.xrayAutoUpgradeInterval", { defaultValue: "Check interval (hours)" })}>
              <Input type="number" min="1" max="168" value={autoIntervalHours} onChange={(e: any) => setAutoIntervalHours(e.target.value)} style={{ maxWidth: 120 }} />
            </Field>
            <label className="nx-row" style={{ gap: 8, fontSize: 13 }}>
              <input type="checkbox" checked={autoPrerelease} onChange={(e) => setAutoPrerelease(e.target.checked)} />
              {t("system.xrayAutoUpgradePrerelease", { defaultValue: "Include pre-releases" })}
            </label>
            <div className="nx-row" style={{ gap: 8, justifyContent: "flex-end" }}>
              <Button disabled={busy} onClick={saveAutoSchedule}>{t("common.save")}</Button>
              <Button variant="primary" disabled={busy} onClick={triggerAutoUpgrade}>
                {t("system.xrayAutoUpgradeRun", { defaultValue: "Run now" })}
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </Card>
  );
};


const UpdatesTab: FC = () => {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const { check, hasUpdate, checking, refreshCheck, openUpdateModal } = usePanelUpdate();
  const [busy, setBusy] = useState(false);

  const runCheck = async () => {
    setBusy(true);
    try { await refreshCheck(); }
    catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  const notes = check ? (check.release_notes_i18n?.[i18n.language] || check.release_notes_i18n?.en || []) : [];
  const noteLines = notes.length ? notes : (check?.release_notes || check?.changelog_md || "").split("\n").filter(Boolean);

  return (
    <Card>
      <CardHead
        title={t("system.tabUpdates")}
        actions={<>
          <Button variant="ghost" disabled={busy || checking} onClick={runCheck}>{t("system.checkUpdates")}</Button>
          <Button variant="primary" disabled={busy || checking || !hasUpdate} onClick={openUpdateModal}>{t("system.applyUpdates")}</Button>
        </>}
      />
      {check && (
        <div className="nx-stack" style={{ marginTop: 12, gap: 10 }}>
          <div className="nx-row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
            <div>
              <div className="nx-muted" style={{ fontSize: 12 }}>{t("system.updateCurrent")}</div>
              <div className="nx-code" style={{ fontSize: 18, fontWeight: 600 }}>v{check.current_version}</div>
            </div>
            {hasUpdate ? (
              <div style={{ textAlign: "end" }}>
                <div className="nx-muted" style={{ fontSize: 12 }}>{t("system.updateAvailable")}</div>
                <div className="nx-code" style={{ fontSize: 18, fontWeight: 600, color: "var(--nx-accent)" }}>v{check.remote_version}</div>
              </div>
            ) : null}
          </div>
          {check.breaking && <Callout tone="warn">{t("system.updatesBreaking")}</Callout>}
          {hasUpdate ? (
            <Callout tone="info">{t("system.updatesBehind", { from: check.current_version, to: check.remote_version })}</Callout>
          ) : (
            <Callout tone="ok">{t("system.updatesUpToDate", { version: check.current_version })}</Callout>
          )}
          {hasUpdate && noteLines.length > 0 && (
            <div>
              <div className="nx-muted" style={{ fontSize: 12, marginBottom: 6 }}>{t("system.updateReleaseNotes")}</div>
              <ul style={{ margin: 0, paddingInlineStart: 18, fontSize: 13, lineHeight: 1.5 }}>
                {noteLines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
};

const AgentAgentsTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [check, setCheck] = useState<AgentUpdateCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<AgentUpdateJobInfo | null>(null);
  const [jobOpen, setJobOpen] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => () => stopPoll(), []);

  const runCheck = async () => {
    setBusy(true);
    try {
      const res = await api.get<AgentUpdateCheck>("/system/agent-updates/check?force=true");
      setCheck(res);
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    runCheck();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pollJob = (jobId: string) => {
    stopPoll();
    pollRef.current = setInterval(async () => {
      try {
        const j = await api.get<AgentUpdateJobInfo>(`/system/agent-updates/jobs/${jobId}`);
        setJob(j);
        if (j.finished) {
          stopPoll();
          setBusy(false);
          if (j.status === "success") toast.push(t("system.agentUpdateDone"), "success");
          else if (j.status === "partial") toast.push(j.message || t("system.agentUpdatePartial"), "info");
          else toast.push(j.error_message || t("system.agentUpdateFailed"), "error");
          runCheck();
        }
      } catch {
        /* keep polling */
      }
    }, 1500);
  };

  const applyAll = async () => {
    if (!check?.nodes_eligible) return;
    if (!confirm(t("system.agentUpdateConfirm", { count: check.nodes_eligible }))) return;
    setBusy(true);
    setJobOpen(true);
    setJob(null);
    try {
      const res = await api.post<{ job_id: string }>("/system/agent-updates/apply");
      pollJob(res.job_id);
      const j = await api.get<AgentUpdateJobInfo>(`/system/agent-updates/jobs/${res.job_id}`);
      setJob(j);
    } catch (e: any) {
      setBusy(false);
      toast.push(e.message, "error");
    }
  };

  const running = busy && jobOpen && job && !job.finished;

  return (
    <>
      <Card>
        <CardHead
          title={t("system.agentUpdatesTitle")}
          actions={<>
            <Button variant="ghost" disabled={busy} onClick={runCheck}>{t("system.agentUpdatesCheck")}</Button>
            <Button
              variant="primary"
              disabled={busy || !check?.nodes_eligible || !check?.ssh_available}
              onClick={applyAll}
            >
              {t("system.agentUpdatesApply")}
            </Button>
          </>}
        />
        <div className="nx-stack" style={{ marginTop: 12, gap: 10 }}>
          <p className="nx-muted" style={{ fontSize: 13, margin: 0 }}>{t("system.agentUpdatesHint")}</p>
          {check && (
            <>
              <div className="nx-row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
                <div>
                  <div className="nx-muted" style={{ fontSize: 12 }}>{t("system.agentEligible")}</div>
                  <div className="nx-code" style={{ fontSize: 18, fontWeight: 600 }}>
                    {check.nodes_eligible} / {check.nodes_total}
                  </div>
                </div>
                <div style={{ textAlign: "end" }}>
                  <div className="nx-muted" style={{ fontSize: 12 }}>{t("system.agentPackage")}</div>
                  <Pill tone={check.package_reachable || check.mirror_reachable ? "ok" : "danger"} dot>
                    {check.package_reachable || check.mirror_reachable
                      ? t("system.agentPackageOk")
                      : t("system.agentPackageDown")}
                  </Pill>
                </div>
              </div>
              {!check.ssh_available && (
                <Callout tone="warn">{t("system.agentSshUnavailable")}</Callout>
              )}
              {check.nodes_skipped > 0 && (
                <Callout tone="info">{t("system.agentSkipped", { count: check.nodes_skipped })}</Callout>
              )}
              {check.package_error && !check.package_reachable && !check.mirror_reachable && (
                <Callout tone="warn">{check.package_error}</Callout>
              )}
            </>
          )}
        </div>
      </Card>

      <Modal
        open={jobOpen}
        title={t("system.agentUpdatesTitle")}
        onClose={running ? () => {} : () => { setJobOpen(false); stopPoll(); }}
        footer={running ? undefined : (
          <Button variant="ghost" onClick={() => { setJobOpen(false); stopPoll(); }}>{t("common.close")}</Button>
        )}
      >
        {!job ? (
          <p className="nx-muted">{t("common.loading")}</p>
        ) : (
          <div className="nx-stack" style={{ gap: 8 }}>
            {job.message && <p className="nx-muted" style={{ margin: 0 }}>{job.message}</p>}
            {job.nodes.map((n) => {
              const tone = n.status === "success" ? "ok"
                : n.status === "failed" ? "danger"
                  : n.status === "running" ? "accent"
                    : n.status === "skipped" ? "default" : "default";
              return (
                <div key={n.node_id} className="nx-row" style={{ gap: 8, fontSize: 13, alignItems: "flex-start" }}>
                  <Pill tone={tone} dot>{n.node_name}</Pill>
                  <span className="nx-muted" style={{ flex: 1 }}>{n.message || n.error || n.status}</span>
                </div>
              );
            })}
            {job.error_message && job.status === "failed" && (
              <Callout tone="danger">{job.error_message}</Callout>
            )}
          </div>
        )}
      </Modal>
    </>
  );
};

const BackupTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { hasPermission } = useApp();
  const canWrite = hasPermission("backup:write");
  const [busy, setBusy] = useState(false);
  const [scheduleHours, setScheduleHours] = useState("");
  const uploadRef = useRef<HTMLInputElement>(null);
  const { data, loading, reload } = useFetch<string[]>(() => api.get("/backups"), []);
  const schedule = useFetch<{ enabled: boolean; interval_hours: number }>(() => api.get("/backups/schedule"), []);

  useEffect(() => {
    if (schedule.data) setScheduleHours(String(schedule.data.interval_hours || 0));
  }, [schedule.data]);

  const downloadNow = async () => {
    setBusy(true);
    try {
      await api.download("/backup/download", "nexuspanel-backup.dump");
      toast.push(t("system.backupDownloaded"), "success");
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const downloadStored = async (name: string) => {
    try {
      await api.download(`/backups/${encodeURIComponent(name)}/download`, name);
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  const onRestoreFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!confirm(t("system.uploadRestoreConfirm"))) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      await api.upload<{ filename: string; restarting?: boolean }>("/backup/restore", form);
      toast.push(t("system.restoreDoneRestarting"), "success");
      // Panel restarts shortly — give the toast a moment, then reload list if still up.
      setTimeout(() => { try { reload(); } catch { /* panel may be restarting */ } }, 2500);
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const saveSchedule = async () => {
    setBusy(true);
    try {
      const hours = parseInt(scheduleHours, 10);
      await api.put("/backups/schedule", { interval_hours: Number.isFinite(hours) ? hours : 0 });
      toast.push(t("common.saved"), "success");
      schedule.reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHead title={t("system.tabBackup")} />
      <p className="nx-card-desc" style={{ marginBottom: 16 }}>
        {t("system.backupIntro")}
      </p>
      <div className="nx-row" style={{ gap: 10, flexWrap: "wrap", marginBottom: 18 }}>
        <Button variant="primary" disabled={busy} onClick={downloadNow}>
          <IcDownload className="nx-ico" /> {t("system.downloadBackup")}
        </Button>
        {canWrite && (
          <>
            <input
              ref={uploadRef}
              type="file"
              accept=".dump,.db,.sql,.tar.gz,.tgz,application/gzip,application/octet-stream"
              style={{ display: "none" }}
              onChange={onRestoreFile}
            />
            <Button variant="danger" disabled={busy} onClick={() => uploadRef.current?.click()}>
              {t("system.restoreBackup")}
            </Button>
          </>
        )}
      </div>
      {schedule.data && (
        <div className="nx-stack" style={{ gap: 10, marginBottom: 18 }}>
          <Callout tone={schedule.data.enabled ? "ok" : "info"}>
            {schedule.data.enabled
              ? t("system.backupScheduleOn", {
                  defaultValue: "Automatic backups every {{hours}}h",
                  hours: schedule.data.interval_hours,
                })
              : t("system.backupScheduleOff", { defaultValue: "Scheduled backups disabled" })}
          </Callout>
          {canWrite && (
            <Field label={t("system.backupIntervalHours", { defaultValue: "Backup interval (hours, 0=off)" })}>
              <div className="nx-row" style={{ gap: 8 }}>
                <Input type="number" min="0" max="168" value={scheduleHours} onChange={(e: any) => setScheduleHours(e.target.value)} style={{ maxWidth: 120 }} />
                <Button disabled={busy} onClick={saveSchedule}>{t("common.save")}</Button>
              </div>
            </Field>
          )}
        </div>
      )}
      <div className="nx-card-desc" style={{ marginBottom: 14 }}>{t("system.backupList")}</div>
      {loading ? <SkeletonRows rows={3} cols={1} />
        : !data?.length ? <div className="nx-muted">{t("common.noData")}</div>
        : <div className="nx-stack" style={{ gap: 8 }}>
            {data.map((b) => (
              <div key={b} className="nx-row" style={{ justifyContent: "space-between", background: "var(--nx-surface-2)", padding: "10px 14px", borderRadius: 8 }}>
                <span className="nx-mono" style={{ fontSize: 12 }}>{b}</span>
                <div className="nx-row" style={{ gap: 6 }}>
                  <Button size="sm" variant="ghost" onClick={() => downloadStored(b)}>
                    <IcDownload className="nx-ico" /> {t("system.download")}
                  </Button>
                  {canWrite && (
                    <Button size="sm" variant="danger" disabled={busy} onClick={async () => {
                      if (!confirm(t("system.restoreConfirm"))) return;
                      setBusy(true);
                      try {
                        await api.post(`/backups/${encodeURIComponent(b)}/restore`);
                        toast.push(t("system.restoreDoneRestarting"), "success");
                      } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
                    }}>{t("system.restore")}</Button>
                  )}
                </div>
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
  useLiveReload(reload, 30000);

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
                    <td><Pill tone={k.revoked ? "danger" : "ok"} dot>{k.revoked ? t("system.keyRevoked") : t("system.keyActive")}</Pill></td>
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
          <Field label={`${t("system.scopes")} (${t("common.optional")})`}><Input value={scopes} onChange={(e: any) => setScopes(e.target.value)} placeholder="users:read, users:write, branding:read, branding:write, reseller:read" /></Field>
        </div>
      )}
    </Modal>
  );
};

const AboutTab: FC = () => {
  const { t, i18n } = useTranslation();
  const { admin, theme, setTheme, expertMode, setExpertMode } = useApp();
  const toast = useToast();
  const sys = useFetch<SystemStats>(() => api.get("/system"), []);
  const [rotating, setRotating] = useState(false);

  const rotateJwt = async () => {
    if (!confirm(t("system.jwtRotateConfirm"))) return;
    setRotating(true);
    try {
      await api.post("/system/jwt/rotate");
      toast.push(t("system.jwtRotated"), "success");
    } catch (e: any) { toast.push(e.message, "error"); } finally { setRotating(false); }
  };

  return (
    <div className="nx-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
      <Card className="nx-glass-card">
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
        <div style={{ height: 14 }} />
        <Field label={t("system.expertMode")} hint={t("system.expertModeHint")}>
          <Toggle on={expertMode} onChange={setExpertMode} />
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
      {admin?.is_sudo && (
        <Card>
          <CardHead title={t("system.securityTitle")} desc={t("system.jwtRotateHint")} />
          <Button variant="danger" size="sm" disabled={rotating} onClick={rotateJwt}>{t("system.jwtRotateBtn")}</Button>
        </Card>
      )}
    </div>
  );
};

type AdminRow = { username: string; is_sudo: boolean; role?: string; max_users?: number | null; users_count?: number | null };

const AdminsTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<AdminRow | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("reseller");
  const [maxUsers, setMaxUsers] = useState("");
  const { data, loading, error, reload, status } = useFetch<AdminRow[]>(() => api.get("/admins"), []);

  if (status === 403) return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;

  const create = async () => {
    try {
      const body: Record<string, unknown> = { username, password, is_sudo: false, role };
      if (maxUsers.trim()) body.max_users = parseInt(maxUsers, 10);
      await api.post("/admin", body);
      toast.push(t("common.created"), "success");
      setShow(false);
      setUsername("");
      setPassword("");
      setMaxUsers("");
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
            <div className="nx-table-wrap">
            <table className="nx-table">
              <thead><tr>
                <th>{t("common.username")}</th><th>{t("common.status")}</th><th>{t("system.role")}</th>
                <th>{t("resellers.usersCount")}</th><th style={{ textAlign: "end" }}>{t("common.actions")}</th>
              </tr></thead>
              <tbody>
                {(data || []).map((a) => (
                  <tr key={a.username}>
                    <td><code>{a.username}</code></td>
                    <td>{a.is_sudo ? t("system.roleSudo") : t("system.roleAdmin")}</td>
                    <td>{a.role || "—"}</td>
                    <td>
                      {(a.users_count ?? 0).toLocaleString()}
                      <span className="nx-faint">
                        {" / "}
                        {a.max_users != null ? a.max_users.toLocaleString() : "∞"}
                      </span>
                    </td>
                    <td>
                      <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                        {!a.is_sudo && (
                          <>
                            <Button size="sm" variant="ghost" title={t("common.edit")} onClick={() => setEdit(a)}><IcEdit className="nx-ico" /></Button>
                            <Button size="sm" variant="danger" title={t("common.delete")} onClick={() => remove(a)}><IcTrash className="nx-ico" /></Button>
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
      <Modal open={show} title={t("system.addAdmin")} onClose={() => setShow(false)}
        footer={<><Button variant="ghost" onClick={() => setShow(false)}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={!username || !password} onClick={create}>{t("common.create")}</Button></>}>
        <div className="nx-stack">
          <Field label={t("common.username")}><Input value={username} onChange={(e: any) => setUsername(e.target.value)} /></Field>
          <Field label={t("common.password")}><Input type="password" value={password} onChange={(e: any) => setPassword(e.target.value)} /></Field>
          <Field label={t("system.role")}>
            <select className="nx-input" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="reseller">{t("resellers.roleReseller")}</option>
              <option value="support">{t("resellers.roleSupport")}</option>
            </select>
          </Field>
          <Field label={`${t("system.maxUsers")} (${t("common.optional")})`}>
            <Input type="number" min={1} value={maxUsers} onChange={(e: any) => setMaxUsers(e.target.value)} placeholder="∞" />
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
            <option value="reseller">{t("resellers.roleReseller")}</option>
            <option value="support">{t("resellers.roleSupport")}</option>
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

type AuditEvent = { id: number; type: string; payload?: Record<string, unknown> | null; created_at: string };

const AuditTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { data, loading, error, reload } = useFetch<AuditEvent[]>(() => api.get("/events?limit=200"), []);
  const sessions = useFetch<{ sessions: { username: string; ip: string; is_sudo: boolean; logged_at: string }[] }>(
    () => api.get("/admin/sessions"),
    [],
  );
  useLiveReload(reload, 60000);

  const revokeSessions = async (username: string) => {
    if (!confirm(t("system.revokeSessionsConfirm", { defaultValue: "Revoke all sessions for {{user}}?", user: username }))) return;
    try {
      await api.post("/admin/sessions/revoke", { username });
      toast.push(t("system.revokeSessionsDone", { defaultValue: "Sessions revoked" }), "success");
      sessions.reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  return (
    <div className="nx-stack" style={{ gap: 16 }}>
      <Card pad0>
        <CardHead title={t("system.adminSessions", { defaultValue: "Admin login sessions" })} />
        {sessions.loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
          : !sessions.data?.sessions?.length ? <EmptyState title={t("common.noData")} />
          : (
            <div className="nx-table-wrap">
              <table className="nx-table">
                <thead><tr><th>{t("common.username")}</th><th>IP</th><th>{t("common.time")}</th><th style={{ textAlign: "end" }}>{t("common.actions")}</th></tr></thead>
                <tbody>
                  {sessions.data.sessions.map((s, idx) => (
                    <tr key={`${s.username}-${s.logged_at}-${idx}`}>
                      <td>{s.username}{s.is_sudo ? " · sudo" : ""}</td>
                      <td className="nx-mono" style={{ fontSize: 12 }}>{s.ip || "—"}</td>
                      <td className="nx-faint" style={{ fontSize: 12 }}>{new Date(s.logged_at).toLocaleString()}</td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end" }}>
                          <Button size="sm" variant="danger" onClick={() => revokeSessions(s.username)}>
                            {t("system.revokeSessions", { defaultValue: "Revoke all" })}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>

      <Card pad0>
        <CardHead title={t("system.tabAudit", { defaultValue: "Audit log" })} />
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={6} cols={3} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !data?.length ? <EmptyState title={t("common.noData")} />
          : (
            <div className="nx-table-wrap">
              <table className="nx-table">
                <thead><tr><th>ID</th><th>{t("common.type", { defaultValue: "Type" })}</th><th>{t("common.time", { defaultValue: "Time" })}</th><th>{t("common.details", { defaultValue: "Details" })}</th></tr></thead>
                <tbody>
                  {data.map((ev) => (
                    <tr key={ev.id}>
                      <td className="nx-mono">{ev.id}</td>
                      <td><Pill>{ev.type}</Pill></td>
                      <td className="nx-faint" style={{ fontSize: 12 }}>{new Date(ev.created_at).toLocaleString()}</td>
                      <td className="nx-mono" style={{ fontSize: 11, maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis" }}>
                        {ev.payload ? JSON.stringify(ev.payload) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
    </div>
  );
};

type RbacMatrix = { permissions: string[]; roles: Record<string, string[]> };

const RbacTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { data, loading, error, reload } = useFetch<RbacMatrix>(() => api.get("/admin/rbac/matrix"), []);
  const [busyRole, setBusyRole] = useState<string | null>(null);

  const togglePerm = async (role: string, perm: string, checked: boolean) => {
    if (!data) return;
    const current = new Set(data.roles[role] || []);
    if (checked) current.add(perm); else current.delete(perm);
    setBusyRole(role);
    try {
      await api.put(`/admin/rbac/roles/${encodeURIComponent(role)}`, { permissions: [...current] });
      toast.push(t("common.saved"), "success");
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusyRole(null);
    }
  };

  if (loading) return <SkeletonRows rows={6} cols={4} />;
  if (error) return <EmptyState title={t("common.error")} desc={error} />;
  if (!data) return null;

  const roles = Object.keys(data.roles);

  return (
    <Card pad0>
      <CardHead title={t("system.tabRbac", { defaultValue: "Access matrix" })} />
      <div className="nx-table-wrap" style={{ overflowX: "auto" }}>
        <table className="nx-table">
          <thead>
            <tr>
              <th>{t("system.permission", { defaultValue: "Permission" })}</th>
              {roles.map((r) => <th key={r}>{r}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.permissions.map((perm) => (
              <tr key={perm}>
                <td className="nx-mono" style={{ fontSize: 12 }}>{perm}</td>
                {roles.map((role) => {
                  const on = (data.roles[role] || []).includes(perm);
                  return (
                    <td key={role}>
                      <input
                        type="checkbox"
                        checked={on}
                        disabled={busyRole === role || role === "sudo"}
                        onChange={(e) => togglePerm(role, perm, e.target.checked)}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
};
