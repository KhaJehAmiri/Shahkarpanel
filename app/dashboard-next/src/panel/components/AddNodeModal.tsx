import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import { isIranNode } from "../lib/region";
import { Button, Callout, Field, Input, Modal, Select, useToast } from "./ui";

type ProvisionResult = {
  status: string;
  job_id?: string;
  node_id?: number;
  detail?: string;
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
  const [f, setF] = useState({
    name: "",
    address: "",
    region: "",
    core_kind: preset?.coreKind || "xray",
    ssh_port: "22",
    username: "root",
    password: "",
    role: "direct",
    makeTunnel: false,
    tunnelPort: "443",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const upd = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<ProvisionResult>("/nodes/provision", {
        name: f.name.trim(),
        host: f.address.trim(),
        ssh_port: parseInt(f.ssh_port),
        username: f.username.trim() || "root",
        password: f.password,
        role: f.role,
        core_kind: f.core_kind,
        region: f.region.trim() || null,
        run: true,
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

  const valid = !!f.name && !!f.address && !!f.password;
  const showTunnel = isEnabled("tunneling") && f.core_kind === "xray";

  if (!canProvision) {
    return (
      <Modal open title={t("infra.addNode")} onClose={onClose}
        footer={<Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>}>
        <Callout tone="warn">{t("common.disabledFeature")}</Callout>
      </Modal>
    );
  }

  return (
    <Modal open formWide title={t("infra.addNode")} onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose} disabled={busy}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !valid} onClick={submit}>
          {busy ? t("infra.provisionRunning") : t("infra.provisionInstall")}
        </Button>
      </>}>
      <div className="nx-stack" style={{ gap: 14 }}>
        <Callout tone="info" className="compact">{t("infra.autoHint")}</Callout>

        <div className="nx-form-grid">
          <Field label={t("infra.coreKind")}>
            <Select value={f.core_kind} onChange={upd("core_kind")}>
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

          <Field label={t("common.name")}>
            <Input value={f.name} onChange={upd("name")} autoFocus placeholder="de-node-1" />
          </Field>
          <Field label={t("infra.serverIp")}>
            <Input value={f.address} onChange={upd("address")} placeholder="1.2.3.4" />
          </Field>

          <Field label={t("infra.regionPreset")}>
            <Select value={f.region} onChange={upd("region")}>
              <option value="">—</option>
              {["ir", "eu", "us", "ae", "tr"].map((r) => <option key={r} value={r}>{r}</option>)}
              <option value="custom">custom</option>
            </Select>
          </Field>
          <Field label={t("infra.sshUser")}>
            <Input value={f.username} onChange={upd("username")} placeholder="root" />
          </Field>

          <Field label={t("infra.sshPort")}>
            <Input type="number" value={f.ssh_port} onChange={upd("ssh_port")} />
          </Field>
          <Field label={t("infra.sshPassword")} hint={t("infra.sshPasswordHint")}>
            <Input type="password" value={f.password} onChange={upd("password")} autoComplete="new-password" />
          </Field>

          {showTunnel && (
            <div className="span-2 nx-stack" style={{ gap: 8 }}>
              <label className="nx-row" style={{ gap: 8, fontSize: 13 }}>
                <input type="checkbox" checked={f.makeTunnel} onChange={(e) => setF({ ...f, makeTunnel: e.target.checked })} />
                {t("infra.makeTunnelWithPanel")}
              </label>
              {f.makeTunnel && (
                <div className="nx-form-grid" style={{ marginTop: 2 }}>
                  <div className="span-2">
                    <Callout tone="info" className="compact">
                      {isIranNode(f.region) ? t("infra.makeTunnelHintIran") : t("infra.makeTunnelHintForeign")}
                    </Callout>
                  </div>
                  <Field label={t("infra.tunnelPort")} hint={t("infra.tunnelPortHint")}>
                    <Input type="number" value={f.tunnelPort} onChange={upd("tunnelPort")} />
                  </Field>
                </div>
              )}
            </div>
          )}
        </div>

        {error && <Callout tone="danger" className="compact">{error}</Callout>}
      </div>
    </Modal>
  );
};
