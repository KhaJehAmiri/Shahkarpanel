"use client";

import { FC, useMemo, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { Field, Input, Select, Toggle } from "../ui";
import { JsonCodeEditor } from "../xray/JsonCodeEditor";

function parseJson(raw: string): Record<string, unknown> {
  const t = (raw || "").trim();
  if (!t) return {};
  try {
    const v = JSON.parse(t);
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function stringify(obj: Record<string, unknown>): string {
  if (!Object.keys(obj).length) return "";
  return JSON.stringify(obj, null, 2);
}

type Props = {
  kind: "mux" | "sockopt" | "final_mask";
  value: string;
  onChange: (v: string) => void;
};

export const StructuredHostJsonFields: FC<Props> = ({ kind, value, onChange }) => {
  const { t } = useTranslation();
  const [advanced, setAdvanced] = useState(() => {
    const obj = parseJson(value);
    if (kind === "mux") {
      return !("enabled" in obj || "concurrency" in obj) && !!value.trim();
    }
    if (kind === "sockopt") {
      return !("tcpFastOpen" in obj || "tcpNoDelay" in obj || "mark" in obj) && !!value.trim();
    }
    return !("type" in obj) && !!value.trim();
  });

  const obj = useMemo(() => parseJson(value), [value]);

  const patch = (next: Record<string, unknown>) => onChange(stringify(next));

  const setField = (key: string, val: unknown) => {
    const copy = { ...obj };
    if (val === "" || val === null || val === undefined) delete copy[key];
    else copy[key] = val;
    patch(copy);
  };

  if (advanced) {
    return (
      <div className="sk-stack" style={{ gap: 8 }}>
        <label className="sk-row" style={{ gap: 8, fontSize: 12 }}>
          <Toggle on={advanced} onChange={setAdvanced} />
          {t("infra.hostJsonAdvanced", { defaultValue: "Raw JSON editor" })}
        </label>
        <JsonCodeEditor value={value} onChange={onChange} minLines={6} />
      </div>
    );
  }

  if (kind === "mux") {
    return (
      <div className="sk-stack" style={{ gap: 10 }}>
        <label className="sk-row" style={{ gap: 8, fontSize: 12 }}>
          <Toggle on={advanced} onChange={setAdvanced} />
          {t("infra.hostJsonAdvanced", { defaultValue: "Raw JSON editor" })}
        </label>
        <div className="sk-host-toggle-row">
          <Toggle on={!!obj.enabled} onChange={(v) => setField("enabled", v)} />
          <span className="sk-host-toggle-label">{t("infra.hostMuxEnabled", { defaultValue: "Mux enabled" })}</span>
        </div>
        <Field label={t("infra.hostMuxConcurrency", { defaultValue: "Concurrency" })}>
          <Input
            type="number"
            min="1"
            value={obj.concurrency != null ? String(obj.concurrency) : ""}
            onChange={(e) => setField("concurrency", e.target.value ? parseInt(e.target.value, 10) : undefined)}
            dir="ltr"
          />
        </Field>
        <Field label="xudpConcurrency">
          <Input
            type="number"
            min="0"
            value={obj.xudpConcurrency != null ? String(obj.xudpConcurrency) : ""}
            onChange={(e) => setField("xudpConcurrency", e.target.value ? parseInt(e.target.value, 10) : undefined)}
            dir="ltr"
          />
        </Field>
        <Field label="xudpProxyUDP443">
          <Select
            value={obj.xudpProxyUDP443 != null ? String(obj.xudpProxyUDP443) : ""}
            onChange={(e: ChangeEvent<HTMLSelectElement>) => setField("xudpProxyUDP443", e.target.value || undefined)}
          >
            <option value="">—</option>
            <option value="reject">reject</option>
            <option value="allow">allow</option>
            <option value="skip">skip</option>
          </Select>
        </Field>
      </div>
    );
  }

  if (kind === "sockopt") {
    return (
      <div className="sk-stack" style={{ gap: 10 }}>
        <label className="sk-row" style={{ gap: 8, fontSize: 12 }}>
          <Toggle on={advanced} onChange={setAdvanced} />
          {t("infra.hostJsonAdvanced", { defaultValue: "Raw JSON editor" })}
        </label>
        <div className="sk-host-toggle-row">
          <Toggle on={!!obj.tcpFastOpen} onChange={(v) => setField("tcpFastOpen", v)} />
          <span className="sk-host-toggle-label">tcpFastOpen</span>
        </div>
        <div className="sk-host-toggle-row">
          <Toggle on={obj.tcpNoDelay !== false} onChange={(v) => setField("tcpNoDelay", v)} />
          <span className="sk-host-toggle-label">tcpNoDelay</span>
        </div>
        <Field label="tcpKeepAliveInterval">
          <Input
            type="number"
            min="0"
            value={obj.tcpKeepAliveInterval != null ? String(obj.tcpKeepAliveInterval) : ""}
            onChange={(e) => setField("tcpKeepAliveInterval", e.target.value ? parseInt(e.target.value, 10) : undefined)}
            dir="ltr"
          />
        </Field>
        <Field label="mark">
          <Input
            type="number"
            value={obj.mark != null ? String(obj.mark) : ""}
            onChange={(e) => setField("mark", e.target.value ? parseInt(e.target.value, 10) : undefined)}
            dir="ltr"
          />
        </Field>
        <Field label="domainStrategy">
          <Select
            value={String(obj.domainStrategy || "")}
            onChange={(e: ChangeEvent<HTMLSelectElement>) => setField("domainStrategy", e.target.value || undefined)}
          >
            <option value="">—</option>
            {["AsIs", "UseIP", "UseIPv4", "UseIPv6"].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </Select>
        </Field>
        <Field label="dialerProxy">
          <Input
            value={String(obj.dialerProxy || "")}
            onChange={(e) => setField("dialerProxy", e.target.value || undefined)}
            dir="ltr"
          />
        </Field>
      </div>
    );
  }

  return (
    <div className="sk-stack" style={{ gap: 10 }}>
      <label className="sk-row" style={{ gap: 8, fontSize: 12 }}>
        <Toggle on={advanced} onChange={setAdvanced} />
        {t("infra.hostJsonAdvanced", { defaultValue: "Raw JSON editor" })}
      </label>
      <Field label={t("infra.hostFinalMaskType", { defaultValue: "Mask type" })}>
        <Input
          value={String(obj.type || "")}
          onChange={(e) => setField("type", e.target.value || undefined)}
          placeholder="e.g. xtls-rprx-vision"
          dir="ltr"
        />
      </Field>
      <Field label={t("infra.hostFinalMaskSeed", { defaultValue: "Seed / extra keys" })} hint={t("infra.hostFinalMaskHint", { defaultValue: "Use raw JSON for complex masks" })}>
        <Input
          value={String(obj.seed || obj.password || "")}
          onChange={(e) => {
            const copy = { ...obj };
            if (e.target.value) copy.seed = e.target.value;
            else delete copy.seed;
            patch(copy);
          }}
          dir="ltr"
        />
      </Field>
    </div>
  );
};
