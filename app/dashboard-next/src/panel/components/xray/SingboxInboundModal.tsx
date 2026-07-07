import { ChangeEvent, FC, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../../api/client";
import { NodeItem } from "../../api/types";
import { useFetch } from "../../lib/useFetch";
import { Button, Callout, Field, Input, Modal, Select, useToast } from "../ui";

type PresetMeta = {
  label?: string;
  note?: string;
  deploy?: string;
  protocol?: string;
  default_port?: number;
  default_congestion_control?: string;
};

type SingboxInboundEntry = {
  id: string;
  preset_id: string;
  node_id: number;
  node_name: string;
  protocol: string;
  tag: string;
  port: number;
  transport: string;
  security: string;
  congestion_control?: string;
  tls_trusted?: boolean;
  node_status?: string;
};

export const SingboxInboundModal: FC<{
  presetId: "tuic-inbound" | "anytls-inbound";
  editEntry?: SingboxInboundEntry | null;
  onClose: () => void;
  onApplied: () => void;
}> = ({ presetId, editEntry, onClose, onApplied }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const presets = useFetch<{ presets: Record<string, PresetMeta> }>(
    () => api.get("/core/inbounds/presets"),
    [],
  );
  const nodes = useFetch<NodeItem[]>(() => api.get("/nodes"), []);

  const meta = presets.data?.presets?.[presetId];
  const isTuic = presetId === "tuic-inbound";

  const connectedNodes = useMemo(
    () => (nodes.data || []).filter((n) => n.status === "connected" && n.core_kind !== "wireguard"),
    [nodes.data],
  );

  const [nodeId, setNodeId] = useState("");
  const [port, setPort] = useState(String(meta?.default_port ?? (isTuic ? 44334 : 44335)));
  const [cc, setCc] = useState(meta?.default_congestion_control || "bbr");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (editEntry) {
      setNodeId(String(editEntry.node_id));
      setPort(String(editEntry.port));
      if (editEntry.congestion_control) setCc(editEntry.congestion_control);
      return;
    }
    setPort(String(meta?.default_port ?? (isTuic ? 44334 : 44335)));
    setCc(meta?.default_congestion_control || "bbr");
    if (connectedNodes.length === 1) setNodeId(String(connectedNodes[0].id));
  }, [editEntry, meta, isTuic, connectedNodes]);

  const apply = async () => {
    const nid = parseInt(nodeId, 10);
    const p = parseInt(port, 10);
    if (!nid || Number.isNaN(p)) {
      toast.push(t("singboxInbound.invalid"), "error");
      return;
    }
    setBusy(true);
    try {
      await api.post(`/core/inbounds/presets/${encodeURIComponent(presetId)}/apply`, {
        node_id: nid,
        port: p,
        tuic_congestion_control: isTuic ? cc.trim() || "bbr" : undefined,
      });
      toast.push(t("singboxInbound.applied", { protocol: isTuic ? "TUIC" : "AnyTLS" }), "success");
      onApplied();
      onClose();
    } catch (e: unknown) {
      toast.push(e instanceof ApiError ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  const selectedNode = connectedNodes.find((n) => String(n.id) === nodeId);

  return (
    <Modal
      open
      title={meta?.label || presetId}
      onClose={onClose}
      footer={
        <div className="nx-row" style={{ gap: 8, justifyContent: "flex-end", width: "100%" }}>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onClick={apply} disabled={busy || !nodeId}>
            {busy ? t("common.loading") : t("singboxInbound.enable")}
          </Button>
        </div>
      }
    >
      <div className="nx-stack" style={{ gap: 14 }}>
        <Callout tone="info">{t("singboxInbound.about")}</Callout>
        {meta?.note && <Muted>{meta.note}</Muted>}

        <Field label={t("singboxInbound.node")}>
          <Select
            value={nodeId}
            onChange={(e: ChangeEvent<HTMLSelectElement>) => setNodeId(e.target.value)}
            disabled={!!editEntry}
          >
            <option value="">{t("singboxInbound.pickNode")}</option>
            {connectedNodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.name} · {n.address} (#{n.id})
              </option>
            ))}
          </Select>
        </Field>

        {!connectedNodes.length && (
          <Callout tone="warn">{t("singboxInbound.noNodes")}</Callout>
        )}

        <Field label={t("singboxInbound.port")}>
          <Input value={port} onChange={(e) => setPort(e.target.value)} type="number" dir="ltr" className="nx-mono" />
        </Field>

        {isTuic && (
          <Field label={t("singbox.tuicCc")}>
            <Input value={cc} onChange={(e) => setCc(e.target.value)} dir="ltr" className="nx-mono" />
          </Field>
        )}

        {selectedNode && !selectedNode.singbox?.tls_trusted && (
          <Callout tone="warn" title={t("singboxInbound.tlsWarnTitle")}>
            {t("singboxInbound.tlsWarnBody")}{" "}
            <Link to={`/servers?tab=h2`}>{t("singboxInbound.openTls")}</Link>
          </Callout>
        )}
      </div>
    </Modal>
  );
};

const Muted: FC<{ children: ReactNode }> = ({ children }) => (
  <div style={{ fontSize: 13, color: "var(--nx-muted)" }}>{children}</div>
);

export type { SingboxInboundEntry };
