import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { NodeItem, Tunnel } from "../api/types";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import { useFetch } from "../lib/useFetch";
import { statusTone } from "../lib/format";
import { PageHeader } from "../components/Shell";
import {
  Button, Callout, Card, CopyField, EmptyState, Field, Input, Modal, Pill, Select, SkeletonRows, Tabs, useToast,
} from "../components/ui";
import { IcPlus, IcRefresh, IcTrash, IcLink, IcEdit, IcEye } from "../components/icons";
import { XrayConfigsHub } from "../components/xray/XrayConfigsHub";

export const Infrastructure: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const [tab, setTab] = useState("nodes");
  if (!admin?.is_sudo) {
    return (
      <div>
        <PageHeader title={t("infra.title")} subtitle={t("infra.subtitle")} description={t("infra.description")} />
        <Callout tone="warn">{t("common.sudoOnly")}</Callout>
      </div>
    );
  }
  const tabs = [
    { id: "nodes", label: t("infra.tabNodes") },
    { id: "xray", label: t("xray.tabHub") },
    { id: "hosts", label: t("infra.tabHosts") },
    { id: "tunnels", label: t("infra.tabTunnels") },
  ];
  return (
    <div>
      <PageHeader title={t("infra.title")} subtitle={t("infra.subtitle")} description={t("infra.description")} />
      <Tabs active={tab} onChange={setTab} tabs={tabs} />
      {tab === "nodes" && <NodesTab />}
      {tab === "xray" && <XrayConfigsHub />}
      {tab === "hosts" && <HostsTab />}
      {tab === "tunnels" && <TunnelsTab />}
    </div>
  );
};

const NodesTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { consumeIntent } = useCopilot();
  const [show, setShow] = useState(false);
  const [preset, setPreset] = useState<{ mode?: "manual" | "ssh"; coreKind?: string }>({});
  const { data, loading, error, reload } = useFetch<NodeItem[]>(() => api.get("/nodes"), []);

  // The Copilot can deep-link straight into "add server" with a preset.
  useEffect(() => {
    if (consumeIntent("add-wg-node")) { setPreset({ mode: "manual", coreKind: "wireguard" }); setShow(true); }
    else if (consumeIntent("add-node-ssh")) { setPreset({ mode: "ssh" }); setShow(true); }
    else if (consumeIntent("add-node")) { setPreset({ mode: "manual" }); setShow(true); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openAdd = () => { setPreset({}); setShow(true); };

  const reconnect = async (n: NodeItem) => {
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
      <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 14, gap: 8 }}>
        <Button variant="ghost" onClick={reload}><IcRefresh className="nx-ico" /></Button>
        <Button variant="primary" onClick={openAdd}><IcPlus className="nx-ico" /> {t("infra.addNode")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={4} cols={5} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} action={<Button onClick={reload}>{t("common.retry")}</Button>} />
          : !data?.length ? <EmptyState title={t("common.noData")} action={<Button variant="primary" onClick={openAdd}><IcPlus className="nx-ico" /> {t("infra.addNode")}</Button>} />
          : (
            <div className="nx-table-wrap">
              <table className="nx-table">
                <thead><tr>
                  <th>{t("common.name")}</th><th>{t("infra.address")}</th><th>{t("common.status")}</th>
                  <th>{t("infra.region")}</th><th>{t("infra.xrayVersion")}</th><th>{t("infra.latency")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {data.map((n) => (
                    <tr key={n.id}>
                      <td style={{ fontWeight: 600 }}>{n.name}{n.core_kind === "wireguard" ? <span style={{ marginInlineStart: 8 }}><Pill tone="info">WG</Pill></span> : null}</td>
                      <td className="nx-mono" style={{ fontSize: 12 }}>{n.address}:{n.port}</td>
                      <td><Pill tone={statusTone(n.status)} dot>{n.status}</Pill>{n.message ? <div className="nx-faint" style={{ fontSize: 11 }}>{n.message}</div> : null}</td>
                      <td>{n.region || "—"}</td>
                      <td className="nx-faint">{n.xray_version || "—"}</td>
                      <td>{n.latency_ms != null ? `${n.latency_ms.toFixed(0)} ms` : "—"}</td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 8 }}>
                          <Button size="sm" onClick={() => reconnect(n)}><IcRefresh className="nx-ico" /> {t("infra.reconnect")}</Button>
                          <Button variant="danger" size="sm" onClick={() => remove(n)}><IcTrash className="nx-ico" /></Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      {show && (
        <AddNode
          onClose={() => setShow(false)}
          onDone={() => { setShow(false); reload(); }}
          initialMode={preset.mode}
          initialCoreKind={preset.coreKind}
        />
      )}
    </>
  );
};

type ProvisionResult = { status: string; install_command: string; detail?: string; output?: string };

const AddNode: FC<{
  onClose: () => void;
  onDone: () => void;
  initialMode?: "manual" | "ssh";
  initialCoreKind?: string;
}> = ({ onClose, onDone, initialMode, initialCoreKind }) => {
  const { t } = useTranslation();
  const { isEnabled } = useApp();
  const toast = useToast();
  const canProvision = isEnabled("node_provisioning");
  const [mode, setMode] = useState<"manual" | "ssh">(initialMode || (canProvision ? "ssh" : "manual"));
  const [f, setF] = useState({
    name: "", address: "", port: "62050", api_port: "62051", region: "",
    core_kind: initialCoreKind || "xray",
    ssh_port: "22", username: "root", password: "", role: "direct",
  });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ProvisionResult | null>(null);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const submitManual = async () => {
    setBusy(true);
    try {
      await api.post("/node", {
        name: f.name.trim(), address: f.address.trim(),
        port: parseInt(f.port), api_port: parseInt(f.api_port),
        region: f.region.trim() || null, add_as_new_host: true, usage_coefficient: 1,
        core_kind: f.core_kind,
      });
      toast.push(t("common.created"), "success"); onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  const submitSsh = async () => {
    setBusy(true);
    setResult(null);
    try {
      const res = await api.post<ProvisionResult>("/nodes/provision", {
        name: f.name.trim(), host: f.address.trim(), ssh_port: parseInt(f.ssh_port),
        username: f.username.trim() || "root", password: f.password, role: f.role, run: true,
      });
      setResult(res);
      if (res.status === "provisioned") {
        toast.push(t("infra.provisionStarted"), "success");
        // Give the agent a moment to self-register, then refresh the list.
        setTimeout(onDone, 2500);
      } else {
        toast.push(t("infra.provisionManual"), "info");
      }
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  const valid = mode === "manual"
    ? !!f.name && !!f.address
    : !!f.name && !!f.address && !!f.password;

  return (
    <Modal open title={t("infra.addNode")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !valid} onClick={mode === "manual" ? submitManual : submitSsh}>
          {mode === "manual" ? t("common.create") : t("infra.provisionInstall")}
        </Button></>}>
      <div className="nx-stack">
        {canProvision && (
          <div className="nx-seg">
            <button type="button" className={`nx-seg-btn ${mode === "ssh" ? "active" : ""}`} onClick={() => { setMode("ssh"); setResult(null); }}>
              {t("infra.modeAuto")}
            </button>
            <button type="button" className={`nx-seg-btn ${mode === "manual" ? "active" : ""}`} onClick={() => { setMode("manual"); setResult(null); }}>
              {t("infra.modeManual")}
            </button>
          </div>
        )}

        {mode === "ssh" ? (
          <Callout tone="info">{t("infra.autoHint")}</Callout>
        ) : null}

        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus placeholder="de-node-1" /></Field>
        <Field label={mode === "ssh" ? t("infra.serverIp") : t("infra.address")}>
          <Input value={f.address} onChange={upd("address")} placeholder="1.2.3.4" />
        </Field>

        {mode === "manual" ? (
          <>
            <div className="nx-row" style={{ gap: 12 }}>
              <Field label={t("infra.port")}><Input type="number" value={f.port} onChange={upd("port")} /></Field>
              <Field label={t("infra.apiPort")}><Input type="number" value={f.api_port} onChange={upd("api_port")} /></Field>
            </div>
            <Field label={`${t("infra.region")} (${t("common.optional")})`}><Input value={f.region} onChange={upd("region")} /></Field>
            <Field label={t("infra.coreKind")}>
              <Select value={f.core_kind} onChange={upd("core_kind")}>
                <option value="xray">Xray (v2ray)</option>
                <option value="wireguard">WireGuard</option>
              </Select>
            </Field>
          </>
        ) : (
          <>
            <div className="nx-row" style={{ gap: 12 }}>
              <Field label={t("infra.sshUser")}><Input value={f.username} onChange={upd("username")} placeholder="root" /></Field>
              <Field label={t("infra.sshPort")}><Input type="number" value={f.ssh_port} onChange={upd("ssh_port")} /></Field>
            </div>
            <Field label={t("infra.sshPassword")} hint={t("infra.sshPasswordHint")}>
              <Input type="password" value={f.password} onChange={upd("password")} autoComplete="new-password" />
            </Field>
            <Field label={t("infra.role")}>
              <Select value={f.role} onChange={upd("role")}>
                <option value="direct">direct</option>
                <option value="relay">relay</option>
                <option value="exit">exit</option>
              </Select>
            </Field>
            <div className="nx-faint" style={{ fontSize: 12 }}>{t("infra.autoInstallsHint")}</div>
          </>
        )}

        {result && (
          <div className="nx-stack" style={{ gap: 8 }}>
            <Callout tone={result.status === "provisioned" ? "ok" : "warn"}>
              {result.detail || result.status}
            </Callout>
            {result.status !== "provisioned" && result.install_command && (
              <CopyField label={t("infra.installCommand")} value={result.install_command} multiline />
            )}
          </div>
        )}
      </div>
    </Modal>
  );
};

const TunnelsTab: FC = () => {
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

  const nodeName = (id: number) => nodes.data?.find((n) => n.id === id)?.name || `#${id}`;

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
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {data.map((tn) => (
                    <tr key={tn.id}>
                      <td style={{ fontWeight: 600 }}>{tn.name}</td>
                      <td>{nodeName(tn.relay_node_id)}</td>
                      <td>{nodeName(tn.exit_node_id)}</td>
                      <td><Pill tone="accent">{tn.transport}</Pill></td>
                      <td className="nx-mono">{tn.listen_port} → {tn.target_port}</td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
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
const HostsTab: FC = () => {
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
                        <Field label={t("infra.address")}><Input value={h.address || ""} onChange={(e: any) => setHost(tag, idx, "address", e.target.value)} placeholder="domain or {SERVER_IP}" style={{ maxWidth: 200 }} /></Field>
                        <Field label={t("infra.port")}><Input type="number" value={h.port ?? ""} onChange={(e: any) => setHost(tag, idx, "port", e.target.value ? parseInt(e.target.value) : null)} style={{ maxWidth: 100 }} /></Field>
                        <Field label="SNI"><Input value={h.sni || ""} onChange={(e: any) => setHost(tag, idx, "sni", e.target.value)} style={{ maxWidth: 160 }} /></Field>
                        <Field label="Host"><Input value={h.host || ""} onChange={(e: any) => setHost(tag, idx, "host", e.target.value)} style={{ maxWidth: 160 }} /></Field>
                        <Field label="Path"><Input value={h.path || ""} onChange={(e: any) => setHost(tag, idx, "path", e.target.value)} style={{ maxWidth: 140 }} /></Field>
                        <Field label="TLS"><Select value={h.security || "inbound_default"} onChange={(e: any) => setHost(tag, idx, "security", e.target.value)}>
                          {["inbound_default", "none", "tls"].map((s) => <option key={s}>{s}</option>)}
                        </Select></Field>
                        <Field label="ALPN"><Input value={h.alpn || ""} onChange={(e: any) => setHost(tag, idx, "alpn", e.target.value)} style={{ maxWidth: 120 }} /></Field>
                        <Field label="FP"><Input value={h.fingerprint || ""} onChange={(e: any) => setHost(tag, idx, "fingerprint", e.target.value)} style={{ maxWidth: 100 }} /></Field>
                        <label className="nx-row" style={{ gap: 6, fontSize: 12 }}><input type="checkbox" checked={!!h.allowinsecure} onChange={(e) => setHost(tag, idx, "allowinsecure", e.target.checked)} /> insecure</label>
                        <label className="nx-row" style={{ gap: 6, fontSize: 12 }}><input type="checkbox" checked={!!h.is_disabled} onChange={(e) => setHost(tag, idx, "is_disabled", e.target.checked)} /> disabled</label>
                        <label className="nx-row" style={{ gap: 6, fontSize: 12 }}><input type="checkbox" checked={!!h.mux_enable} onChange={(e) => setHost(tag, idx, "mux_enable", e.target.checked)} /> mux</label>
                        <label className="nx-row" style={{ gap: 6, fontSize: 12 }}><input type="checkbox" checked={!!h.use_sni_as_host} onChange={(e) => setHost(tag, idx, "use_sni_as_host", e.target.checked)} /> sni→host</label>
                        <Field label="Fragment"><Input value={h.fragment_setting || ""} onChange={(e: any) => setHost(tag, idx, "fragment_setting", e.target.value)} style={{ maxWidth: 140 }} /></Field>
                        <Field label="Noise"><Input value={h.noise_setting || ""} onChange={(e: any) => setHost(tag, idx, "noise_setting", e.target.value)} style={{ maxWidth: 140 }} /></Field>
                        <div style={{ alignSelf: "flex-end" }}><Button variant="danger" size="sm" onClick={() => delHost(tag, idx)}><IcTrash className="nx-ico" /></Button></div>
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
  const [f, setF] = useState({ name: "", relay: "", exit: "", transport: "reality", listen: "443", target: "443" });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/tunnels", {
        name: f.name.trim(), relay_node_id: parseInt(f.relay), exit_node_id: parseInt(f.exit),
        transport: f.transport, listen_port: parseInt(f.listen), target_port: parseInt(f.target),
      });
      toast.push(t("common.created"), "success"); onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Modal open title={t("infra.addTunnel")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !f.name || !f.relay || !f.exit} onClick={submit}>{t("common.create")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("infra.relayNode")}>
            <Select value={f.relay} onChange={upd("relay")}><option value="">—</option>{nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}</Select>
          </Field>
          <Field label={t("infra.exitNode")}>
            <Select value={f.exit} onChange={upd("exit")}><option value="">—</option>{nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}</Select>
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
