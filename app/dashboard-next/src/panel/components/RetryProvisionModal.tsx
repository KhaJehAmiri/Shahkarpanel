import React, { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { NodeItem } from "../api/types";
import { Button, Callout, Field, Input, Modal, useToast } from "./ui";

type RetryResult = {
  status: string;
  job_id?: string;
  node_id?: number;
  detail?: string;
};

/** Re-run SSH provisioning for a failed node without deleting it. */
export const RetryProvisionModal: FC<{
  node: NodeItem;
  onClose: () => void;
  onDone: () => void;
}> = ({ node, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const host = (node.address || "").split(":")[0];
  const [f, setF] = useState({
    username: "root",
    ssh_port: "22",
    password: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const upd = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<RetryResult>(`/nodes/${node.id}/retry`, {
        username: f.username.trim() || "root",
        ssh_port: parseInt(f.ssh_port, 10) || 22,
        password: f.password,
        refresh_agent: false,
      });
      if (res.status === "started") {
        toast.push(t("infra.provisionRetryQueued"), "success");
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

  return (
    <Modal
      open
      title={t("infra.provisionRetryTitle", { name: node.name })}
      onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose} disabled={busy}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !f.password} onClick={submit}>
          {busy ? t("infra.provisionRunning") : t("infra.provisionRetry")}
        </Button>
      </>}
    >
      <div className="nx-stack" style={{ gap: 12 }}>
        <Callout tone="info" className="compact">{t("infra.provisionRetryHint")}</Callout>
        <Field label={t("infra.serverIp")}>
          <Input value={host} readOnly className="nx-mono" />
        </Field>
        <div className="nx-form-grid">
          <Field label={t("infra.sshUser")}>
            <Input value={f.username} onChange={upd("username")} placeholder="root" />
          </Field>
          <Field label={t("infra.sshPort")}>
            <Input type="number" value={f.ssh_port} onChange={upd("ssh_port")} />
          </Field>
          <div className="span-2">
            <Field label={t("infra.sshPassword")} hint={t("infra.sshPasswordHint")}>
              <Input
                type="password"
                value={f.password}
                onChange={upd("password")}
                autoComplete="new-password"
                autoFocus
              />
            </Field>
          </div>
        </div>
        {error && <Callout tone="danger" className="compact">{error}</Callout>}
      </div>
    </Modal>
  );
};
