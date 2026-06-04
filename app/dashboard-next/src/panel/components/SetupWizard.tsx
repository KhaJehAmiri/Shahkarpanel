import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import { Button, Field, Input, Modal } from "./ui";

const TOGGLEABLE = [
  "tenants",
  "white_label",
  "node_provisioning",
  "tunneling",
  "billing",
  "smart_routing",
];

export const SetupWizard: FC = () => {
  const { t } = useTranslation();
  const { admin, refreshFlags } = useApp();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("NexusPanel");
  const [features, setFeatures] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!admin?.is_sudo) return;
    api.get<{ completed: boolean; show_wizard: boolean }>("/setup/status")
      .then((s) => setOpen(s.show_wizard))
      .catch(() => setOpen(false));
  }, [admin?.is_sudo]);

  const submit = async () => {
    setBusy(true);
    setErr("");
    try {
      const enable_features = TOGGLEABLE.filter((f) => features[f]);
      await api.post("/setup/", {
        panel_title: title,
        enable_features,
      });
      setOpen(false);
      await refreshFlags();
    } catch (e: any) {
      setErr(e.message || t("common.error"));
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <Modal
      open
      title={t("setup.title")}
      onClose={() => setOpen(false)}
      footer={
        <>
          <Button variant="ghost" onClick={() => setOpen(false)}>{t("setup.skip")}</Button>
          <Button variant="primary" disabled={busy} onClick={submit}>{t("setup.finish")}</Button>
        </>
      }
    >
      <div className="nx-stack">
        <p className="nx-faint" style={{ fontSize: 13 }}>{t("setup.description")}</p>
        <Field label={t("setup.panelTitle")}>
          <Input value={title} onChange={(e: any) => setTitle(e.target.value)} />
        </Field>
        <div className="nx-stack" style={{ gap: 8 }}>
          <div className="nx-faint" style={{ fontSize: 12 }}>{t("setup.features")}</div>
          {TOGGLEABLE.map((f) => (
            <label key={f} className="nx-row" style={{ gap: 8, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={!!features[f]}
                onChange={(e) => setFeatures((prev) => ({ ...prev, [f]: e.target.checked }))}
              />
              <span>{f}</span>
            </label>
          ))}
        </div>
        {err ? <div className="nx-callout danger">{err}</div> : null}
      </div>
    </Modal>
  );
};
