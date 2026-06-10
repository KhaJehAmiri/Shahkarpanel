import { FC, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { NodeItem, Tunnel } from "../api/types";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import { useFetch, usePolling } from "../lib/useFetch";
import { statusTone } from "../lib/format";
import {
  Button, Callout, Card, CopyField, EmptyState, Field, Input, Modal, Pager, Pill, Select, SkeletonRows, UsageBar, usePagedList, useToast,
} from "../components/ui";
import { IcPlus, IcRefresh, IcTrash, IcLink, IcEdit, IcEye, IcBolt } from "../components/icons";
import { AddNodeModal, AddNodePreset } from "../components/AddNodeModal";
import { isIranNode } from "../lib/region";
/** @deprecated Use /nodes — kept for old bookmarks. */
export const Infrastructure: FC = () => <Navigate to="/nodes" replace />;

export const NodesTab: FC<{ resellerMode?: boolean }> = ({ resellerMode }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const { consumeIntent } = useCopilot();
  const [show, setShow] = useState(false);
  const [editNode, setEditNode] = useState<NodeItem | null>(null);
  const [xrayNode, setXrayNode] = useState<NodeItem | null>(null);
  const [preset, setPreset] = useState<AddNodePreset>({});
  const { data, loading, error, reload } = useFetch<NodeItem[]>(() => api.get("/nodes"), []);
  const provisioning = (data || []).some((n) => n.provision_status === "provisioning");
  usePolling(reload, 3000, provisioning);
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
  const remove = async (n: NodeItem) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try { await api.del(`/node/${n.id}`); toast.push(t("common.deleted"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <>
      {!resellerMode && (
        <>
          <Callout tone="info" title={t("infra.xrayVersionHintTitle")}>
            {t("infra.xrayVersionHint")}
          </Callout>
          <NodeGroupsPanel />
        </>
      )}
      <div className="nx-page-actions">
        {(data?.length ?? 0) > 8 && (
          <Input value={nodeSearch} onChange={(e: any) => { setNodeSearch(e.target.value); pager.setPage(0); }} placeholder={t("common.search")} style={{ maxWidth: 220 }} />
        )}
        <Button variant="ghost" title={t("common.refresh")} onClick={reload}><IcRefresh className="nx-ico" /></Button>
        <Button variant="primary" onClick={openAdd}><IcPlus className="nx-ico" /> {t("infra.addNode")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={4} cols={5} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} action={<Button onClick={reload}>{t("common.retry")}</Button>} />
          : !filteredNodes.length ? <EmptyState title={t("common.noData")} action={<Button variant="primary" onClick={openAdd}><IcPlus className="nx-ico" /> {t("infra.addNode")}</Button>} />
          : (
            <div className="nx-table-wrap">
              <table className="nx-table">
                <thead><tr>
                  <th>{t("common.name")}</th><th>{t("infra.address")}</th><th>{t("common.status")}</th>
                  <th>{t("infra.region")}</th>
                  <th title={t("infra.xrayVersionHint")}>{t("infra.xrayVersionCol")}</th>
                  <th>{t("infra.latency")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {pager.slice.map((n) => (
                    <tr key={n.id}>
                      <td style={{ fontWeight: 600 }}>{n.name}{n.core_kind === "wireguard" ? <span style={{ marginInlineStart: 8 }}><Pill tone="info">WG</Pill></span> : null}</td>
                      <td className="nx-mono" style={{ fontSize: 12 }}>{n.address}:{n.port}</td>
                      <td style={{ minWidth: 160 }}>
                        {n.provision_status === "provisioning" ? (
                          <div className="nx-stack" style={{ gap: 6 }}>
                            <div className="nx-row" style={{ justifyContent: "space-between", fontSize: 12 }}>
                              <span>{provisionLabel(n.provision_step)}</span>
                              <span className="nx-mono">{n.provision_progress ?? 5}%</span>
                            </div>
                            <UsageBar pct={n.provision_progress ?? 5} />
                          </div>
                        ) : n.provision_status === "failed" ? (
                          <>
                            <Pill tone="danger" dot>{t("infra.provisionFailedShort")}</Pill>
                            {n.provision_message ? <div className="nx-faint" style={{ fontSize: 11, marginTop: 4 }}>{n.provision_message}</div> : null}
                          </>
                        ) : (
                          <>
                            <Pill tone={statusTone(n.status)} dot>{t(`users.status.${n.status}`, n.status)}</Pill>
                            {n.message ? <div className="nx-faint" style={{ fontSize: 11 }}>{n.message}</div> : null}
                          </>
                        )}
                      </td>
                      <td>{n.region || "—"}</td>
                      <td className="nx-mono" style={{ fontSize: 12 }}>{n.xray_version || "—"}</td>
                      <td>{n.latency_ms != null ? `${n.latency_ms.toFixed(0)} ms` : "—"}</td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6, flexWrap: "wrap" }}>
                          {/* Xray version endpoint is sudo-only — hide for resellers. */}
                          {n.core_kind !== "wireguard" && !resellerMode && (
                            <Button size="sm" variant="primary" onClick={() => setXrayNode(n)} title={t("infra.xraySetVersion")}>
                              {t("infra.xraySetVersion")}
                            </Button>
                          )}
                          {!resellerMode && (
                            <Button size="sm" variant="ghost" onClick={() => setEditNode(n)} title={t("infra.editNode")}>
                              <IcEdit className="nx-ico" />
                            </Button>
                          )}
                          {n.provision_status !== "provisioning" && (
                            <Button size="sm" onClick={() => reconnect(n)} title={t("infra.reconnect")}><IcRefresh className="nx-ico" /> {t("infra.reconnect")}</Button>
                          )}
                          <Button variant="danger" size="sm" title={t("common.delete")} onClick={() => remove(n)}><IcTrash className="nx-ico" /></Button>
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
    </>
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
      <div className="nx-card-title" style={{ marginBottom: 8 }}>{t("infra.nodeGroups")}</div>
      <div className="nx-row" style={{ gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <Input value={name} onChange={(e: any) => setName(e.target.value)} placeholder={t("common.name")} style={{ maxWidth: 180 }} />
        <Input value={region} onChange={(e: any) => setRegion(e.target.value)} placeholder={t("infra.region")} style={{ maxWidth: 140 }} />
        <Button size="sm" variant="primary" disabled={busy || !name.trim()} onClick={add}><IcPlus className="nx-ico" /> {t("common.create")}</Button>
      </div>
      {loading ? (
        <SkeletonRows rows={1} cols={3} />
      ) : !data?.length ? (
        <div className="nx-faint" style={{ fontSize: 12 }}>{t("common.noData")}</div>
      ) : (
        <div className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
          {data.map((g) => (
            <Pill key={g.id} tone="accent">
              {g.name}{g.region ? ` · ${g.region}` : ""}
              <button type="button" className="nx-btn icon ghost sm" style={{ marginInlineStart: 6 }} title={t("common.delete")} aria-label={t("common.delete")} onClick={() => remove(g)}>×</button>
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
  const groups = useFetch<NodeGroupRow[]>(() => api.get("/node/groups"), []);
  const [name, setName] = useState(node.name);
  const [address, setAddress] = useState(node.address);
  const [region, setRegion] = useState(node.region || "");
  const [groupId, setGroupId] = useState(node.group_id != null ? String(node.group_id) : "");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await api.put(`/node/${node.id}`, {
        name: name.trim(),
        address: address.trim(),
        region: region.trim() || null,
        group_id: groupId ? parseInt(groupId, 10) : null,
      });
      toast.push(t("common.saved"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open title={`${t("infra.editNode")} — ${node.name}`} onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !name.trim() || !address.trim()} onClick={submit}>{t("common.save")}</Button>
      </>}>
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={name} onChange={(e: any) => setName(e.target.value)} autoFocus /></Field>
        <Field label={t("infra.address")}><Input value={address} onChange={(e: any) => setAddress(e.target.value)} /></Field>
        <Field label={t("infra.region")}><Input value={region} onChange={(e: any) => setRegion(e.target.value)} /></Field>
        <Field label={t("infra.nodeGroup")}>
          <Select value={groupId} onChange={(e: any) => setGroupId(e.target.value)}>
            <option value="">—</option>
            {(groups.data || []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </Select>
        </Field>
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
      <div className="nx-faint" style={{ fontSize: 12, marginTop: 8 }}>{t("infra.xrayVersion")}: {node.xray_version || "—"}</div>
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
  const enabled = isEnabled("tunneling");
  const { data, loading, error, status, reload } = useFetch<Tunnel[]>(() => api.get("/tunnels"), []);
  const nodes = useFetch<NodeItem[]>(() => api.get("/nodes"), []);

  if (!enabled || status === 404) {
    return <Callout tone="warn" title={t("infra.tunnelsDisabled")}>{t("common.disabledFeature")}</Callout>;
  }

  const remove = async (id: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try { await api.del(`/tunnels/${id}`); toast.push(t("common.deleted"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  const apply = async (id: number) => {
    try { await api.post(`/tunnels/${id}/apply`, {}); toast.push(t("infra.tunnelApplied"), "success"); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  const endName = (id: number | null, kind: "panel" | "node") =>
    kind === "panel" || id == null
      ? t("infra.panelEndpoint")
      : nodes.data?.find((n) => n.id === id)?.name || `#${id}`;

  return (
    <>
      <Callout tone="info" title={t("infra.tabTunnels")}>{t("infra.tunnelDesc")}</Callout>
      <div className="nx-row" style={{ justifyContent: "flex-end", margin: "14px 0", gap: 8 }}>
        <Button variant="ghost" onClick={reload}><IcRefresh className="nx-ico" /></Button>
        <Button variant="primary" onClick={() => setShow(true)}><IcLink className="nx-ico" /> {t("infra.addTunnel")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={3} cols={4} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !data?.length ? <EmptyState title={t("common.noData")} />
          : (
            <div className="nx-table-wrap">
              <table className="nx-table">
                <thead><tr>
                  <th>{t("common.name")}</th><th>{t("infra.relayNode")}</th><th>{t("infra.exitNode")}</th>
                  <th>{t("infra.transport")}</th><th>{t("infra.listenPort")}→{t("infra.targetPort")}</th>
                  <th>{t("common.status")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {data.map((tn) => (
                    <tr key={tn.id}>
                      <td style={{ fontWeight: 600 }}>{tn.name}</td>
                      <td>{endName(tn.relay_node_id, tn.relay_kind)}</td>
                      <td>{endName(tn.exit_node_id, tn.exit_kind)}</td>
                      <td><Pill tone="accent">{tn.transport}</Pill></td>
                      <td className="nx-mono">{tn.listen_port} → {tn.target_port}</td>
                      <td><Pill tone={tn.enabled ? "ok" : "default"}>{tn.enabled ? t("common.enabled") : t("common.disabled")}</Pill></td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                          <Button size="sm" variant="ghost" title={t("infra.applyTunnel")} disabled={!tn.enabled} onClick={() => apply(tn.id)}><IcBolt className="nx-ico" /></Button>
                          <Button size="sm" variant="ghost" title={t("infra.viewConfig")} onClick={() => setConfigId(tn.id)}><IcEye className="nx-ico" /></Button>
                          <Button size="sm" variant="ghost" onClick={() => setEdit(tn)}><IcEdit className="nx-ico" /></Button>
                          <Button variant="danger" size="sm" onClick={() => remove(tn.id)}><IcTrash className="nx-ico" /></Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      {show && <AddTunnel nodes={nodes.data || []} onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
      {edit && <EditTunnel tunnel={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
      {configId != null && <TunnelConfigModal tunnelId={configId} onClose={() => setConfigId(null)} />}
    </>
  );
};

/* -------------------------------- Hosts --------------------------------- */
export const HostsTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { data, loading, error, reload } = useFetch<Record<string, any[]>>(() => api.get("/hosts"), []);
  const [draft, setDraft] = useState<Record<string, any[]> | null>(null);
  const [busy, setBusy] = useState(false);
  const hosts = draft ?? data ?? {};

  const setHost = (tag: string, idx: number, key: string, value: any) => {
    const copy: Record<string, any[]> = JSON.parse(JSON.stringify(hosts));
    copy[tag][idx][key] = value;
    setDraft(copy);
  };
  const addHost = (tag: string) => {
    const copy: Record<string, any[]> = JSON.parse(JSON.stringify(hosts));
    copy[tag] = [...(copy[tag] || []), {
      remark: "{USERNAME}", address: "", port: null, sni: "", host: "", path: "",
      security: "inbound_default", alpn: "", fingerprint: "", allowinsecure: false,
      is_disabled: false, mux_enable: false, fragment_setting: "", noise_setting: "",
      random_user_agent: false, use_sni_as_host: false,
    }];
    setDraft(copy);
  };
  const delHost = (tag: string, idx: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    const copy: Record<string, any[]> = JSON.parse(JSON.stringify(hosts));
    copy[tag].splice(idx, 1);
    setDraft(copy);
  };

  const save = async () => {
    setBusy(true);
    try { await api.put("/hosts", hosts); toast.push(t("common.saved"), "success"); setDraft(null); reload(); }
    catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  if (loading) return <Card><SkeletonRows rows={4} cols={3} /></Card>;
  if (error) return <EmptyState title={t("common.error")} desc={error} />;

  return (
    <>
      <Callout tone="info" title={t("infra.tabHosts")}>{t("infra.hostsDesc")}</Callout>
      <div className="nx-row" style={{ justifyContent: "flex-end", margin: "14px 0" }}>
        <Button variant="primary" disabled={busy || !draft} onClick={save}>{t("common.save")}</Button>
      </div>
      <div className="nx-stack">
        {Object.keys(hosts).map((tag) => (
          <Card key={tag}>
            <div className="nx-row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
              <b>{tag}</b>
              <Button size="sm" onClick={() => addHost(tag)}><IcPlus className="nx-ico" /> {t("common.add")}</Button>
            </div>
            {!hosts[tag]?.length ? <div className="nx-faint" style={{ fontSize: 12 }}>{t("infra.noHost")}</div>
              : <div className="nx-stack" style={{ gap: 12 }}>
                  {hosts[tag].map((h: any, idx: number) => (
                    <div key={idx} className="nx-card" style={{ background: "var(--nx-surface-2)", padding: 12 }}>
                      <div className="nx-row" style={{ gap: 10, flexWrap: "wrap" }}>
                        <Field label={t("infra.remark")}><Input value={h.remark || ""} onChange={(e: any) => setHost(tag, idx, "remark", e.target.value)} style={{ maxWidth: 160 }} /></Field>
                        <Field label={t("infra.address")}><Input value={h.address || ""} onChange={(e: any) => setHost(tag, idx, "address", e.target.value)} placeholder={t("infra.hostAddressPlaceholder")} style={{ maxWidth: 200 }} /></Field>
                        <Field label={t("infra.port")}><Input type="number" value={h.port ?? ""} onChange={(e: any) => setHost(tag, idx, "port", e.target.value ? parseInt(e.target.value) : null)} style={{ maxWidth: 100 }} /></Field>
                        <Field label={t("infra.hostSni")}><Input value={h.sni || ""} onChange={(e: any) => setHost(tag, idx, "sni", e.target.value)} style={{ maxWidth: 160 }} /></Field>
                        <Field label={t("infra.hostHost")}><Input value={h.host || ""} onChange={(e: any) => setHost(tag, idx, "host", e.target.value)} style={{ maxWidth: 160 }} /></Field>
                        <Field label={t("infra.hostPath")}><Input value={h.path || ""} onChange={(e: any) => setHost(tag, idx, "path", e.target.value)} style={{ maxWidth: 140 }} /></Field>
                        <Field label={t("infra.hostTls")}><Select value={h.security || "inbound_default"} onChange={(e: any) => setHost(tag, idx, "security", e.target.value)}>
                          {["inbound_default", "none", "tls"].map((s) => <option key={s}>{s}</option>)}
                        </Select></Field>
                        <Field label={t("infra.hostAlpn")}><Input value={h.alpn || ""} onChange={(e: any) => setHost(tag, idx, "alpn", e.target.value)} style={{ maxWidth: 120 }} /></Field>
                        <Field label={t("infra.hostFp")}><Input value={h.fingerprint || ""} onChange={(e: any) => setHost(tag, idx, "fingerprint", e.target.value)} style={{ maxWidth: 100 }} /></Field>
                        <label className="nx-row" style={{ gap: 6, fontSize: 12 }}><input type="checkbox" checked={!!h.allowinsecure} onChange={(e) => setHost(tag, idx, "allowinsecure", e.target.checked)} /> {t("infra.hostInsecure")}</label>
                        <label className="nx-row" style={{ gap: 6, fontSize: 12 }}><input type="checkbox" checked={!!h.is_disabled} onChange={(e) => setHost(tag, idx, "is_disabled", e.target.checked)} /> {t("infra.hostDisabled")}</label>
                        <label className="nx-row" style={{ gap: 6, fontSize: 12 }}><input type="checkbox" checked={!!h.mux_enable} onChange={(e) => setHost(tag, idx, "mux_enable", e.target.checked)} /> {t("infra.hostMux")}</label>
                        <label className="nx-row" style={{ gap: 6, fontSize: 12 }}><input type="checkbox" checked={!!h.use_sni_as_host} onChange={(e) => setHost(tag, idx, "use_sni_as_host", e.target.checked)} /> {t("infra.hostSniAsHost")}</label>
                        <Field label={t("infra.hostFragment")}><Input value={h.fragment_setting || ""} onChange={(e: any) => setHost(tag, idx, "fragment_setting", e.target.value)} style={{ maxWidth: 140 }} /></Field>
                        <Field label={t("infra.hostNoise")}><Input value={h.noise_setting || ""} onChange={(e: any) => setHost(tag, idx, "noise_setting", e.target.value)} style={{ maxWidth: 140 }} /></Field>
                        <div style={{ alignSelf: "flex-end" }}><Button variant="danger" size="sm" title={t("common.delete")} onClick={() => delHost(tag, idx)}><IcTrash className="nx-ico" /></Button></div>
                      </div>
                    </div>
                  ))}
                </div>}
          </Card>
        ))}
      </div>
    </>
  );
};

const EditTunnel: FC<{ tunnel: Tunnel; onClose: () => void; onDone: () => void }> = ({ tunnel, onClose, onDone }) => {
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
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} /></Field>
        <label className="nx-row" style={{ gap: 8 }}><input type="checkbox" checked={f.enabled} onChange={upd("enabled")} /> {t("common.enabled")}</label>
        <Field label={t("infra.transport")}>
          <Select value={f.transport} onChange={upd("transport")}>
            {["reality", "ws", "grpc", "tcp"].map((x) => <option key={x} value={x}>{x}</option>)}
          </Select>
        </Field>
        <div className="nx-row" style={{ gap: 12 }}>
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
      {loading ? <div className="nx-faint">{t("common.loading")}</div>
        : error ? <div className="nx-callout danger">{error}</div>
        : <pre className="nx-code" style={{ fontSize: 11, maxHeight: 400, overflow: "auto", whiteSpace: "pre-wrap" }}>
            {JSON.stringify(data, null, 2)}
          </pre>}
    </Modal>
  );
};

const AddTunnel: FC<{ nodes: NodeItem[]; onClose: () => void; onDone: () => void }> = ({ nodes, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const deploy = useFetch<{ panel_region: string }>(() => api.get("/system/deployment"), []);
  const irNodes = nodes.filter((n) => isIranNode(n.region));
  const foreignNodes = nodes.filter((n) => !isIranNode(n.region));
  const panelForeign = deploy.data?.panel_region === "foreign";

  const defaultRelay = irNodes[0]?.id ?? "";
  const defaultExit = foreignNodes[0]?.id ?? "";

  const [f, setF] = useState({
    name: "", relay: String(defaultRelay || ""), exit: String(defaultExit || ""),
    transport: "reality", listen: "443", target: "443",
  });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  useEffect(() => {
    if (!f.relay && defaultRelay) setF((s) => ({ ...s, relay: String(defaultRelay) }));
    if (!f.exit && defaultExit) setF((s) => ({ ...s, exit: String(defaultExit) }));
  }, [defaultRelay, defaultExit, f.relay, f.exit]);

  // "panel" => this panel's local core is that end; otherwise a node id string.
  const endId = (v: string): number | null => (v === "panel" ? null : parseInt(v));

  const submit = async () => {
    if (f.relay === "panel" && f.exit === "panel") {
      toast.push(t("infra.tunnelBothPanel"), "error"); return;
    }
    setBusy(true);
    try {
      await api.post("/tunnels", {
        name: f.name.trim(), relay_node_id: endId(f.relay), exit_node_id: endId(f.exit),
        transport: f.transport, listen_port: parseInt(f.listen), target_port: parseInt(f.target),
      });
      toast.push(t("common.created"), "success"); onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  const bothPanel = f.relay === "panel" && f.exit === "panel";

  return (
    <Modal open title={t("infra.addTunnel")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !f.name || !f.relay || !f.exit || bothPanel} onClick={submit}>{t("common.create")}</Button></>}>
      <div className="nx-stack">
        {deploy.data && (
          <Callout tone="info">
            {panelForeign ? t("infra.tunnelHintPanelForeign") : t("infra.tunnelHintPanelIran")}
          </Callout>
        )}
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("infra.relayNode")} hint={t("infra.relayEndHint")}>
            <Select value={f.relay} onChange={upd("relay")}>
              <option value="">—</option>
              <option value="panel">{t("infra.panelEndpoint")}</option>
              {(irNodes.length ? irNodes : nodes).map((n) => <option key={n.id} value={n.id}>{n.name} ({n.region || "?"})</option>)}
            </Select>
          </Field>
          <Field label={t("infra.exitNode")} hint={t("infra.exitEndHint")}>
            <Select value={f.exit} onChange={upd("exit")}>
              <option value="">—</option>
              <option value="panel">{t("infra.panelEndpoint")}</option>
              {(foreignNodes.length ? foreignNodes : nodes).map((n) => <option key={n.id} value={n.id}>{n.name} ({n.region || "?"})</option>)}
            </Select>
          </Field>
        </div>
        <Field label={t("infra.transport")}>
          <Select value={f.transport} onChange={upd("transport")}>
            {["reality", "ws", "grpc", "tcp"].map((x) => <option key={x} value={x}>{x}</option>)}
          </Select>
        </Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("infra.listenPort")}><Input type="number" value={f.listen} onChange={upd("listen")} /></Field>
          <Field label={t("infra.targetPort")}><Input type="number" value={f.target} onChange={upd("target")} /></Field>
        </div>
      </div>
    </Modal>
  );
};
