import { ChangeEvent, FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  defaultOutboundForm,
  finalizeOutboundFromForm,
  outboundToForm,
  validateOutboundTag,
  type OutboundForm,
} from "../../lib/outboundHelpers";
import { OUTBOUND_LINK_PLACEHOLDER, parseOutboundShareLink } from "../../lib/outboundLinkParser";
import { Button, Input, Modal, Tabs, useToast } from "../ui";
import { IcPlus } from "../icons";
import { JsonCodeEditor } from "./JsonCodeEditor";
import { OutboundFormFields } from "./OutboundFormFields";

export const OutboundModal: FC<{
  outbounds: Record<string, unknown>[];
  editIdx: number | null;
  preset: OutboundForm | null;
  onClose: () => void;
  onApply: (payload: {
    outbound: Record<string, unknown>;
    mode: "create" | "update";
    originalTag?: string;
  }) => void | Promise<void>;
}> = ({ outbounds, editIdx, preset, onClose, onApply }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const existing = editIdx != null ? outbounds[editIdx] : null;
  const isNew = editIdx == null;

  const [tab, setTab] = useState<"form" | "json">("form");
  const [f, setF] = useState<OutboundForm>(
    existing ? outboundToForm(existing) : preset ?? defaultOutboundForm(),
  );
  const [jsonText, setJsonText] = useState(() =>
    JSON.stringify(existing ?? (preset ? finalizeOutboundFromForm(preset) : {}), null, 2),
  );
  const [jsonErr, setJsonErr] = useState<string | null>(null);
  const [importLink, setImportLink] = useState("");
  const [importedRaw, setImportedRaw] = useState<Record<string, unknown> | undefined>();

  const rawRef = useMemo(() => {
    if (existing) return JSON.parse(JSON.stringify(existing)) as Record<string, unknown>;
    return importedRaw;
  }, [existing, importedRaw]);

  useEffect(() => {
    if (tab === "json") {
      try {
        const built = finalizeOutboundFromForm(f, rawRef);
        setJsonText(JSON.stringify(built, null, 2));
        setJsonErr(null);
      } catch {
        /* keep current json */
      }
    }
  }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

  const syncFormToJson = () => {
    const built = finalizeOutboundFromForm(f, rawRef);
    setJsonText(JSON.stringify(built, null, 2));
    setJsonErr(null);
  };

  const uniqueTag = (tag: string): string => {
    const base = tag.trim() || "outbound";
    if (editIdx != null && String(outbounds[editIdx]?.tag) === base) return base;
    if (!outbounds.some((o, i) => i !== editIdx && String(o.tag) === base)) return base;
    let n = 2;
    while (outbounds.some((o, i) => i !== editIdx && String(o.tag) === `${base}-${n}`)) n++;
    return `${base}-${n}`;
  };

  const handleImport = () => {
    const link = importLink.trim();
    if (!link) return;
    const ob = parseOutboundShareLink(link);
    if (!ob) {
      toast.push(t("outbounds.importFailed"), "error");
      return;
    }
    ob.tag = uniqueTag(String(ob.tag || ""));
    const raw = JSON.parse(JSON.stringify(ob)) as Record<string, unknown>;
    setImportedRaw(raw);
    setF(outboundToForm(raw));
    setJsonText(JSON.stringify(raw, null, 2));
    setJsonErr(null);
    setTab("form");
    toast.push(t("outbounds.imported"), "success");
  };

  const parseJson = (): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(jsonText) as Record<string, unknown>;
      setJsonErr(null);
      return parsed;
    } catch (e: unknown) {
      setJsonErr(e instanceof Error ? e.message : "Invalid JSON");
      return null;
    }
  };

  const submit = async () => {
    let ob: Record<string, unknown>;
    if (tab === "json") {
      const parsed = parseJson();
      if (!parsed) {
        toast.push(t("outbounds.invalidJson"), "error");
        return;
      }
      ob = parsed;
      const tagErr = validateOutboundTag(String(ob.tag || ""), outbounds, editIdx);
      if (tagErr) {
        toast.push(t(`outbounds.tagError.${tagErr}`), "error");
        return;
      }
    } else {
      const tagErr = validateOutboundTag(f.tag, outbounds, editIdx);
      if (tagErr) {
        toast.push(t(`outbounds.tagError.${tagErr}`), "error");
        return;
      }
      ob = finalizeOutboundFromForm(f, rawRef);
    }

    if (editIdx != null) {
      const originalTag = String(outbounds[editIdx]?.tag || ob.tag || "");
      await onApply({ outbound: ob, mode: "update", originalTag });
    } else {
      await onApply({ outbound: ob, mode: "create" });
    }
  };

  const modalTitle = isNew ? (
    <span className="sk-modal-title-plus"><IcPlus className="sk-ico" /> {t("xray.tabOutbounds")}</span>
  ) : (
    t("common.edit")
  );

  return (
    <Modal
      open
      formWide
      wide
      title={modalTitle}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.close")}</Button>
          <Button variant="primary" disabled={tab === "form" && !f.tag.trim()} onClick={submit}>
            {isNew ? t("common.create") : t("common.save")}
          </Button>
        </>
      }
    >
      <div className="sk-outbound-modal">
        <Tabs
          tabs={[
            { id: "form", label: t("outbounds.tabForm") },
            { id: "json", label: t("outbounds.tabJson") },
          ]}
          active={tab}
          onChange={(id) => {
            if (id === "json" && tab === "form") syncFormToJson();
            if (id === "form" && tab === "json") {
              const parsed = parseJson();
              if (parsed) setF(outboundToForm(parsed));
            }
            setTab(id as "form" | "json");
          }}
        />

        {tab === "json" ? (
          <div className="sk-outbound-json-tab">
            <div className="sk-outbound-import">
              <Input
                value={importLink}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setImportLink(e.target.value)}
                placeholder={OUTBOUND_LINK_PLACEHOLDER}
                dir="ltr"
                className="sk-mono"
                onKeyDown={(e) => { if (e.key === "Enter") handleImport(); }}
              />
              <Button variant="primary" onClick={handleImport} disabled={!importLink.trim()}>
                {t("outbounds.importLink")}
              </Button>
            </div>
            <div className="sk-outbound-json">
              <JsonCodeEditor
                value={jsonText}
                onChange={(v) => { setJsonText(v); setJsonErr(null); }}
              />
              {jsonErr && <div className="sk-outbound-json-err">{jsonErr}</div>}
            </div>
          </div>
        ) : (
          <div className="sk-outbound-modal-body">
            <OutboundFormFields f={f} setF={setF} chainTags={outbounds.map((o) => String(o.tag))} />
          </div>
        )}
      </div>
    </Modal>
  );
};
