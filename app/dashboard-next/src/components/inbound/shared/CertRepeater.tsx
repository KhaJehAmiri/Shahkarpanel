"use client";

import { useTranslation } from "react-i18next";
import { CollapsibleSection } from "./CollapsibleSection";
import { FieldRow, inputClass, btnSecondaryClass, btnDangerClass } from "./FieldRow";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { TLSCertificate } from "../types";

interface TlsCertSuggestion {
  id: string;
  label: string;
  certificateFile: string;
  keyFile: string;
  serverName?: string;
}

interface CertRepeaterProps {
  certificates: TLSCertificate[];
  onChange: (certs: TLSCertificate[]) => void;
  error?: string;
  suggestions?: TlsCertSuggestion[];
  onApplySuggestion?: (s: TlsCertSuggestion) => void;
}

const emptyCert = (): TLSCertificate => ({
  usage: "encipherment",
  certificateFile: "",
  keyFile: "",
  certificate: [],
  key: [],
  ocspStapling: 0,
  buildChain: false,
  oneTimeLoading: false,
  pemMode: false,
});

export function CertRepeater({
  certificates,
  onChange,
  error,
  suggestions = [],
  onApplySuggestion,
}: CertRepeaterProps) {
  const { t } = useTranslation();

  const update = (i: number, patch: Partial<TLSCertificate>) => {
    const next = [...certificates];
    next[i] = { ...next[i], ...patch };
    onChange(next);
  };

  const applyToCert = (i: number, suggestion: TlsCertSuggestion) => {
    update(i, {
      certificateFile: suggestion.certificateFile,
      keyFile: suggestion.keyFile,
      pemMode: false,
      certificate: [],
      key: [],
    });
    onApplySuggestion?.(suggestion);
  };

  return (
    <CollapsibleSection
      title={t("inbounds.digitalCert")}
      defaultOpen
      action={
        <button type="button" className={btnSecondaryClass} onClick={() => onChange([...certificates, emptyCert()])}>
          + {t("inbounds.tlsAddCert")}
        </button>
      }
    >
      {error && <p className="mb-2 text-xs text-red-400">{error}</p>}
      {certificates.length === 0 && (
        <p className="text-xs text-[var(--text-hint)]">{t("inbounds.tlsCertRequired")}</p>
      )}
      {certificates.map((cert, i) => (
        <div key={i} className="mb-3 rounded-lg border border-[var(--border)] p-3">
          {suggestions.length > 0 && (
            <FieldRow label={t("inbounds.tlsLoadCert")}>
              <Select
                value=""
                onValueChange={(id) => {
                  const s = suggestions.find((x) => x.id === id);
                  if (s) applyToCert(i, s);
                }}
              >
                <SelectTrigger><SelectValue placeholder={t("inbounds.tlsSelectCert")} /></SelectTrigger>
                <SelectContent>
                  {suggestions.map((s) => (
                    <SelectItem key={s.id} value={s.id}>{s.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FieldRow>
          )}
          <FieldRow label={t("inbounds.usageOption")}>
            <Select value={cert.usage} onValueChange={(v) => update(i, { usage: v as TLSCertificate["usage"] })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="encipherment">encipherment</SelectItem>
                <SelectItem value="verify">verify</SelectItem>
                <SelectItem value="issue">issue</SelectItem>
              </SelectContent>
            </Select>
          </FieldRow>
          <FieldRow label="Input mode">
            <div className="flex gap-2">
              <button
                type="button"
                className={`${btnSecondaryClass} ${!cert.pemMode ? "border-[var(--accent)]" : ""}`}
                onClick={() => update(i, { pemMode: false })}
              >
                {t("inbounds.certFilePath")}
              </button>
              <button
                type="button"
                className={`${btnSecondaryClass} ${cert.pemMode ? "border-[var(--accent)]" : ""}`}
                onClick={() => update(i, { pemMode: true })}
              >
                {t("inbounds.certFileContent")}
              </button>
            </div>
          </FieldRow>
          {!cert.pemMode ? (
            <>
              <FieldRow label={t("inbounds.publicKey")}>
                <input
                  className={inputClass}
                  value={cert.certificateFile}
                  onChange={(e) => update(i, { certificateFile: e.target.value })}
                  placeholder="/path/to/fullchain.pem"
                  dir="ltr"
                />
              </FieldRow>
              <FieldRow label={t("inbounds.privateKey")}>
                <input
                  className={inputClass}
                  value={cert.keyFile}
                  onChange={(e) => update(i, { keyFile: e.target.value })}
                  placeholder="/path/to/privkey.pem"
                  dir="ltr"
                />
              </FieldRow>
            </>
          ) : (
            <>
              <FieldRow label={t("inbounds.publicKey")}>
                <textarea
                  className={`${inputClass} min-h-[80px] font-mono text-xs`}
                  value={cert.certificate.join("\n")}
                  onChange={(e) => update(i, { certificate: e.target.value.split("\n") })}
                  dir="ltr"
                />
              </FieldRow>
              <FieldRow label={t("inbounds.privateKey")}>
                <textarea
                  className={`${inputClass} min-h-[80px] font-mono text-xs`}
                  value={cert.key.join("\n")}
                  onChange={(e) => update(i, { key: e.target.value.split("\n") })}
                  dir="ltr"
                />
              </FieldRow>
            </>
          )}
          <FieldRow label={t("inbounds.ocspStapling")}>
            <div className="flex items-center gap-2">
              <input
                type="number"
                className={inputClass}
                style={{ maxWidth: 100 }}
                value={cert.ocspStapling}
                onChange={(e) => update(i, { ocspStapling: parseInt(e.target.value, 10) || 0 })}
                dir="ltr"
              />
              <span className="text-xs text-[var(--text-hint)]">s</span>
            </div>
          </FieldRow>
          <FieldRow label="Build Chain">
            <Switch checked={cert.buildChain} onCheckedChange={(v) => update(i, { buildChain: v })} />
          </FieldRow>
          <FieldRow label={t("inbounds.oneTimeLoading")}>
            <Switch checked={cert.oneTimeLoading} onCheckedChange={(v) => update(i, { oneTimeLoading: v })} />
          </FieldRow>
          <button type="button" className={btnDangerClass} onClick={() => onChange(certificates.filter((_, j) => j !== i))}>
            {t("common.remove")}
          </button>
        </div>
      ))}
    </CollapsibleSection>
  );
}
