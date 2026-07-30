import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { NodeItem } from "../api/types";
import { JsonCodeEditor } from "./xray/JsonCodeEditor";
import { Button, Callout, Field, Modal, useToast } from "./ui";

export const NodeXrayOverrideModal: FC<{
  node: NodeItem;
  onClose: () => void;
  onDone: () => void;
}> = ({ node, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [text, setText] = useState("{}");
  const [preview, setPreview] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const data = await api.get<Record<string, unknown>>(`/node/${node.id}/xray-config/override`);
        if (!alive) return;
        setText(JSON.stringify(data || {}, null, 2));
      } catch (e: unknown) {
        if (alive) toast.push(e instanceof Error ? e.message : t("common.error"), "error");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [node.id, t, toast]);

  const loadPreview = async () => {
    try {
      const cfg = await api.get<Record<string, unknown>>(`/node/${node.id}/xray-config`);
      setPreview(JSON.stringify(cfg, null, 2));
      setShowPreview(true);
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    }
  };

  const save = async () => {
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(text || "{}");
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
        throw new Error(t("infra.xrayOverrideInvalid"));
      }
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("infra.xrayOverrideInvalid"), "error");
      return;
    }
    setBusy(true);
    try {
      await api.put(`/node/${node.id}/xray-config/override`, payload);
      toast.push(t("infra.xrayOverrideSaved"), "success");
      onDone();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    if (!confirm(t("infra.xrayOverrideClearConfirm"))) return;
    setBusy(true);
    try {
      await api.put(`/node/${node.id}/xray-config/override`, {});
      toast.push(t("infra.xrayOverrideCleared"), "success");
      onDone();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      title={`${t("infra.xrayConfigOverride")} — ${node.name}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="ghost" disabled={busy || loading} onClick={() => void clear()}>{t("common.clear")}</Button>
          <Button variant="primary" disabled={busy || loading} onClick={() => void save()}>{t("common.save")}</Button>
        </>
      }
    >
      <div className="sk-stack">
        <Callout tone="info">{t("infra.xrayOverrideHint")}</Callout>
        <Field label={t("infra.xrayOverrideFragment")}>
          {loading ? t("common.loading") : (
            <JsonCodeEditor value={text} onChange={setText} minLines={18} />
          )}
        </Field>
        <div className="sk-row" style={{ gap: 8 }}>
          <Button size="sm" variant="ghost" onClick={() => void loadPreview()}>{t("infra.xrayOverridePreview")}</Button>
        </div>
        {showPreview && preview && (
          <Field label={t("infra.xrayOverrideEffective")}>
            <pre className="sk-mono" style={{ maxHeight: 280, overflow: "auto", margin: 0, padding: 12, background: "var(--sk-surface-2)", borderRadius: 8 }}>
              {preview}
            </pre>
          </Field>
        )}
      </div>
    </Modal>
  );
};
