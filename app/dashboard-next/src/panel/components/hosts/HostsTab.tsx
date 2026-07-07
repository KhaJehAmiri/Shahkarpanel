"use client";

import { FC, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../../context/AppContext";
import { api } from "../../api/client";
import { useFetch } from "../../lib/useFetch";
import { Button, Callout, EmptyState, Pill, SkeletonRows, Stat, Toggle, useToast } from "../ui";
import { IcCheck, IcEdit, IcGlobe, IcPlus, IcTrash } from "../icons";
import { HostEditorModal } from "./HostEditorModal";
import { HostCloneModal } from "./HostCloneModal";
import { emptyHost } from "./types";
import {
  cloneHosts,
  flattenHosts,
  formatEndpoint,
  reindexSortOrder,
  type HostRecord,
  type HostRowRef,
} from "./types";
import "./hosts.css";

type EditorState =
  | { mode: "add"; tag: string; host: HostRecord }
  | { mode: "edit"; tag: string; index: number; host: HostRecord }
  | null;

export const HostsTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { admin, hasPermission } = useApp();
  const canWrite = hasPermission("hosts:write");
  const readOnly = !canWrite;
  const { data, loading, error, reload } = useFetch<Record<string, HostRecord[]>>(
    () => api.get("/hosts"),
    [],
  );
  const edge = useFetch<{
    enabled?: boolean;
    cdn_runtime_enabled?: boolean;
    routes?: { host: string; inbound_tag: string }[];
    nginx_writable?: boolean;
    desired_written?: boolean;
  }>(() => (admin?.is_sudo ? api.get("/edge/status") : Promise.resolve({})), [admin?.is_sudo]);
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState<EditorState>(null);
  const [cloneOpen, setCloneOpen] = useState(false);

  const hosts = data ?? {};
  const inboundTags = useMemo(() => Object.keys(hosts).sort(), [hosts]);
  const rows = useMemo(() => flattenHosts(hosts), [hosts]);

  const stats = useMemo(() => {
    const total = rows.length;
    const disabled = rows.filter((r) => r.host.is_disabled).length;
    return { total, enabled: total - disabled, disabled };
  }, [rows]);

  const persist = useCallback(
    async (next: Record<string, HostRecord[]>) => {
      // Persist the visible array order by stamping sort_order per position;
      // the backend re-sorts by sort_order on read.
      const ordered = reindexSortOrder(next);
      setBusy(true);
      try {
        await api.put("/hosts", ordered);
        toast.push(t("common.saved"), "success");
        reload();
      } catch (e: unknown) {
        toast.push(e instanceof Error ? e.message : String(e), "error");
        throw e;
      } finally {
        setBusy(false);
      }
    },
    [reload, t, toast],
  );

  const openAdd = () => {
    const tag = inboundTags[0];
    if (!tag) return;
    setEditor({ mode: "add", tag, host: emptyHost() });
  };

  const openEdit = (row: HostRowRef) => {
    setEditor({
      mode: "edit",
      tag: row.tag,
      index: row.index,
      host: { ...row.host },
    });
  };

  const handleModalSave = async (tag: string, host: HostRecord) => {
    const copy = cloneHosts(hosts);
    if (editor?.mode === "add") {
      copy[tag] = [...(copy[tag] || []), host];
    } else if (editor?.mode === "edit") {
      copy[editor.tag][editor.index] = host;
    }
    try {
      await persist(copy);
      setEditor(null);
    } catch {
      /* toast already shown */
    }
  };

  const toggleEnable = async (row: HostRowRef) => {
    const copy = cloneHosts(hosts);
    copy[row.tag][row.index] = { ...copy[row.tag][row.index], is_disabled: !row.host.is_disabled };
    try {
      await persist(copy);
    } catch {
      /* toast already shown */
    }
  };

  const removeHost = async (row: HostRowRef) => {
    if (!confirm(t("common.confirmDelete"))) return;
    const copy = cloneHosts(hosts);
    copy[row.tag].splice(row.index, 1);
    try {
      await persist(copy);
    } catch {
      /* toast already shown */
    }
  };

  const moveHost = async (row: HostRowRef, dir: -1 | 1) => {
    const copy = cloneHosts(hosts);
    const list = copy[row.tag];
    const to = row.index + dir;
    if (to < 0 || to >= list.length) return;
    [list[row.index], list[to]] = [list[to], list[row.index]];
    try {
      await persist(copy);
    } catch {
      /* toast already shown */
    }
  };

  const securityLabel = (sec: string) => {
    if (!sec || sec === "inbound_default") return t("infra.hostSecuritySame");
    return sec;
  };

  if (loading) {
    return (
      <div className="nx-hosts-page">
        <SkeletonRows rows={4} cols={3} />
      </div>
    );
  }
  if (error) return <EmptyState title={t("common.error")} desc={error} />;

  return (
    <div className="nx-hosts-page">
      <Callout tone="info" title={t("infra.tabHosts")}>
        {t("infra.hostsDescAuto")}
      </Callout>

      {edge.data && admin?.is_sudo && (
        <Callout tone={edge.data.enabled ? "ok" : "info"} title={t("infra.cdnStatus", { defaultValue: "CDN / edge proxy" })}>
          <div className="nx-stack" style={{ gap: 4, fontSize: 13 }}>
            <div>
              {edge.data.cdn_runtime_enabled
                ? t("infra.cdnRuntimeOn", { defaultValue: "CDN runtime active" })
                : t("infra.cdnRuntimeOff", { defaultValue: "CDN runtime inactive" })}
            </div>
            <div className="nx-faint">
              {t("infra.cdnRoutes", { defaultValue: "{{count}} nginx route(s)", count: edge.data.routes?.length || 0 })}
              {" · "}
              {edge.data.nginx_writable
                ? t("infra.cdnNginxWritable", { defaultValue: "nginx writable" })
                : t("infra.cdnNginxReadonly", { defaultValue: "nginx read-only" })}
            </div>
          </div>
        </Callout>
      )}

      <div className="nx-hosts-stats">
        <Stat label={t("infra.hostStatTotal")} value={stats.total} icon={<IcGlobe className="nx-ico" />} />
        <Stat label={t("infra.hostStatEnabled")} value={stats.enabled} icon={<IcCheck className="nx-ico" />} />
        <Stat label={t("infra.hostStatDisabled")} value={stats.disabled} />
      </div>

      {readOnly && (
        <Callout tone="info">{t("infra.hostsReadOnly")}</Callout>
      )}

      <div className="nx-hosts-actions">
        {!readOnly && (
          <>
            <Button variant="primary" disabled={busy || !inboundTags.length} onClick={openAdd}>
              <IcPlus className="nx-ico" /> {t("infra.hostAddTitle")}
            </Button>
            <Button disabled={busy || inboundTags.length < 2} onClick={() => setCloneOpen(true)}>
              {t("infra.hostCloneTemplate", { defaultValue: "Clone hosts" })}
            </Button>
          </>
        )}
      </div>

      {!inboundTags.length ? (
        <EmptyState title={t("common.noData")} desc={t("infra.noInboundForHosts")} />
      ) : !rows.length ? (
        <EmptyState title={t("common.noData")} desc={t("infra.noHost")} />
      ) : (
        <div className="nx-card pad0 nx-hosts-table-card">
          <div className="nx-table-wrap">
            <table className="nx-table">
              <thead>
                <tr>
                  <th>{t("common.actions")}</th>
                  <th>{t("common.enable")}</th>
                  <th>{t("infra.remark")}</th>
                  <th>{t("infra.hostEndpoint")}</th>
                  <th>{t("infra.hostInbound")}</th>
                  <th>{t("infra.hostTls")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const listLen = hosts[row.tag]?.length ?? 0;
                  const canUp = row.index > 0;
                  const canDown = row.index < listLen - 1;
                  return (
                    <tr key={`${row.tag}-${row.index}`} className={row.host.is_disabled ? "is-muted" : ""}>
                      <td>
                        {!readOnly ? (
                          <div className="nx-hosts-row-actions">
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={busy || !canUp}
                              title={t("infra.hostMoveUp")}
                              onClick={() => moveHost(row, -1)}
                            >
                              ↑
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={busy || !canDown}
                              title={t("infra.hostMoveDown")}
                              onClick={() => moveHost(row, 1)}
                            >
                              ↓
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={busy}
                              title={t("common.edit")}
                              onClick={() => openEdit(row)}
                            >
                              <IcEdit className="nx-ico" />
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              disabled={busy}
                              title={t("common.delete")}
                              onClick={() => removeHost(row)}
                            >
                              <IcTrash className="nx-ico" />
                            </Button>
                          </div>
                        ) : (
                          <span className="nx-muted">—</span>
                        )}
                      </td>
                      <td>
                        <Toggle
                          on={!row.host.is_disabled}
                          disabled={busy || readOnly}
                          label={t("common.enable")}
                          onChange={() => toggleEnable(row)}
                        />
                      </td>
                      <td className="nx-hosts-remark">{row.host.remark || "—"}</td>
                      <td className="nx-hosts-mono" dir="ltr">
                        {formatEndpoint(row.host)}
                      </td>
                      <td>
                        <Pill tone="accent">{row.tag}</Pill>
                      </td>
                      <td>
                        <Pill>{securityLabel(row.host.security)}</Pill>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {editor && (
        <HostEditorModal
          open
          mode={editor.mode}
          inboundTag={editor.tag}
          inboundTags={inboundTags}
          initial={editor.host}
          busy={busy}
          onClose={() => setEditor(null)}
          onSave={handleModalSave}
        />
      )}

      {cloneOpen && (
        <HostCloneModal
          inboundTags={inboundTags}
          onClose={() => setCloneOpen(false)}
          onDone={() => { setCloneOpen(false); reload(); }}
        />
      )}
    </div>
  );
};
