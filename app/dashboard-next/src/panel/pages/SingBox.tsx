import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { NodeItem, NodeSingBoxConfig, SingBoxTLSStatus } from "../api/types";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import { useFetch } from "../lib/useFetch";
import { PageHeader } from "../components/Shell";
import { Button, Callout, Card, Field, Input, Pill, useToast, SkeletonRows } from "../components/ui";
import { IcPlus, IcUsers } from "../components/icons";

const DEFAULT_CERT = "/var/lib/nexuspanel-node/tls/cert.pem";
const DEFAULT_KEY = "/var/lib/nexuspanel-node/tls/key.pem";

function tlsDefaults(node: NodeItem): { cert: string; key: string; sni: string } {
  const sb = node.singbox;
  return {
    cert: sb?.certificate_path || DEFAULT_CERT,
    key: sb?.key_path || DEFAULT_KEY,
    sni: sb?.sni || node.address,
  };
}

const SingBoxNodeCard: FC<{ node: NodeItem; onSaved: () => void }> = ({ node, onSaved }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const tls = tlsDefaults(node);
  const sb = node.singbox;

  const [certPath, setCertPath] = useState(tls.cert);
  const [keyPath, setKeyPath] = useState(tls.key);
  const [sni, setSni] = useState(tls.sni);
  const [hy2On, setHy2On] = useState(!!sb?.hysteria2_enabled);
  const [hy2Port, setHy2Port] = useState(String(sb?.hysteria2_port ?? 44333));
  const [hy2Up, setHy2Up] = useState(sb?.hysteria2_up_mbps != null ? String(sb.hysteria2_up_mbps) : "");
  const [hy2Down, setHy2Down] = useState(sb?.hysteria2_down_mbps != null ? String(sb.hysteria2_down_mbps) : "");
  const [hy2Obfs, setHy2Obfs] = useState(sb?.hysteria2_obfs_password ?? "");
  const [tuicOn, setTuicOn] = useState(!!sb?.tuic_enabled);
  const [tuicPort, setTuicPort] = useState(String(sb?.tuic_port ?? 44334));
  const [tuicCc, setTuicCc] = useState(sb?.tuic_congestion_control ?? "bbr");
  const [leDomain, setLeDomain] = useState(sb?.tls_le_domain || sb?.sni || "");
  const [leKind, setLeKind] = useState(sb?.tls_le_kind || "auto");
  const [leEmail, setLeEmail] = useState("");
  const [sshPassword, setSshPassword] = useState("");
  const [tlsStatus, setTlsStatus] = useState<SingBoxTLSStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [leBusy, setLeBusy] = useState(false);
  const [syncBusy, setSyncBusy] = useState(false);

  useEffect(() => {
    const d = tlsDefaults(node);
    setCertPath(d.cert);
    setKeyPath(d.key);
    setSni(d.sni);
    setHy2On(!!node.singbox?.hysteria2_enabled);
    setHy2Port(String(node.singbox?.hysteria2_port ?? 44333));
    setHy2Up(node.singbox?.hysteria2_up_mbps != null ? String(node.singbox.hysteria2_up_mbps) : "");
    setHy2Down(node.singbox?.hysteria2_down_mbps != null ? String(node.singbox.hysteria2_down_mbps) : "");
    setHy2Obfs(node.singbox?.hysteria2_obfs_password ?? "");
    setTuicOn(!!node.singbox?.tuic_enabled);
    setTuicPort(String(node.singbox?.tuic_port ?? 44334));
    setTuicCc(node.singbox?.tuic_congestion_control ?? "bbr");
    setLeDomain(node.singbox?.tls_le_domain || node.singbox?.sni || "");
    setLeKind(node.singbox?.tls_le_kind || "auto");
    setTlsStatus(null);
    /* eslint-disable-next-line */
  }, [node.id, node.singbox]);

  const refreshTls = async () => {
    setLeBusy(true);
    try {
      const st = await api.post<SingBoxTLSStatus>(`/node/${node.id}/singbox/tls/refresh`, {
        ssh_password: sshPassword || undefined,
      });
      setTlsStatus(st);
      onSaved();
    } catch (e: any) {
      // Refresh failed — fall back to last known status, but tell the user.
      toast.push(e?.message || t("common.error"), "error");
      try {
        const st = await api.get<SingBoxTLSStatus>(`/node/${node.id}/singbox/tls/status`);
        setTlsStatus(st);
      } catch {
        setTlsStatus(null);
      }
    } finally {
      setLeBusy(false);
    }
  };

  const issueLe = async () => {
    if (!leDomain.trim() || !leEmail.trim() || !sshPassword.trim()) {
      toast.push(t("singbox.leRequired"), "error");
      return;
    }
    setLeBusy(true);
    try {
      const st = await api.post<SingBoxTLSStatus>(`/node/${node.id}/singbox/tls/issue`, {
        identifier: leDomain.trim(),
        tls_kind: leKind,
        email: leEmail.trim(),
        ssh_password: sshPassword,
      });
      setTlsStatus(st);
      setSni(leDomain.trim());
      toast.push(t("singbox.leIssued"), "success");
      onSaved();
    } catch (e: any) {
      toast.push(e?.message || t("common.error"), "error");
    } finally {
      setLeBusy(false);
    }
  };

  const forceSync = async () => {
    setSyncBusy(true);
    try {
      await api.post(`/node/${node.id}/singbox/sync`);
      toast.push(t("singbox.synced"), "success");
      onSaved();
    } catch (e: any) {
      toast.push(e?.message || t("common.error"), "error");
    } finally {
      setSyncBusy(false);
    }
  };

  const renewLe = async () => {
    if (!sshPassword.trim()) {
      toast.push(t("singbox.leRequired"), "error");
      return;
    }
    setLeBusy(true);
    try {
      const st = await api.post<SingBoxTLSStatus>(`/node/${node.id}/singbox/tls/renew`, {
        ssh_password: sshPassword,
      });
      setTlsStatus(st);
      toast.push(t("singbox.leRenewed"), "success");
      onSaved();
    } catch (e: any) {
      toast.push(e?.message || t("common.error"), "error");
    } finally {
      setLeBusy(false);
    }
  };

  const parseOptInt = (raw: string) => {
    const v = raw.trim();
    return v === "" ? null : Number(v);
  };

  const save = async () => {
    if (!hy2On && !tuicOn) {
      toast.push(t("singbox.stackRequired"), "error");
      return;
    }
    if (!certPath.trim() || !keyPath.trim()) {
      toast.push(t("singbox.tlsRequired"), "error");
      return;
    }
    setBusy(true);
    try {
      const body: Partial<NodeSingBoxConfig> = {
        certificate_path: certPath.trim(),
        key_path: keyPath.trim(),
        sni: sni.trim() || node.address,
        hysteria2_enabled: hy2On,
        hysteria2_port: hy2On ? Number(hy2Port) : null,
        hysteria2_up_mbps: hy2On ? parseOptInt(hy2Up) : null,
        hysteria2_down_mbps: hy2On ? parseOptInt(hy2Down) : null,
        hysteria2_obfs_password: hy2On && hy2Obfs.trim() ? hy2Obfs.trim() : null,
        tuic_enabled: tuicOn,
        tuic_port: tuicOn ? Number(tuicPort) : null,
        tuic_congestion_control: tuicCc.trim() || "bbr",
      };
      await api.put(`/node/${node.id}/singbox`, body);
      toast.push(t("common.saved"), "success");
      onSaved();
      if (node.status !== "connected") {
        toast.push(t("singbox.nodeOffline"), "info");
      }
    } catch (e: any) {
      toast.push(e?.message || t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  const connected = node.status === "connected";

  return (
    <Card style={{ marginBottom: 12, padding: 16 }}>
      <div className="nx-row" style={{ alignItems: "center", marginBottom: 12, gap: 8 }}>
        <div style={{ fontWeight: 700 }}>{node.name}</div>
        <Pill tone={connected ? "ok" : "warn"}>{node.status}</Pill>
        <span className="nx-faint" style={{ fontSize: 12 }}>{node.address}</span>
      </div>

      <div className="nx-stack" style={{ gap: 10 }}>
        <div className="nx-faint" style={{ fontSize: 12, fontWeight: 600 }}>{t("singbox.tlsTitle")}</div>
        <Field label={t("singbox.certPath")}>
          <Input value={certPath} onChange={(e) => setCertPath(e.target.value)} />
        </Field>
        <Field label={t("singbox.keyPath")}>
          <Input value={keyPath} onChange={(e) => setKeyPath(e.target.value)} />
        </Field>
        <Field label={t("singbox.sni")}>
          <Input value={sni} onChange={(e) => setSni(e.target.value)} placeholder={node.address} />
        </Field>

        <Callout tone="info" title={t("singbox.leTitle")}>
          <div className="nx-stack" style={{ gap: 8 }}>
            <div className="nx-faint" style={{ fontSize: 12 }}>{t("singbox.leHint")}</div>
            <Field label={t("singbox.leDomain")}>
              <Input value={leDomain} onChange={(e) => setLeDomain(e.target.value)} placeholder={t("singbox.sniPlaceholder")} />
            </Field>
            <Field label={t("singbox.leKind")}>
              <select className="nx-input" value={leKind} onChange={(e) => setLeKind(e.target.value)}>
                <option value="auto">{t("singbox.leKindAuto")}</option>
                <option value="domain">{t("singbox.leKindDomain")}</option>
                <option value="ip">{t("singbox.leKindIp")}</option>
              </select>
            </Field>
            <Field label={t("singbox.leEmail")}>
              <Input value={leEmail} onChange={(e) => setLeEmail(e.target.value)} type="email" />
            </Field>
            <Field label={t("singbox.sshPassword")}>
              <Input value={sshPassword} onChange={(e) => setSshPassword(e.target.value)} type="password" />
            </Field>
            <div className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
              <Button size="sm" variant="primary" disabled={leBusy} onClick={issueLe}>
                {t("singbox.leIssue")}
              </Button>
              <Button size="sm" variant="ghost" disabled={leBusy || !node.singbox?.tls_le_domain} onClick={renewLe}>
                {t("singbox.leRenew")}
              </Button>
              <Button size="sm" variant="ghost" disabled={leBusy} onClick={refreshTls}>
                {t("singbox.leRefresh")}
              </Button>
            </div>
            {(tlsStatus || node.singbox?.tls_trusted) && (
              <div className="nx-faint" style={{ fontSize: 12 }}>
                {tlsStatus?.trusted || node.singbox?.tls_trusted
                  ? t("singbox.leTrusted")
                  : t("singbox.leUntrusted")}
                {tlsStatus?.expires_at || node.singbox?.tls_expires_at
                  ? ` · ${tlsStatus?.expires_at || node.singbox?.tls_expires_at}`
                  : ""}
              </div>
            )}
          </div>
        </Callout>

        <div className="nx-row" style={{ gap: 16, marginTop: 8, flexWrap: "wrap" }}>
          <label className="nx-row" style={{ gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={hy2On} onChange={(e) => setHy2On(e.target.checked)} />
            <span>{t("singbox.hy2Enable")}</span>
          </label>
          <label className="nx-row" style={{ gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={tuicOn} onChange={(e) => setTuicOn(e.target.checked)} />
            <span>{t("singbox.tuicEnable")}</span>
          </label>
        </div>

        {hy2On && (
          <div className="nx-row" style={{ gap: 10, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 120 }}>
              <Field label={t("singbox.hy2Port")}>
                <Input value={hy2Port} onChange={(e) => setHy2Port(e.target.value)} type="number" />
              </Field>
            </div>
            <div style={{ flex: 1, minWidth: 100 }}>
              <Field label={t("singbox.hy2Up")}>
                <Input value={hy2Up} onChange={(e) => setHy2Up(e.target.value)} placeholder="Mbps" />
              </Field>
            </div>
            <div style={{ flex: 1, minWidth: 100 }}>
              <Field label={t("singbox.hy2Down")}>
                <Input value={hy2Down} onChange={(e) => setHy2Down(e.target.value)} placeholder="Mbps" />
              </Field>
            </div>
            <div style={{ flex: 2, minWidth: 160 }}>
              <Field label={t("singbox.hy2Obfs")}>
                <Input value={hy2Obfs} onChange={(e) => setHy2Obfs(e.target.value)} />
              </Field>
            </div>
          </div>
        )}

        {tuicOn && (
          <div className="nx-row" style={{ gap: 10, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 120 }}>
              <Field label={t("singbox.tuicPort")}>
                <Input value={tuicPort} onChange={(e) => setTuicPort(e.target.value)} type="number" />
              </Field>
            </div>
            <div style={{ flex: 1, minWidth: 120 }}>
              <Field label={t("singbox.tuicCc")}>
                <Input value={tuicCc} onChange={(e) => setTuicCc(e.target.value)} />
              </Field>
            </div>
          </div>
        )}
      </div>

      <div className="nx-row" style={{ marginTop: 14, gap: 8 }}>
        <div style={{ flex: 1 }} />
        <Button size="sm" variant="ghost" disabled={syncBusy || busy} onClick={forceSync}>
          {t("singbox.forceSync")}
        </Button>
        <Button size="sm" variant="primary" disabled={busy} onClick={save}>
          {t("singbox.saveSync")}
        </Button>
      </div>
    </Card>
  );
};

export const SingBox: FC<{ embedded?: boolean }> = ({ embedded }) => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const { setOpen, requestIntent } = useCopilot();
  const nav = useNavigate();
  const nodes = useFetch<NodeItem[]>(
    () => (admin?.is_sudo ? api.get("/nodes") : Promise.resolve([])),
    [admin?.is_sudo],
  );
  const users = useFetch<{ total: number }>(() => api.get("/users?limit=1"), []);

  const nodeList = (nodes.data || []).filter((n) => n.status !== "disabled");
  const configuredNodes = nodeList.filter(
    (n) => n.singbox?.hysteria2_enabled || n.singbox?.tuic_enabled,
  );
  const hy2Nodes = configuredNodes.filter((n) => n.singbox?.hysteria2_enabled).length;
  const hasUsers = (users.data?.total ?? 0) > 0;

  if (!admin?.is_sudo) {
    return (
      <div>
        <PageHeader title={t("singbox.title")} subtitle={t("singbox.subtitle")} />
        <Callout tone="warn">{t("common.sudoOnly")}</Callout>
      </div>
    );
  }

  return (
    <div>
      {!embedded && (
        <PageHeader
          title={t("singbox.title")}
          subtitle={t("singbox.subtitle")}
          description={t("singbox.description")}
          actions={<Button variant="ghost" onClick={() => setOpen(true)}>✦ {t("copilot.title")}</Button>}
        />
      )}

      {!embedded && (
        <Callout tone="info" title={t("singbox.notXrayTitle")}>
          {t("singbox.notXrayBody")}
        </Callout>
      )}

      <div className="nx-row" style={{ gap: 12, margin: "16px 0" }}>
        <Card style={{ flex: 1, padding: 16 }}>
          <div className="nx-faint" style={{ fontSize: 12 }}>{t("singbox.nodesCount")}</div>
          {nodes.loading ? <SkeletonRows rows={1} cols={1} /> : <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{hy2Nodes}</div>}
        </Card>
        <Card style={{ flex: 1, padding: 16 }}>
          <div className="nx-faint" style={{ fontSize: 12 }}>{t("overview.totalUsers")}</div>
          {users.loading ? <SkeletonRows rows={1} cols={1} /> : <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{users.data?.total ?? "—"}</div>}
        </Card>
      </div>

      {nodeList.length === 0 ? (
        <Callout tone="warn">{t("singbox.noNodes")}</Callout>
      ) : (
        <div>
          <div className="nx-card-title" style={{ marginBottom: 8 }}>{t("singbox.configTitle")}</div>
          <p className="nx-faint" style={{ fontSize: 12, margin: "0 0 12px" }}>{t("singbox.configHint")}</p>
          {configuredNodes.length === 0 && (
            <Callout tone="info" title={t("singbox.setupFirstTitle")}>{t("singbox.setupFirstBody")}</Callout>
          )}
          {nodeList.map((n) => (
            <SingBoxNodeCard key={n.id} node={n} onSaved={() => nodes.reload()} />
          ))}
        </div>
      )}

      <div className="nx-row" style={{ marginTop: 16, gap: 10 }}>
        <Button variant="primary" onClick={() => { requestIntent("add-node"); nav("/servers?tab=nodes"); }}>
          <IcPlus className="nx-ico" /> {t("singbox.addNode")}
        </Button>
        <Button onClick={() => { requestIntent("create-user"); nav("/users"); }}>
          <IcUsers className="nx-ico" /> {t("singbox.addUser")}
        </Button>
      </div>
    </div>
  );
};
