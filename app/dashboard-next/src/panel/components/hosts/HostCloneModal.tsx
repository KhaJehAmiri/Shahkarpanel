"use client";

import { FC, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { Button, Field, Modal, Select, useToast } from "../ui";
import { hostTagLabel } from "./types";

type Props = {
  inboundTags: string[];
  onClose: () => void;
  onDone: () => void;
};

export const HostCloneModal: FC<Props> = ({ inboundTags, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [sourceTag, setSourceTag] = useState(inboundTags[0] || "");
  const [targets, setTargets] = useState<string[]>([]);
  const [mode, setMode] = useState<"append" | "replace">("append");
  const [busy, setBusy] = useState(false);

  const toggleTarget = (tag: string) => {
    setTargets((cur) => (cur.includes(tag) ? cur.filter((x) => x !== tag) : [...cur, tag]));
  };

  const submit = async () => {
    if (!sourceTag || !targets.length) {
      toast.push(t("infra.hostClonePickTargets", { defaultValue: "Select source and at least one target inbound" }), "error");
      return;
    }
    setBusy(true);
    try {
      const res = await api.post<{ cloned: number }>("/hosts/clone", {
        source_tag: sourceTag,
        target_tags: targets.filter((tg) => tg !== sourceTag),
        mode,
      });
      toast.push(t("infra.hostCloneDone", { defaultValue: "Cloned {{n}} host row(s)", n: res.cloned }), "success");
      onDone();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      title={t("infra.hostCloneTemplate", { defaultValue: "Clone hosts" })}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={busy} onClick={submit}>{t("common.apply", { defaultValue: "Apply" })}</Button>
        </>
      }
    >
      <div className="sk-stack" style={{ gap: 14 }}>
        <Field label={t("infra.hostCloneSource", { defaultValue: "Source inbound" })}>
          <Select value={sourceTag} onChange={(e: ChangeEvent<HTMLSelectElement>) => setSourceTag(e.target.value)}>
            {inboundTags.map((tg) => <option key={tg} value={tg}>{hostTagLabel(tg)}</option>)}
          </Select>
        </Field>
        <Field label={t("infra.hostCloneTargets", { defaultValue: "Target inbounds" })}>
          <div className="sk-row" style={{ gap: 6, flexWrap: "wrap" }}>
            {inboundTags.filter((tg) => tg !== sourceTag).map((tg) => (
              <button
                key={tg}
                type="button"
                className={`sk-btn sm ${targets.includes(tg) ? "primary" : ""}`}
                onClick={() => toggleTarget(tg)}
              >
                {targets.includes(tg) ? "✓ " : ""}{hostTagLabel(tg)}
              </button>
            ))}
          </div>
        </Field>
        <Field label={t("infra.hostCloneMode", { defaultValue: "Mode" })}>
          <Select value={mode} onChange={(e: ChangeEvent<HTMLSelectElement>) => setMode(e.target.value as "append" | "replace")}>
            <option value="append">{t("infra.hostCloneAppend", { defaultValue: "Append to existing" })}</option>
            <option value="replace">{t("infra.hostCloneReplace", { defaultValue: "Replace targets" })}</option>
          </Select>
        </Field>
      </div>
    </Modal>
  );
};
