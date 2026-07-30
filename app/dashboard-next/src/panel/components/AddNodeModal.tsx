import React, { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { Button, Callout, Field, Input, Modal, Select, useToast } from "./ui";
import {
  NodeServicesForm,
  buildProvisionServicesPayload,
  defaultNodeServices,
  type NodeServicesState,
} from "./NodeServicesForm";
import "./add-node-modal.css";

type ProvisionResult = {
  status: string;
  job_id?: string;
  node_id?: number;
  detail?: string;
  install_command?: string;
};

export type AddNodePreset = {
  coreKind?: "xray" | "wireguard";
};

/** SSH provision — closes immediately; progress shows on the nodes list. */
export const AddNodeModal: FC<{
  onClose: () => void;
  onDone: () => void;
  preset?: AddNodePreset;
}> = ({ onClose, onDone, preset }) => {
  const { t } = useTranslation();
  const { isEnabled } = useApp();
  const toast = useToast();
  const canProvision = isEnabled("node_provisioning");
  const regions = useFetch<{ regions: { code: string; flag: string; name: string }[] }>(
    () => api.get("/nodes/region-presets"),
    [],
  );
  const [f, setF] = useState({
    name: "",
    address: "",
    region: "",
    core_kind: preset?.coreKind || "xray",
    ssh_port: "22",
    username: "root",
    password: "",
    role: "direct",
  });
  const [services, setServices] = useState<NodeServicesState>(
    defaultNodeServices(preset?.coreKind || "xray"),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualCmd, setManualCmd] = useState<string | null>(null);
  const upd = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value });

  const patchServices = (patch: Partial<NodeServicesState>) => {
    setServices((prev) => ({ ...prev, ...patch }));
  };

  const onCoreKindChange = (kind: "xray" | "wireguard") => {
    setF({ ...f, core_kind: kind });
    setServices(defaultNodeServices(kind));
  };

  const wantsQuic = services.enable_hysteria2 || services.enable_tuic;
  const leOk = services.tls_mode !== "letsencrypt"
    || (!!services.le_email.trim() && !!(services.le_target.trim() || f.address.trim()));

  const valid = !!f.name && !!f.address && !!f.password
    && (f.core_kind !== "wireguard" || services.enable_plain_wg || services.enable_awg)
    && (!wantsQuic || services.tls_mode === "self_signed" || leOk);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<ProvisionResult>("/nodes/provision", {
        name: f.name.trim(),
        host: f.address.trim(),
        ssh_port: parseInt(f.ssh_port, 10),
        username: f.username.trim() || "root",
        password: f.password,
        role: f.role,
        core_kind: f.core_kind,
        region: f.region.trim() || null,
        run: true,
        ...buildProvisionServicesPayload({ ...services, core_kind: f.core_kind }, f.address),
      });
      if (res.status === "started") {
        toast.push(t("infra.provisionQueued"), "success");
        onDone();
      }
    } catch (e: any) {
      const msg = e.message || t("infra.provisionFailed");
      setError(msg);
      toast.push(msg, "error");
    } finally {
      setBusy(false);
    }
  };

  const fetchManual = async () => {
    if (!f.name.trim()) {
      toast.push(t("common.name"), "error");
      return;
    }
    setBusy(true);
    try {
      const q = new URLSearchParams({
        name: f.name.trim(),
        role: f.role,
        core_kind: f.core_kind,
      });
      if (f.region.trim()) q.set("region", f.region.trim());
      const res = await api.get<ProvisionResult>(`/nodes/install-command?${q}`);
      setManualCmd(res.install_command || "");
    } catch (e: any) {
      toast.push(e?.message || t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  if (!canProvision) {
    return (
      <Modal open title={t("infra.addNode")} onClose={onClose}
        footer={<>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={busy || !f.name.trim()} onClick={fetchManual}>
            {t("infra.manualInstallCmd")}
          </Button>
        </>}>
        <div className="sk-stack" style={{ gap: 12 }}>
          <Callout tone="warn">{t("infra.provisionDisabledHint")}</Callout>
          <Field label={t("common.name")}>
            <Input value={f.name} onChange={upd("name")} placeholder="de-node-1" />
          </Field>
          {manualCmd && (
            <Callout tone="info">
              <pre style={{ whiteSpace: "pre-wrap", fontSize: 11, margin: 0 }}>{manualCmd}</pre>
            </Callout>
          )}
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      open
      formWide
      className="sk-add-node-shell"
      title={t("infra.addNode")}
      onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose} disabled={busy}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !valid} onClick={submit}>
          {busy ? t("infra.provisionRunning") : t("infra.provisionInstall")}
        </Button>
      </>}
    >
      <div className="sk-add-node-body">
        <Callout tone="info" className="compact">{t("infra.autoHint")}</Callout>

        <section className="sk-add-node-section" aria-labelledby="add-node-core">
          <h3 className="sk-add-node-section-title" id="add-node-core">{t("infra.addNodeSectionCore")}</h3>
          <div className="sk-form-grid">
            <Field label={t("infra.coreKind")}>
              <Select value={f.core_kind} onChange={(e: React.ChangeEvent<HTMLSelectElement>) => onCoreKindChange(e.target.value as "xray" | "wireguard")}>
                <option value="xray">Xray (v2ray)</option>
                <option value="wireguard">WireGuard</option>
              </Select>
            </Field>
            <Field label={t("infra.role")}>
              <Select value={f.role} onChange={upd("role")}>
                <option value="direct">direct</option>
                <option value="relay">relay</option>
                <option value="exit">exit</option>
              </Select>
            </Field>
          </div>
        </section>

        <section className="sk-add-node-section" aria-labelledby="add-node-server">
          <h3 className="sk-add-node-section-title" id="add-node-server">{t("infra.addNodeSectionServer")}</h3>
          <div className="sk-form-grid">
            <Field label={t("common.name")}>
              <Input value={f.name} onChange={upd("name")} autoFocus placeholder="de-node-1" />
            </Field>
            <Field label={t("infra.serverIp")}>
              <Input value={f.address} onChange={upd("address")} placeholder="1.2.3.4" />
            </Field>
            <div className="span-2">
              <Field label={t("infra.regionPreset")}>
                <Select value={f.region} onChange={upd("region")}>
                  <option value="">—</option>
                  {(regions.data?.regions || []).map((r) => (
                    <option key={r.code} value={r.code}>
                      {r.flag} {r.name} ({r.code})
                    </option>
                  ))}
                  <option value="custom">🌐 custom</option>
                </Select>
              </Field>
            </div>
          </div>
        </section>

        <section className="sk-add-node-section" aria-labelledby="add-node-ssh">
          <h3 className="sk-add-node-section-title" id="add-node-ssh">{t("infra.addNodeSectionSsh")}</h3>
          <div className="sk-form-grid">
            <Field label={t("infra.sshUser")}>
              <Input value={f.username} onChange={upd("username")} placeholder="root" />
            </Field>
            <Field label={t("infra.sshPort")}>
              <Input type="number" value={f.ssh_port} onChange={upd("ssh_port")} />
            </Field>
            <div className="span-2">
              <Field label={t("infra.sshPassword")} hint={t("infra.sshPasswordHint")}>
                <Input type="password" value={f.password} onChange={upd("password")} autoComplete="new-password" />
              </Field>
            </div>
          </div>
        </section>

        <NodeServicesForm
          state={{ ...services, core_kind: f.core_kind }}
          setState={patchServices}
          serverAddress={f.address}
          region={f.region}
        />

        {error && <Callout tone="danger" className="compact">{error}</Callout>}
      </div>
    </Modal>
  );
};
