import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { NodeItem, Tunnel } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { statusTone } from "../lib/format";
import { PageHeader } from "../components/Shell";
import {
  Button, Callout, Card, EmptyState, Field, Input, Modal, Pill, Select, SkeletonRows, Tabs, useToast,
} from "../components/ui";
import { IcPlus, IcRefresh, IcTrash, IcLink } from "../components/icons";

export const Infrastructure: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const [tab, setTab] = useState("nodes");
  const tabs = [
    { id: "nodes", label: t("infra.tabNodes") },
    ...(admin?.is_sudo ? [{ id: "inbounds", label: t("infra.tabInbounds") }, { id: "hosts", label: t("infra.tabHosts") }] : []),
    { id: "tunnels", label: t("infra.tabTunnels") },
  ];
  return (
    <div>
      <PageHeader title={t("infra.title")} subtitle={t("infra.subtitle")} />
      <Tabs active={tab} onChange={setTab} tabs={tabs} />
      {tab === "nodes" && <NodesTab />}
      {tab === "inbounds" && <InboundsTab />}
      {tab === "hosts" && <HostsTab />}
      {tab === "tunnels" && <TunnelsTab />}
    </div>
  );
};

const NodesTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const { data, loading, error, reload } = useFetch<NodeItem[]>(() => api.get("/nodes"), []);

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
        <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("infra.addNode")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={4} cols={5} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} action={<Button onClick={reload}>{t("common.retry")}</Button>} />
          : !data?.length ? <EmptyState title={t("common.noData")} action={<Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("infra.addNode")}</Button>} />
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
                      <td style={{ fontWeight: 600 }}>{n.name}</td>
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
      {show && <AddNode onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
    </>
  );
};

const AddNode: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState({ name: "", address: "", port: "62050", api_port: "62051", region: "" });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/node", {
        name: f.name.trim(), address: f.address.trim(),
        port: parseInt(f.port), api_port: parseInt(f.api_port),
        region: f.region.trim() || null, add_as_new_host: true, usage_coefficient: 1,
      });
      toast.push(t("common.created"), "success"); onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Modal open title={t("infra.addNode")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !f.name || !f.address} onClick={submit}>{t("common.create")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={f.name} onChange={upd("name")} autoFocus /></Field>
        <Field label={t("infra.address")}><Input value={f.address} onChange={upd("address")} placeholder="1.2.3.4" /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={t("infra.port")}><Input type="number" value={f.port} onChange={upd("port")} /></Field>
          <Field label={t("infra.apiPort")}><Input type="number" value={f.api_port} onChange={upd("api_port")} /></Field>
        </div>
        <Field label={`${t("infra.region")} (${t("common.optional")})`}><Input value={f.region} onChange={upd("region")} /></Field>
      </div>
    </Modal>
  );
};

const TunnelsTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { isEnabled } = useApp();
  const [show, setShow] = useState(false);
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
                      <td><div className="nx-row" style={{ justifyContent: "flex-end" }}><Button variant="danger" size="sm" onClick={() => remove(tn.id)}><IcTrash className="nx-ico" /></Button></div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      {show && <AddTunnel nodes={nodes.data || []} onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
    </>
  );
};

/* ------------------------------ Inbounds -------------------------------- */
const PROTOCOLS = ["vless", "vmess", "trojan", "shadowsocks"];
const NETWORKS = ["tcp", "ws", "grpc"];
const SS_METHODS = ["chacha20-ietf-poly1305", "aes-256-gcm", "aes-128-gcm"];

function buildInbound(f: any) {
  const stream: any = { network: f.network, security: "none" };
  if (f.network === "ws") stream.wsSettings = { path: f.path || "/" };
  if (f.network === "grpc") stream.grpcSettings = { serviceName: f.path || "" };
  const settings: any = { clients: [] };
  if (f.protocol === "vless") settings.decryption = "none";
  if (f.protocol === "shadowsocks") { settings.network = "tcp,udp"; settings.method = f.method; }
  const inbound: any = {
    tag: f.tag.trim(),
    listen: "0.0.0.0",
    port: parseInt(f.port),
    protocol: f.protocol,
    settings,
  };
  if (f.protocol !== "shadowsocks") inbound.streamSettings = stream;
  return inbound;
}

const isUserInbound = (i: any) => PROTOCOLS.includes(i?.protocol);

const InboundsTab: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const { data, loading, error, reload } = useFetch<any>(() => api.get("/core/config"), []);
  const inbounds = (data?.inbounds || []).filter(isUserInbound);

  const save = async (config: any) => {
    await api.put("/core/config", config);
  };

  const remove = async (tag: string) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      const cfg = { ...data, inbounds: data.inbounds.filter((i: any) => i.tag !== tag) };
      await save(cfg);
      toast.push(t("common.deleted"), "success");
      reload();
    } catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <>
      <Callout tone="info" title={t("infra.tabInbounds")}>{t("infra.inboundsDesc")}</Callout>
      <div className="nx-row" style={{ justifyContent: "flex-end", margin: "14px 0", gap: 8 }}>
        <Button variant="ghost" onClick={reload}><IcRefresh className="nx-ico" /></Button>
        <Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("infra.addInbound")}</Button>
      </div>
      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={4} cols={4} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !inbounds.length ? <EmptyState title={t("common.noData")} action={<Button variant="primary" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("infra.addInbound")}</Button>} />
          : (
            <div className="nx-table-wrap"><table className="nx-table">
              <thead><tr><th>{t("common.name")}</th><th>Protocol</th><th>{t("infra.port")}</th><th>{t("infra.transport")}</th><th style={{ textAlign: "end" }}>{t("common.actions")}</th></tr></thead>
              <tbody>
                {inbounds.map((i: any) => (
                  <tr key={i.tag}>
                    <td style={{ fontWeight: 600 }}>{i.tag}</td>
                    <td><Pill tone="accent">{i.protocol}</Pill></td>
                    <td className="nx-mono">{i.port}</td>
                    <td>{i.streamSettings?.network || "tcp"}{i.streamSettings?.wsSettings?.path ? ` ${i.streamSettings.wsSettings.path}` : ""}</td>
                    <td><div className="nx-row" style={{ justifyContent: "flex-end" }}><Button variant="danger" size="sm" onClick={() => remove(i.tag)}><IcTrash className="nx-ico" /></Button></div></td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
      </Card>
      {show && <AddInbound config={data} onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
    </>
  );
};

const AddInbound: FC<{ config: any; onClose: () => void; onDone: () => void }> = ({ config, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState({ tag: "", protocol: "vless", port: "443", network: "tcp", path: "/", method: SS_METHODS[0] });
  const [busy, setBusy] = useState(false);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    setBusy(true);
    try {
      const exists = (config.inbounds || []).some((i: any) => i.tag === f.tag.trim() || String(i.port) === f.port);
      if (exists) { toast.push("Tag or port already in use", "error"); setBusy(false); return; }
      const cfg = { ...config, inbounds: [...(config.inbounds || []), buildInbound(f)] };
      await api.put("/core/config", cfg);
      toast.push(t("common.created"), "success");
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Modal open title={t("infra.addInbound")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !f.tag || !f.port} onClick={submit}>{t("common.create")}</Button></>}>
      <div className="nx-stack">
        <Callout tone="warn">{t("infra.inboundRestart")}</Callout>
        <Field label={`${t("common.name")} (tag)`}><Input value={f.tag} onChange={upd("tag")} placeholder="VLESS WS 2" autoFocus /></Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label="Protocol"><Select value={f.protocol} onChange={upd("protocol")}>{PROTOCOLS.map((p) => <option key={p}>{p}</option>)}</Select></Field>
          <Field label={t("infra.port")}><Input type="number" value={f.port} onChange={upd("port")} /></Field>
        </div>
        {f.protocol !== "shadowsocks" ? (
          <div className="nx-row" style={{ gap: 12 }}>
            <Field label={t("infra.transport")}><Select value={f.network} onChange={upd("network")}>{NETWORKS.map((n) => <option key={n}>{n}</option>)}</Select></Field>
            {(f.network === "ws" || f.network === "grpc") && (
              <Field label={f.network === "ws" ? "path" : "serviceName"}><Input value={f.path} onChange={upd("path")} /></Field>
            )}
          </div>
        ) : (
          <Field label="method"><Select value={f.method} onChange={upd("method")}>{SS_METHODS.map((m) => <option key={m}>{m}</option>)}</Select></Field>
        )}
      </div>
    </Modal>
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
    copy[tag] = [...(copy[tag] || []), { remark: "{USERNAME}", address: "", port: null, sni: "", host: "", path: "", security: "inbound_default" }];
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
