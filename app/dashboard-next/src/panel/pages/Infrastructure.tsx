import { FC, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { NodeItem, Tunnel, TunnelHealth } from "../api/types";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import { useFetch, useLiveReload, usePolling } from "../lib/useFetch";
import { formatAgo, statusTone } from "../lib/format";
import {
  Button, Callout, Card, CardHead, CopyField, EmptyState, Field, Input, Modal, Pager, Pill, Select, SkeletonRows, UsageBar, usePagedList, useToast,
} from "../components/ui";
import { IcPlus, IcRefresh, IcTrash, IcLink, IcEdit, IcEye, IcBolt } from "../components/icons";
import { TableRowMenu, type TableMenuItem } from "../components/TableRowMenu";
import { AddNodeModal, AddNodePreset } from "../components/AddNodeModal";
import { RetryProvisionModal } from "../components/RetryProvisionModal";
import { NodeXrayOverrideModal } from "../components/NodeXrayOverrideModal";
import { isIranNode, pickNodeByRegion } from "../lib/region";
/** @deprecated Use /nodes — kept for old bookmarks. */
export const Infrastructure: FC = () => <Navigate to="/nodes" replace />;

export const NodesTab: FC<{ resellerMode?: boolean }> = ({ resellerMode }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const { consumeIntent } = useCopilot();
  const [show, setShow] = useState(false);
  const [editNode, setEditNode] = useState<NodeItem | null>(null);
  const [xrayNode, setXrayNode] = useState<NodeItem | null>(null);
  const [overrideNode, setOverrideNode] = useState<NodeItem | null>(null);
  const [retryNode, setRetryNode] = useState<NodeItem | null>(null);
  const [preset, setPreset] = useState<AddNodePreset>({});
  const { data, loading, error, reload } = useFetch<NodeItem[]>(() => api.get("/nodes"), []);
  const provisioning = (data || []).some((n) => n.provision_status === "provisioning");
  usePolling(reload, 3000, provisioning);
  useLiveReload(reload, 30000);
  const [nodeSearch, setNodeSearch] = useState("");
  const filteredNodes = (data || []).filter((n) =>
    !nodeSearch.trim() || `${n.name} ${n.address} ${n.region || ""}`.toLowerCase().includes(nodeSearch.trim().toLowerCase()),
  );
  const pager = usePagedList(filteredNodes, 20);

  const provisionLabel = (step?: string | null) => {
    if (!step) return t("infra.provisionStep.queued");
    const key = `infra.provisionStep.${step}`;
    const label = t(key);
    return label === key ? step : label;
  };

  // Copilot / WireGuard page deep-link into the unified add-server modal.
  useEffect(() => {
    if (consumeIntent("add-wg-node")) { setPreset({ coreKind: "wireguard" }); setShow(true); }
    else if (consumeIntent("add-node-ssh") || consumeIntent("add-node")) { setPreset({ coreKind: "xray" }); setShow(true); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openAdd = () => { setPreset({}); setShow(true); };

  const reconnect = async (n: NodeItem) => {
    if (!confirm(t("infra.reconnectConfirm", { name: n.name }))) return;
    try { await api.post(`/node/${n.id}/reconnect`); toast.push(t("infra.reconnecting"), "success"); }
    catch (e: any) { toast.push(e.message, "error"); }
  };
  const converge = async (n: NodeItem) => {
    try {
      await api.post(`/node/${n.id}/converge`);
      toast.push(t("infra.converging"), "success");
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };
  const updateAgent = async (n: NodeItem) => {
    if (!confirm(t("infra.updateAgentConfirm", { name: n.name }))) return;
    try {
      const res = await api.post<{ job_id: string }>(`/system/agent-updates/apply/${n.id}`);
      toast.push(t("infra.updateAgentStarted"), "success");
      const jobId = res.job_id;
      const tick = async () => {
        try {
          const job = await api.get<{
            finished: boolean;
            status: string;
            error_message?: string;
            message?: string;
          }>(`/system/agent-updates/jobs/${jobId}`);
          if (!job.finished) {
            setTimeout(tick, 2000);
            return;
          }
          if (job.status === "success") toast.push(t("infra.updateAgentDone", { name: n.name }), "success");
          else toast.push(job.error_message || job.message || t("infra.updateAgentFailed"), "error");
          reload();
        } catch {
          setTimeout(tick, 3000);
        }
      };
      setTimeout(tick, 1500);
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };
  const remove = async (n: NodeItem) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try { await api.del(`/node/${n.id}`); toast.push(t("common.deleted"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <div className="sk-stack sk-hub-panel">
      {!resellerMode && (
        <>
          <p className="sk-hub-lede">
            <strong>{t("infra.xrayVersionHintTitle")}. </strong>
            {t("infra.xrayVersionHint")}
          </p>
          <NodeGroupsPanel />
        </>
      )}
      <div className="sk-proto-toolbar">
        <div className="sk-proto-toolbar-start">
          {(data?.length ?? 0) > 8 && (
            <Input
              value={nodeSearch}
              onChange={(e: any) => { setNodeSearch(e.target.value); pager.setPage(0); }}
              placeholder={t("common.search")}
              style={{ maxWidth: 220 }}
            />
          )}
        </div>
        <div className="sk-proto-toolbar-end">
          <Button size="sm" variant="ghost" title={t("common.refresh")} onClick={reload}>
            <IcRefresh className="sk-ico" />
          </Button>
          <Button size="sm" variant="primary" onClick={openAdd}>
            <IcPlus className="sk-ico" /> {t("infra.addNode")}
          </Button>
        </div>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={4} cols={5} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} action={<Button onClick={reload}>{t("common.retry")}</Button>} />
          : !filteredNodes.length ? <EmptyState title={t("common.noData")} action={<Button variant="primary" onClick={openAdd}><IcPlus className="sk-ico" /> {t("infra.addNode")}</Button>} />
          : (
            <div className="sk-table-wrap">
              <table className="sk-table">
                <thead>
                  <tr>
                    <th>{t("common.name")}</th>
                    <th>{t("infra.address")}</th>
                    <th>{t("common.status")}</th>
                    <th>{t("infra.region")}</th>
                    <th title={t("infra.xrayVersionHint")}>{t("infra.xrayVersionCol")}</th>
                    <th className="sk-num">{t("infra.latency")}</th>
                    <th className="sk-actions" />
                  </tr>
                </thead>
                <tbody>
                  {pager.slice.map((n) => {
                    const menuItems: TableMenuItem[] = [];
                    if (!resellerMode) {
                      menuItems.push({
                        id: "xray",
                        label: t("infra.xraySetVersion"),
                        onClick: () => setXrayNode(n),
                      });
                      if (n.core_kind !== "wireguard") {
                        menuItems.push({
                          id: "override",
                          label: t("infra.xrayConfigOverride"),
                          icon: <IcBolt className="sk-ico" />,
                          onClick: () => setOverrideNode(n),
                        });
                      }
                      menuItems.push({
                        id: "edit",
                        label: t("infra.editNode"),
                        icon: <IcEdit className="sk-ico" />,
                        onClick: () => setEditNode(n),
                      });
                      if (n.provision_status !== "provisioning" && n.provision_status !== "failed") {
                        menuItems.push({
                          id: "agent",
                          label: t("infra.updateAgent"),
                          onClick: () => updateAgent(n),
                        });
                      }
                    }
                    if (n.provision_status === "failed") {
                      menuItems.push({
                        id: "retry",
                        label: t("infra.provisionRetry"),
                        icon: <IcRefresh className="sk-ico" />,
                        onClick: () => setRetryNode(n),
                      });
                    }
                    if ((n.health_status || n.status) === "drifted") {
                      menuItems.push({
                        id: "converge",
                        label: t("infra.converge"),
                        icon: <IcRefresh className="sk-ico" />,
                        onClick: () => converge(n),
                      });
                    }
                    if (n.provision_status !== "provisioning") {
                      menuItems.push({
                        id: "reconnect",
                        label: t("infra.reconnect"),
                        icon: <IcRefresh className="sk-ico" />,
                        onClick: () => reconnect(n),
                      });
                    }
                    menuItems.push({
                      id: "del",
                      label: t("common.delete"),
                      icon: <IcTrash className="sk-ico" />,
                      danger: true,
                      onClick: () => remove(n),
                    });

                    return (
                      <tr key={n.id} className={n.provision_status === "failed" ? "is-muted" : undefined}>
                        <td>
                          <div className="sk-proto-name">
                            <span className="sk-proto-name-main">
                              {n.name}
                              {n.core_kind === "wireguard" ? (
                                <span className="sk-proto-chip is-muted" style={{ marginInlineStart: 6 }}>WG</span>
                              ) : null}
                            </span>
                          </div>
                        </td>
                        <td className="sk-mono sk-proto-meta" dir="ltr">{n.address}:{n.port}</td>
                        <td>
                          {n.provision_status === "provisioning" ? (
                            <div className="sk-stack" style={{ gap: 4, minWidth: 140 }}>
                              <div className="sk-row" style={{ justifyContent: "space-between", gap: 8 }}>
                                <span className="sk-proto-meta">{provisionLabel(n.provision_step)}</span>
                                <span className="sk-mono sk-proto-meta">{n.provision_progress ?? 5}%</span>
                              </div>
                              <UsageBar pct={n.provision_progress ?? 5} />
                            </div>
                          ) : n.provision_status === "failed" ? (
                            <div className="sk-proto-name">
                              <Pill tone="danger" dot>{t("infra.provisionFailedShort")}</Pill>
                              {n.provision_message ? (
                                <span className="sk-proto-name-sub">{n.provision_message}</span>
                              ) : null}
                            </div>
                          ) : (
                            <div className="sk-proto-name">
                              {(() => {
                                const hs = n.health_status || n.status;
                                return (
                                  <Pill tone={statusTone(hs)} dot>{t(`infra.status.${hs}`, hs)}</Pill>
                                );
                              })()}
                              {n.control_tunneled ? (
                                <span className="sk-proto-name-sub">{t("infra.controlTunneled")}</span>
                              ) : null}
                              {n.drift_reason ? (
                                <span className="sk-proto-name-sub">{n.drift_reason}</span>
                              ) : null}
                              {n.last_ack_at ? (
                                <span className="sk-proto-name-sub">{t("infra.lastAck")}: {formatAgo(n.last_ack_at)}</span>
                              ) : null}
                              {typeof n.reported_peer_count === "number" && n.reported_peer_count > 0 ? (
                                <span className="sk-proto-name-sub">{t("infra.peers")}: {n.reported_peer_count}</span>
                              ) : null}
                              {n.message ? <span className="sk-proto-name-sub">{n.message}</span> : null}
                            </div>
                          )}
                        </td>
                        <td className="sk-proto-meta">{n.region || "—"}</td>
                        <td className="sk-mono sk-proto-meta">{n.xray_version || "—"}</td>
                        <td className="sk-num sk-proto-meta">
                          {n.latency_ms != null ? `${n.latency_ms.toFixed(0)} ms` : "—"}
                        </td>
                        <td className="sk-actions">
                          <TableRowMenu items={menuItems} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      <Pager page={pager.page} pages={pager.pages} onPage={pager.setPage} />
      {!resellerMode && <TopologyCard />}
      {show && (
        <AddNodeModal
          preset={preset}
          onClose={() => setShow(false)}
          onDone={() => { setShow(false); reload(); }}
        />
      )}
      {xrayNode && (
        <XrayVersionModal node={xrayNode} onClose={() => setXrayNode(null)} onDone={() => { setXrayNode(null); reload(); }} />
      )}
      {editNode && (
        <EditNodeModal node={editNode} onClose={() => setEditNode(null)} onDone={() => { setEditNode(null); reload(); }} />
      )}
      {overrideNode && (
        <NodeXrayOverrideModal node={overrideNode} onClose={() => setOverrideNode(null)} onDone={() => { setOverrideNode(null); reload(); }} />
      )}
      {retryNode && (
        <RetryProvisionModal
          node={retryNode}
          onClose={() => setRetryNode(null)}
          onDone={() => { setRetryNode(null); reload(); }}
        />
      )}
    </div>
  );
};

type NodeGroupRow = { id: number; name: string; region?: string | null };

const NodeGroupsPanel: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { data, loading, reload } = useFetch<NodeGroupRow[]>(() => api.get("/node/groups"), []);
  const [name, setName] = useState("");
  const [region, setRegion] = useState("");
  const [busy, setBusy] = useState(false);

  const add = async () => {
    if (!name.trim()) {
      toast.push(t("infra.nameRequired"), "error");
      return;
    }
    setBusy(true);
    try {
      await api.post("/node/groups", { name: name.trim(), region: region.trim() || null });
      setName("");
      setRegion("");
      toast.push(t("common.created"), "success");
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (g: NodeGroupRow) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      await api.del(`/node/groups/${g.id}`);
      toast.push(t("common.deleted"), "success");
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  return (
    <Card style={{ marginBottom: 14, padding: 14 }}>
      <div className="sk-card-title" style={{ marginBottom: 8 }}>{t("infra.nodeGroups")}</div>
      <div className="sk-row" style={{ gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <Input value={name} onChange={(e: any) => setName(e.target.value)} placeholder={t("common.name")} style={{ maxWidth: 180 }} />
        <Input value={region} onChange={(e: any) => setRegion(e.target.value)} placeholder={t("infra.region")} style={{ maxWidth: 140 }} />
        <Button size="sm" variant="primary" disabled={busy || !name.trim()} onClick={add}><IcPlus className="sk-ico" /> {t("common.create")}</Button>
      </div>
      {loading ? (
        <SkeletonRows rows={1} cols={3} />
      ) : !data?.length ? (
        <div className="sk-faint" style={{ fontSize: 12 }}>{t("common.noData")}</div>
      ) : (
        <div className="sk-row" style={{ gap: 8, flexWrap: "wrap" }}>
          {data.map((g) => (
            <Pill key={g.id} tone="accent">
              {g.name}{g.region ? ` · ${g.region}` : ""}
              <button type="button" className="sk-btn icon ghost sm" style={{ marginInlineStart: 6 }} title={t("common.delete")} aria-label={t("common.delete")} onClick={() => remove(g)}>×</button>
            </Pill>
          ))}
        </div>
      )}
    </Card>
  );
};

const EditNodeModal: FC<{ node: NodeItem; onClose: () => void; onDone: () => void }> = ({ node, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const releases = useFetch<{ tag: string }[]>(() => api.get("/xray/releases"), []);
  const [name, setName] = useState(node.name);
  const [address, setAddress] = useState(node.address);
  const [tag, setTag] = useState("");
  const [busy, setBusy] = useState(false);
  const [xrayBusy, setXrayBusy] = useState(false);
  const [liveVersion, setLiveVersion] = useState(node.xray_version || "");

  const submit = async () => {
    setBusy(true);
    try {
      await api.put(`/node/${node.id}`, {
        name: name.trim(),
        address: address.trim(),
      });
      toast.push(t("common.saved"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const applyXray = async () => {
    if (!tag) return;
    if (!confirm(t("infra.xrayUpgradeConfirm"))) return;
    setXrayBusy(true);
    try {
      const res = await api.post<{ version: string }>(`/nodes/${node.id}/xray/version`, { version: tag });
      const ver = res.version || tag;
      setLiveVersion(ver);
      toast.push(ver, "success");
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setXrayBusy(false);
    }
  };

  return (
    <Modal open title={`${t("infra.editNode")} — ${node.name}`} onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || xrayBusy || !name.trim() || !address.trim()} onClick={submit}>{t("common.save")}</Button>
      </>}>
      <div className="sk-stack">
        <Field label={t("common.name")}><Input value={name} onChange={(e: any) => setName(e.target.value)} autoFocus /></Field>
        <Field label={t("infra.address")}><Input value={address} onChange={(e: any) => setAddress(e.target.value)} /></Field>

        <div style={{ borderTop: "1px solid var(--sk-border, rgba(127,127,127,.25))", paddingTop: 12, marginTop: 4 }}>
          <div className="sk-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ fontWeight: 600 }}>{t("infra.xraySetVersion")}</span>
            <span className="sk-mono sk-faint" style={{ fontSize: 12 }}>
              {t("infra.xrayVersion")}: {liveVersion || "—"}
            </span>
          </div>
          <Field label={t("infra.xrayPickRelease")}>
            <Select value={tag} onChange={(e: any) => setTag(e.target.value)} disabled={releases.loading || xrayBusy}>
              <option value="">—</option>
              {(releases.data || []).map((r) => <option key={r.tag} value={r.tag}>{r.tag}</option>)}
            </Select>
          </Field>
          <div className="sk-faint" style={{ fontSize: 12, marginBottom: 8 }}>{t("infra.xrayEditHint")}</div>
          <div className="sk-row" style={{ justifyContent: "flex-end" }}>
            <Button variant="primary" size="sm" disabled={xrayBusy || busy || !tag} onClick={applyXray}>
              {xrayBusy ? t("common.loading") : t("infra.xrayApplyVersion")}
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
};

const XrayVersionModal: FC<{ node: NodeItem; onClose: () => void; onDone: () => void }> = ({ node, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const releases = useFetch<{ tag: string }[]>(() => api.get("/xray/releases"), []);
  const [tag, setTag] = useState("");
  const [busy, setBusy] = useState(false);

  const apply = async () => {
    if (!tag) return;
    if (!confirm(t("infra.xrayUpgradeConfirm"))) return;
    setBusy(true);
    try {
      const res = await api.post<{ version: string }>(`/nodes/${node.id}/xray/version`, { version: tag });
      toast.push(res.version || t("common.saved"), "success");
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Modal open title={`${t("infra.xraySetVersion")} — ${node.name}`} onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !tag} onClick={apply}>{t("common.save")}</Button>
      </>}>
      <Field label={t("infra.xrayPickRelease")}>
        <Select value={tag} onChange={(e: any) => setTag(e.target.value)} disabled={releases.loading}>
          <option value="">—</option>
          {(releases.data || []).map((r) => <option key={r.tag} value={r.tag}>{r.tag}</option>)}
        </Select>
      </Field>
      <div className="sk-faint" style={{ fontSize: 12, marginTop: 8 }}>{t("infra.xrayVersion")}: {node.xray_version || "—"}</div>
    </Modal>
  );
};

export const TunnelsTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { isEnabled } = useApp();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<Tunnel | null>(null);
  const [configId, setConfigId] = useState<number | null>(null);
  const [healthMap, setHealthMap] = useState<Record<number, TunnelHealth | "loading" | "error">>({});
  const enabled = isEnabled("tunneling");
  const { data, loading, error, status, reload } = useFetch<Tunnel[]>(() => api.get("/tunnels"), []);
  const nodes = useFetch<NodeItem[]>(() => api.get("/nodes"), []);
  const templates = useFetch<TunnelTemplatesResponse>(() => api.get("/tunnels/templates"), []);
  const transports = useFetch<TransportsResponse>(() => api.get("/tunnels/transports"), []);

  const loadHealth = async (id: number) => {
    setHealthMap((prev) => ({ ...prev, [id]: "loading" }));
    try {
      const h = await api.get<TunnelHealth>(`/tunnels/${id}/health`);
      setHealthMap((prev) => ({ ...prev, [id]: h }));
    } catch {
      setHealthMap((prev) => ({ ...prev, [id]: "error" }));
    }
  };

  useEffect(() => {
    if (!data?.length) return;
    data.filter((tn) => tn.enabled).forEach((tn) => { void loadHealth(tn.id); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  if (!enabled || status === 404) {
    return <Callout tone="warn" title={t("infra.tunnelsDisabled")}>{t("common.disabledFeature")}</Callout>;
  }

  const remove = async (id: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try { await api.del(`/tunnels/${id}`); toast.push(t("common.deleted"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  const apply = async (id: number) => {
    try {
      const res = await api.post<{ health?: TunnelHealth }>(`/tunnels/${id}/apply`, {});
      if (res.health) setHealthMap((prev) => ({ ...prev, [id]: res.health! }));
      toast.push(t("infra.tunnelApplied"), "success");
    } catch (e: any) { toast.push(e.message, "error"); }
  };

  const healthHint = (h: TunnelHealth) => {
    const parts: string[] = [];
    const c = h.checks || {};
    if (c.relay && c.relay.connected === false) parts.push(t("infra.tunnelHealthRelayDown"));
    if (c.transit && c.transit.connected === false) parts.push(t("infra.tunnelHealthTransitDown"));
    if (c.exit && c.exit.connected === false) parts.push(t("infra.tunnelHealthExitDown"));
    if (c.transit_listen && c.transit_listen.reachable === false) parts.push(t("infra.tunnelHealthTransitListenDown"));
    if (c.exit_listen && c.exit_listen.reachable === false) parts.push(t("infra.tunnelHealthListenDown"));
    return parts.join(" · ");
  };

  const renderHealth = (tn: Tunnel) => {
    if (!tn.enabled) return <span className="sk-proto-meta">—</span>;
    const h = healthMap[tn.id];
    if (h === "loading") return <span className="sk-proto-meta">{t("common.loading")}</span>;
    if (h === "error") return <Pill tone="default">?</Pill>;
    if (!h) return <span className="sk-proto-meta">—</span>;
    const hint = healthHint(h);
    return (
      <div className="sk-proto-name">
        <Pill tone={h.healthy ? "ok" : "danger"} dot>
          {h.healthy ? t("infra.tunnelHealthOk") : t("infra.tunnelHealthDown")}
        </Pill>
        {hint ? <span className="sk-proto-name-sub">{hint}</span> : null}
      </div>
    );
  };

  const endName = (id: number | null, kind: "panel" | "node") =>
    kind === "panel" || id == null
      ? t("infra.panelEndpoint")
      : nodes.data?.find((n) => n.id === id)?.name || `#${id}`;

  return (
    <div className="sk-stack sk-hub-panel">
      <p className="sk-hub-lede">{t("infra.tunnelDesc")}</p>
      <div className="sk-proto-toolbar">
        <div className="sk-proto-toolbar-start" />
        <div className="sk-proto-toolbar-end">
          <Button size="sm" variant="ghost" onClick={reload}><IcRefresh className="sk-ico" /></Button>
          <Button size="sm" variant="primary" onClick={() => setShow(true)}>
            <IcLink className="sk-ico" /> {t("infra.addTunnel")}
          </Button>
        </div>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !data?.length ? <EmptyState title={t("common.noData")} />
          : (
            <div className="sk-table-wrap">
              <table className="sk-table">
                <thead>
                  <tr>
                    <th>{t("common.name")}</th>
                    <th>{t("infra.relayNode")}</th>
                    <th>{t("infra.transitNode")}</th>
                    <th>{t("infra.exitNode")}</th>
                    <th>{t("infra.transport")}</th>
                    <th>{t("infra.listenPort")}→{t("infra.targetPort")}</th>
                    <th>{t("infra.tunnelHealthCol")}</th>
                    <th>{t("common.status")}</th>
                    <th className="sk-actions" />
                  </tr>
                </thead>
                <tbody>
                  {data.map((tn) => (
                    <tr key={tn.id} className={tn.enabled ? undefined : "is-muted"}>
                      <td><span className="sk-proto-name-main">{tn.name}</span></td>
                      <td className="sk-proto-meta">{endName(tn.relay_node_id, tn.relay_kind)}</td>
                      <td className="sk-proto-meta">{tn.intermediate_node_id ? endName(tn.intermediate_node_id, "node") : "—"}</td>
                      <td className="sk-proto-meta">{endName(tn.exit_node_id, tn.exit_kind)}</td>
                      <td><span className="sk-proto-chip">{tn.transport}</span></td>
                      <td className="sk-mono sk-proto-meta">{tn.listen_port} → {tn.target_port}</td>
                      <td>{renderHealth(tn)}</td>
                      <td>
                        <Pill tone={tn.enabled ? "ok" : "default"} dot>
                          {tn.enabled ? t("common.enabled") : t("common.disabled")}
                        </Pill>
                      </td>
                      <td className="sk-actions">
                        <TableRowMenu
                          items={[
                            {
                              id: "health",
                              label: t("infra.tunnelHealthRefresh"),
                              icon: <IcRefresh className="sk-ico" />,
                              disabled: !tn.enabled,
                              onClick: () => void loadHealth(tn.id),
                            },
                            {
                              id: "apply",
                              label: t("infra.applyTunnel"),
                              icon: <IcBolt className="sk-ico" />,
                              disabled: !tn.enabled,
                              onClick: () => apply(tn.id),
                            },
                            {
                              id: "config",
                              label: t("infra.viewConfig"),
                              icon: <IcEye className="sk-ico" />,
                              onClick: () => setConfigId(tn.id),
                            },
                            {
                              id: "edit",
                              label: t("common.edit"),
                              icon: <IcEdit className="sk-ico" />,
                              onClick: () => setEdit(tn),
                            },
                            {
                              id: "del",
                              label: t("common.delete"),
                              icon: <IcTrash className="sk-ico" />,
                              danger: true,
                              onClick: () => remove(tn.id),
                            },
                          ]}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      {show && (
        <AddTunnel
          nodes={nodes.data || []}
          templates={templates}
          transports={transports.data?.transports || []}
          onClose={() => setShow(false)}
          onDone={() => { setShow(false); reload(); }}
        />
      )}
      {edit && (
        <EditTunnel
          tunnel={edit}
          transports={transports.data?.transports || []}
          onClose={() => setEdit(null)}
          onDone={() => { setEdit(null); reload(); }}
        />
      )}
      {configId != null && <TunnelConfigModal tunnelId={configId} onClose={() => setConfigId(null)} />}
    </div>
  );
};

/* -------------------------------- Hosts --------------------------------- */
export { HostsTab } from "../components/hosts/HostsTab";

type TunnelTemplateSpec = {
  id?: string;
  label: string;
  hops?: number;
  transport?: string;
  relay_region?: string;
  exit_region?: string;
  category?: string;
};

type TunnelTemplatesResponse = {
  templates: Record<string, TunnelTemplateSpec>;
  iran_pairs: Record<string, TunnelTemplateSpec>;
};

type TemplatesFetchState = {
  data: TunnelTemplatesResponse | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
};

type TunnelTransportMeta = {
  id: string;
  label: string;
  engine: "xray" | "singbox";
  stub?: boolean;
  description?: string;
};

type TransportsResponse = { transports: TunnelTransportMeta[] };

const TunnelTransportSelect: FC<{
  value: string;
  onChange: (e: { target: { value: string } }) => void;
  transports: TunnelTransportMeta[];
  hint?: string;
}> = ({ value, onChange, transports, hint }) => {
  const { t } = useTranslation();
  const xray = transports.filter((tr) => tr.engine === "xray");
  const singbox = transports.filter((tr) => tr.engine === "singbox");
  const fallback = ["reality", "ws", "grpc", "tcp", "quic", "hysteria2", "tuic"];

  return (
    <Field label={t("infra.transport")} hint={hint}>
      <Select value={value} onChange={onChange}>
        {(xray.length ? xray : fallback.filter((id) => id !== "hysteria2" && id !== "tuic").map((id) => ({ id, label: id, engine: "xray" as const }))).map((tr) => (
          <option key={tr.id} value={tr.id}>{tr.label}</option>
        ))}
        {singbox.length > 0 && (
          <optgroup label={t("infra.tunnelSingboxTransports")}>
            {singbox.map((tr) => (
              <option key={tr.id} value={tr.id}>{tr.label}{tr.stub ? " *" : ""}</option>
            ))}
          </optgroup>
        )}
      </Select>
    </Field>
  );
};

const EditTunnel: FC<{ tunnel: Tunnel; transports: TunnelTransportMeta[]; onClose: () => void; onDone: () => void }> = ({
  tunnel, transports, onClose, onDone,
}) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState({
    name: tunnel.name,
    enabled: tunnel.enabled,
    transport: tunnel.transport,
    listen: String(tunnel.listen_port),
    target: String(tunnel.target_port),
  });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const submit = async () => {
    setBusy(true);
    try {
      await api.patch(`/tunnels/${tunnel.id}`, {
        name: f.name.trim(),
        enabled: f.enabled,
        transport: f.transport,
        listen_port: parseInt(f.listen, 10),
        target_port: parseInt(f.target, 10),
      });
      toast.push(t("common.saved"), "success");
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Modal open title={`${t("common.edit")} — ${tunnel.name}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy} onClick={submit}>{t("common.save")}</Button></>}>
      <div className="sk-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} /></Field>
        <label className="sk-row" style={{ gap: 8 }}><input type="checkbox" checked={f.enabled} onChange={upd("enabled")} /> {t("common.enabled")}</label>
        <TunnelTransportSelect
          value={f.transport}
          onChange={upd("transport")}
          transports={transports}
          hint={transports.find((tr) => tr.id === f.transport)?.stub ? t("infra.tunnelSingboxStubHint") : undefined}
        />
        <div className="sk-row" style={{ gap: 12 }}>
          <Field label={t("infra.listenPort")}><Input type="number" value={f.listen} onChange={upd("listen")} /></Field>
          <Field label={t("infra.targetPort")}><Input type="number" value={f.target} onChange={upd("target")} /></Field>
        </div>
      </div>
    </Modal>
  );
};

const TunnelConfigModal: FC<{ tunnelId: number; onClose: () => void }> = ({ tunnelId, onClose }) => {
  const { t } = useTranslation();
  const { data, loading, error } = useFetch<Record<string, unknown>>(() => api.get(`/tunnels/${tunnelId}/config`), [tunnelId]);

  return (
    <Modal open title={t("infra.tunnelConfig")} onClose={onClose} wide
      footer={<Button variant="ghost" onClick={onClose}>{t("common.close")}</Button>}>
      {loading ? <div className="sk-faint">{t("common.loading")}</div>
        : error ? <div className="sk-callout danger">{error}</div>
        : <pre className="sk-code" style={{ fontSize: 11, maxHeight: 400, overflow: "auto", whiteSpace: "pre-wrap" }}>
            {JSON.stringify(data, null, 2)}
          </pre>}
    </Modal>
  );
};

const AddTunnel: FC<{
  nodes: NodeItem[];
  templates: TemplatesFetchState;
  transports: TunnelTransportMeta[];
  onClose: () => void;
  onDone: () => void;
}> = ({
  nodes, templates, transports, onClose, onDone,
}) => {
  const { t } = useTranslation();
  const toast = useToast();
  const deploy = useFetch<{ panel_region: string }>(() => api.get("/system/deployment"), []);
  const irNodes = nodes.filter((n) => isIranNode(n.region));
  const foreignNodes = nodes.filter((n) => !isIranNode(n.region));
  const panelForeign = deploy.data?.panel_region === "foreign";

  const defaultRelay = irNodes[0]?.id ?? "";
  const defaultExit = foreignNodes[0]?.id ?? "";
  const defaultTransit = foreignNodes[1]?.id ?? foreignNodes[0]?.id ?? "";

  const [f, setF] = useState({
    name: "", template: "", relay: String(defaultRelay || ""), transit: "", exit: String(defaultExit || ""),
    transport: "reality", listen: "443", target: "443", transitPort: "8442",
  });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const selectedTemplate = f.template ? templates.data?.templates?.[f.template] : undefined;
  const needsTransit = (selectedTemplate?.hops ?? 2) >= 3;
  const otherTemplates = Object.entries(templates.data?.templates || {}).filter(([, spec]) => spec.category !== "iran-pair");

  useEffect(() => {
    if (!f.relay && defaultRelay) setF((s) => ({ ...s, relay: String(defaultRelay) }));
    if (!f.exit && defaultExit) setF((s) => ({ ...s, exit: String(defaultExit) }));
    if (needsTransit && !f.transit && defaultTransit) setF((s) => ({ ...s, transit: String(defaultTransit) }));
  }, [defaultRelay, defaultExit, defaultTransit, f.relay, f.exit, f.transit, needsTransit]);

  useEffect(() => {
    if (!f.template || !templates.data) return;
    const spec = templates.data.templates[f.template];
    if (!spec) return;
    setF((s) => {
      const next = { ...s };
      if (spec.transport) next.transport = spec.transport;
      // Prefer real nodes matching the template regions (true node→node).
      // Only fall back to "this panel" when no matching node exists.
      if (spec.relay_region) {
        const relayNode = pickNodeByRegion(nodes, spec.relay_region);
        if (relayNode) next.relay = String(relayNode.id);
        else if (!panelForeign) next.relay = "panel";
      }
      if (spec.exit_region) {
        const exitNode = pickNodeByRegion(nodes, spec.exit_region);
        if (exitNode) next.exit = String(exitNode.id);
        else if (panelForeign) next.exit = "panel";
      }
      if (!s.name.trim() && spec.label) next.name = spec.label;
      return next;
    });
  }, [f.template, templates.data, nodes, panelForeign]);

  // "panel" => this panel's local core is that end; otherwise a node id string.
  const endId = (v: string): number | null => (v === "panel" ? null : parseInt(v, 10));

  const submit = async () => {
    if (f.relay === "panel" && f.exit === "panel") {
      toast.push(t("infra.tunnelBothPanel"), "error"); return;
    }
    if (needsTransit && !f.transit) {
      toast.push(t("infra.tunnelTransitRequired"), "error"); return;
    }
    setBusy(true);
    try {
      await api.post("/tunnels", {
        name: f.name.trim(),
        template_id: f.template || undefined,
        relay_node_id: endId(f.relay),
        intermediate_node_id: f.transit ? endId(f.transit) : undefined,
        intermediate_port: f.transit ? parseInt(f.transitPort, 10) : undefined,
        exit_node_id: endId(f.exit),
        transport: f.transport,
        listen_port: parseInt(f.listen, 10),
        target_port: parseInt(f.target, 10),
      });
      toast.push(t("common.created"), "success"); onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  const bothPanel = f.relay === "panel" && f.exit === "panel";

  return (
    <Modal open title={t("infra.addTunnel")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !f.name || !f.relay || !f.exit || bothPanel || (needsTransit && !f.transit)} onClick={submit}>{t("common.create")}</Button></>}>
      <div className="sk-stack">
        {deploy.data && (
          <Callout tone="info">
            {panelForeign ? t("infra.tunnelHintPanelForeign") : t("infra.tunnelHintPanelIran")}
          </Callout>
        )}
        <Field label={t("infra.tunnelTemplate")} hint={t("infra.tunnelTemplateHint")}>
          <Select value={f.template} onChange={upd("template")} disabled={templates.loading}>
            <option value="">{templates.loading ? t("common.loading") : t("common.none")}</option>
            {Object.keys(templates.data?.iran_pairs || {}).length > 0 && (
              <optgroup label={t("infra.tunnelIranTemplates")}>
                {Object.entries(templates.data!.iran_pairs).map(([id, spec]) => (
                  <option key={id} value={id}>
                    {spec.label} ({spec.relay_region}→{spec.exit_region})
                  </option>
                ))}
              </optgroup>
            )}
            {otherTemplates.length > 0 && (
              <optgroup label={t("infra.tunnelOtherTemplates")}>
                {otherTemplates.map(([id, spec]) => (
                  <option key={id} value={id}>{spec.label} ({spec.hops ?? 2} hops)</option>
                ))}
              </optgroup>
            )}
          </Select>
          {templates.error ? (
            <div className="sk-faint" style={{ fontSize: 12, marginTop: 6, color: "var(--sk-danger)" }}>
              {templates.error}
              <Button size="sm" variant="ghost" onClick={templates.reload}>{t("common.retry")}</Button>
            </div>
          ) : null}
        </Field>
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <div className="sk-row" style={{ gap: 12 }}>
          <Field label={t("infra.relayNode")} hint={t("infra.relayEndHint")}>
            <Select value={f.relay} onChange={upd("relay")}>
              <option value="">—</option>
              <option value="panel">{t("infra.panelEndpoint")}</option>
              {(irNodes.length ? irNodes : nodes).map((n) => <option key={n.id} value={n.id}>{n.name} ({n.region || "?"})</option>)}
            </Select>
          </Field>
          {needsTransit && (
            <Field label={t("infra.transitNode")} hint={t("infra.transitEndHint")}>
              <Select value={f.transit} onChange={upd("transit")}>
                <option value="">—</option>
                {nodes.map((n) => <option key={n.id} value={n.id}>{n.name} ({n.region || "?"})</option>)}
              </Select>
            </Field>
          )}
          <Field label={t("infra.exitNode")} hint={t("infra.exitEndHint")}>
            <Select value={f.exit} onChange={upd("exit")}>
              <option value="">—</option>
              <option value="panel">{t("infra.panelEndpoint")}</option>
              {(foreignNodes.length ? foreignNodes : nodes).map((n) => <option key={n.id} value={n.id}>{n.name} ({n.region || "?"})</option>)}
            </Select>
          </Field>
        </div>
        <TunnelTransportSelect
          value={f.transport}
          onChange={upd("transport")}
          transports={transports}
          hint={transports.find((tr) => tr.id === f.transport)?.stub ? t("infra.tunnelSingboxStubHint") : undefined}
        />
        <div className="sk-row" style={{ gap: 12 }}>
          <Field label={t("infra.listenPort")}><Input type="number" value={f.listen} onChange={upd("listen")} /></Field>
          {needsTransit && (
            <Field label={t("infra.transitPort")}><Input type="number" value={f.transitPort} onChange={upd("transitPort")} /></Field>
          )}
          <Field label={t("infra.targetPort")}><Input type="number" value={f.target} onChange={upd("target")} /></Field>
        </div>
      </div>
    </Modal>
  );
};

type TopologyEdge = { id: number; name: string; source: string; target: string; transport: string; enabled: boolean };
type TopologyResponse = { nodes: { id: number; name: string; address: string; status: string }[]; edges: TopologyEdge[] };

const TopologyCard: FC = () => {
  const { t } = useTranslation();
  const topo = useFetch<TopologyResponse>(() => api.get("/nodes/topology"), []);

  return (
    <Card className="sk-mt-20">
      <CardHead title={t("infra.topology", "Node topology")} actions={
        <Button variant="ghost" size="sm" onClick={topo.reload}>{t("common.refresh")}</Button>
      } />
      {topo.loading ? <SkeletonRows rows={2} cols={3} />
        : topo.error ? <EmptyState title={t("common.error")} desc={topo.error} />
        : (
          <div className="sk-stack" style={{ gap: 8, fontSize: 13 }}>
            {(topo.data?.edges || []).length === 0 ? (
              <div className="sk-faint">{t("infra.topologyEmpty", "No tunnels configured yet.")}</div>
            ) : (
              (topo.data?.edges || []).map((e) => (
                <div key={e.id} className="sk-code" style={{ padding: "8px 10px" }}>
                  <b>{e.name}</b>: {e.source} → {e.target} ({e.transport}) {e.enabled ? "" : `[${t("common.disabled")}]`}
                </div>
              ))
            )}
          </div>
        )}
    </Card>
  );
};
