"use client";

import { useCallback, useEffect, useState } from "react";
import { UseFormReturn } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { api } from "@/panel/api/client";
import { FieldRow, inputClass, btnPrimaryClass, btnSecondaryClass } from "./FieldRow";
import { TagInput } from "./TagInput";
import { CollapsibleSection } from "./CollapsibleSection";
import { CertRepeater } from "./CertRepeater";
import { fieldError } from "../useInboundForm";
import type { InboundFormState, TLSCertificate } from "../types";
import {
  ALPN_OPTIONS,
  TLS_CIPHER_PRESETS,
  TLS_CURVE_OPTIONS,
  TLS_FINGERPRINTS,
} from "../types";

interface TlsCertSuggestion {
  id: string;
  label: string;
  certificateFile: string;
  keyFile: string;
  serverName?: string;
}

interface Props {
  form: UseFormReturn<InboundFormState>;
  errors: Record<string, string>;
}

export function TlsSettingsPanel({ form, errors }: Props) {
  const { t } = useTranslation();
  const { watch, setValue } = form;
  const tls = watch("tlsSettings");

  const [suggestions, setSuggestions] = useState<TlsCertSuggestion[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generatingEch, setGeneratingEch] = useState(false);
  const [issuingAcme, setIssuingAcme] = useState(false);
  const [acmeEmail, setAcmeEmail] = useState("admin@localhost");
  const [certError, setCertError] = useState<string | null>(null);
  const [echError, setEchError] = useState<string | null>(null);

  const loadSuggestions = useCallback(async () => {
    setLoadingSuggestions(true);
    setCertError(null);
    try {
      const res = await api.get<{ suggestions: TlsCertSuggestion[] }>("/core/tls/suggestions");
      setSuggestions(res.suggestions || []);
    } catch (err) {
      setCertError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingSuggestions(false);
    }
  }, []);

  useEffect(() => {
    void loadSuggestions();
  }, [loadSuggestions]);

  const toggleAlpn = (alpn: string) => {
    const next = tls.alpn.includes(alpn) ? tls.alpn.filter((x) => x !== alpn) : [...tls.alpn, alpn];
    setValue("tlsSettings.alpn", next);
  };

  const toggleCurve = (curve: string) => {
    const next = tls.curvePreferences.includes(curve)
      ? tls.curvePreferences.filter((x) => x !== curve)
      : [...tls.curvePreferences, curve];
    setValue("tlsSettings.curvePreferences", next);
  };

  const applyCipherPreset = (presetId: string) => {
    setValue("tlsSettings.cipherPreset", presetId);
    const preset = TLS_CIPHER_PRESETS.find((p) => p.id === presetId);
    if (preset && presetId !== "custom") {
      setValue("tlsSettings.cipherSuites", preset.value);
    }
  };

  const applySuggestion = (suggestion: TlsCertSuggestion) => {
    const cert: TLSCertificate = {
      usage: "encipherment",
      certificateFile: suggestion.certificateFile,
      keyFile: suggestion.keyFile,
      certificate: [],
      key: [],
      ocspStapling: 0,
      buildChain: false,
      oneTimeLoading: false,
      pemMode: false,
    };
    setValue("tlsSettings.certificates", [cert]);
    if (suggestion.serverName && !tls.serverName) {
      setValue("tlsSettings.serverName", suggestion.serverName);
    }
  };

  const generateSelfSigned = async () => {
    setGenerating(true);
    setCertError(null);
    try {
      const serverName = tls.serverName.trim();
      const created = await api.post<TlsCertSuggestion>("/core/tls/self-signed", {
        domain: serverName || undefined,
        serverName: serverName || undefined,
      });
      applySuggestion(created);
      await loadSuggestions();
    } catch (err) {
      setCertError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  };

  const issueAcme = async () => {
    const domain = tls.serverName.trim();
    if (!domain) {
      setCertError(t("inbounds.acmeNeedsSni", { defaultValue: "Set Server Name (SNI) to your domain first" }));
      return;
    }
    setIssuingAcme(true);
    setCertError(null);
    try {
      await api.post("/core/acme/issue", { domain, email: acmeEmail.trim() || "admin@localhost" });
      await loadSuggestions();
      setCertError(null);
    } catch (err) {
      setCertError(err instanceof Error ? err.message : String(err));
    } finally {
      setIssuingAcme(false);
    }
  };

  const generateEch = async () => {
    setGeneratingEch(true);
    setEchError(null);
    try {
      const serverName = tls.serverName.trim();
      const created = await api.post<{
        serverName: string;
        echServerKeys: string[];
        echConfigList: string[];
      }>("/core/tls/ech", { serverName: serverName || undefined });
      setValue("tlsSettings.echEnabled", true);
      setValue("tlsSettings.echServerKeys", created.echServerKeys || []);
      setValue("tlsSettings.echConfigList", created.echConfigList || []);
      if (created.serverName && !tls.serverName) {
        setValue("tlsSettings.serverName", created.serverName);
      }
    } catch (err) {
      setEchError(err instanceof Error ? err.message : String(err));
    } finally {
      setGeneratingEch(false);
    }
  };

  const clearEch = () => {
    setEchError(null);
    setValue("tlsSettings.echEnabled", false);
    setValue("tlsSettings.echServerKeys", []);
    setValue("tlsSettings.echConfigList", []);
  };

  const chipClass = (active: boolean) =>
    `rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${
      active
        ? "border-[var(--accent)] bg-[var(--accent)]/15 text-[var(--accent)]"
        : "border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--accent)]/50"
    }`;

  return (
    <>
      <FieldRow label="Server Name (SNI)" hint={t("inbounds.sniHint")}>
        <input
          className={inputClass}
          value={tls.serverName}
          onChange={(e) => setValue("tlsSettings.serverName", e.target.value)}
          placeholder="example.com"
          dir="ltr"
        />
      </FieldRow>

      <FieldRow label={t("inbounds.cipherSuites")}>
        <Select value={tls.cipherPreset || "auto"} onValueChange={applyCipherPreset}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {TLS_CIPHER_PRESETS.map((p) => (
              <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>
            ))}
            <SelectItem value="custom">{t("inbounds.cipherCustom")}</SelectItem>
          </SelectContent>
        </Select>
      </FieldRow>
      {(tls.cipherPreset === "custom" || (tls.cipherSuites && tls.cipherPreset === "auto" && !TLS_CIPHER_PRESETS.some((p) => p.value === tls.cipherSuites))) && (
        <FieldRow label={t("inbounds.cipherCustom")} hint="Colon-separated cipher suite names">
          <input
            className={inputClass}
            value={tls.cipherSuites}
            onChange={(e) => {
              setValue("tlsSettings.cipherSuites", e.target.value);
              setValue("tlsSettings.cipherPreset", "custom");
            }}
            dir="ltr"
          />
        </FieldRow>
      )}

      <FieldRow label={t("inbounds.tlsVersionRange")}>
        <div className="flex w-full items-center gap-2">
          <Select value={tls.minVersion} onValueChange={(v) => setValue("tlsSettings.minVersion", v as typeof tls.minVersion)}>
            <SelectTrigger className="flex-1"><SelectValue /></SelectTrigger>
            <SelectContent>{["1.0", "1.1", "1.2", "1.3"].map((v) => <SelectItem key={v} value={v}>{v}</SelectItem>)}</SelectContent>
          </Select>
          <span className="text-[var(--text-hint)]">—</span>
          <Select value={tls.maxVersion} onValueChange={(v) => setValue("tlsSettings.maxVersion", v as typeof tls.maxVersion)}>
            <SelectTrigger className="flex-1"><SelectValue /></SelectTrigger>
            <SelectContent>{["1.0", "1.1", "1.2", "1.3"].map((v) => <SelectItem key={v} value={v}>{v}</SelectItem>)}</SelectContent>
          </Select>
        </div>
      </FieldRow>

      <FieldRow label="uTLS">
        <Select value={tls.fingerprint || "empty"} onValueChange={(v) => setValue("tlsSettings.fingerprint", v === "empty" ? "" : v)}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="empty">(empty)</SelectItem>
            {TLS_FINGERPRINTS.filter(Boolean).map((f) => <SelectItem key={f} value={f}>{f}</SelectItem>)}
          </SelectContent>
        </Select>
      </FieldRow>

      <FieldRow label="ALPN">
        <div className="flex flex-wrap gap-2">
          {ALPN_OPTIONS.map((a) => (
            <button key={a} type="button" className={chipClass(tls.alpn.includes(a))} onClick={() => toggleAlpn(a)}>
              {a}
            </button>
          ))}
        </div>
      </FieldRow>

      <FieldRow label={t("inbounds.curvePreferences")}>
        <div className="flex flex-wrap gap-2">
          {TLS_CURVE_OPTIONS.map((c) => (
            <button key={c} type="button" className={chipClass(tls.curvePreferences.includes(c))} onClick={() => toggleCurve(c)}>
              {c}
            </button>
          ))}
        </div>
      </FieldRow>

      <FieldRow label={t("inbounds.rejectUnknownSni")}>
        <Switch checked={tls.rejectUnknownSni} onCheckedChange={(v) => setValue("tlsSettings.rejectUnknownSni", v)} />
      </FieldRow>
      <FieldRow label={t("inbounds.disableSystemRoot")}>
        <Switch checked={tls.disableSystemRoot} onCheckedChange={(v) => setValue("tlsSettings.disableSystemRoot", v)} />
      </FieldRow>
      <FieldRow label={t("inbounds.sessionResumption")}>
        <Switch checked={tls.enableSessionResumption} onCheckedChange={(v) => setValue("tlsSettings.enableSessionResumption", v)} />
      </FieldRow>
      <FieldRow label="Allow Insecure">
        <div className="flex items-center gap-2">
          <Switch checked={tls.allowInsecure} onCheckedChange={(v) => setValue("tlsSettings.allowInsecure", v)} />
          {tls.allowInsecure && <Badge variant="warning">⚠ {t("inbounds.allowInsecureWarn")}</Badge>}
        </div>
      </FieldRow>

      <div className="mb-4 rounded-lg border border-[var(--border)] p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <strong className="text-sm">{t("inbounds.digitalCert")}</strong>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={btnSecondaryClass} disabled={loadingSuggestions} onClick={() => void loadSuggestions()}>
              {loadingSuggestions ? t("common.loading") : t("inbounds.tlsRefreshCerts")}
            </button>
            <button type="button" className={btnPrimaryClass} disabled={generating} onClick={() => void generateSelfSigned()}>
              {generating ? t("common.loading") : t("inbounds.tlsGenerateSelfSigned")}
            </button>
            <button type="button" className={btnSecondaryClass} disabled={issuingAcme} onClick={() => void issueAcme()}>
              {issuingAcme ? t("common.loading") : t("inbounds.tlsIssueAcme", { defaultValue: "Issue ACME cert" })}
            </button>
          </div>
        </div>

        <FieldRow label={t("inbounds.acmeEmail", { defaultValue: "ACME email" })}>
          <input
            className={inputClass}
            value={acmeEmail}
            onChange={(e) => setAcmeEmail(e.target.value)}
            placeholder="admin@example.com"
            dir="ltr"
          />
        </FieldRow>

        {certError && <p className="mb-2 text-xs text-red-400">{certError}</p>}

        {suggestions.length > 0 && (
          <FieldRow label={t("inbounds.tlsLoadCert")} hint={t("inbounds.tlsLoadCertHint")}>
            <Select
              value=""
              onValueChange={(id) => {
                const s = suggestions.find((x) => x.id === id);
                if (s) applySuggestion(s);
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

        <CertRepeater
          certificates={tls.certificates}
          onChange={(c) => setValue("tlsSettings.certificates", c)}
          error={fieldError(errors, "tlsSettings.certificates")}
          suggestions={suggestions}
          onApplySuggestion={applySuggestion}
        />
      </div>

      <FieldRow label={t("inbounds.masterKeyLog")} hint={t("inbounds.masterKeyLogHint")}>
        <input
          className={inputClass}
          value={tls.masterKeyLog}
          onChange={(e) => setValue("tlsSettings.masterKeyLog", e.target.value)}
          placeholder="/path/to/sslkeylog.txt"
          dir="ltr"
        />
      </FieldRow>

      <CollapsibleSection title="ECH" defaultOpen={tls.echEnabled}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <FieldRow label="ECH">
            <Switch
              checked={tls.echEnabled}
              onCheckedChange={(v) => setValue("tlsSettings.echEnabled", v)}
            />
          </FieldRow>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={btnPrimaryClass}
              disabled={generatingEch}
              onClick={() => void generateEch()}
            >
              {generatingEch ? t("common.loading") : t("inbounds.tlsGenerateEch")}
            </button>
            {(tls.echEnabled || tls.echServerKeys.length > 0 || tls.echConfigList.length > 0) && (
              <button type="button" className={btnSecondaryClass} onClick={clearEch}>
                {t("common.clear")}
              </button>
            )}
          </div>
        </div>
        {echError && <p className="mb-2 text-xs text-red-400">{echError}</p>}
        <p className="mb-3 text-xs text-[var(--text-hint)]">{t("inbounds.tlsEchHint")}</p>
        <p className="mb-3 text-xs text-amber-500/90">{t("inbounds.echCdnWarning")}</p>
        {(tls.echEnabled || tls.echServerKeys.length > 0 || tls.echConfigList.length > 0) && (
          <>
            <FieldRow label={t("inbounds.tlsEchServerKeys")} hint={t("inbounds.tlsEchServerKeysHint")}>
              <textarea
                className={`${inputClass} min-h-[72px] font-mono text-xs`}
                value={tls.echServerKeys.join("\n")}
                onChange={(e) =>
                  setValue(
                    "tlsSettings.echServerKeys",
                    e.target.value.split("\n").map((x) => x.trim()).filter(Boolean),
                  )
                }
                dir="ltr"
                readOnly={generatingEch}
              />
            </FieldRow>
            <FieldRow label={t("inbounds.tlsEchConfigList")} hint={t("inbounds.tlsEchConfigHint")}>
              <textarea
                className={`${inputClass} min-h-[72px] font-mono text-xs`}
                value={tls.echConfigList.join("\n")}
                onChange={(e) =>
                  setValue(
                    "tlsSettings.echConfigList",
                    e.target.value.split("\n").map((x) => x.trim()).filter(Boolean),
                  )
                }
                dir="ltr"
                readOnly={generatingEch}
              />
            </FieldRow>
          </>
        )}
      </CollapsibleSection>

      <FieldRow label={t("inbounds.pinnedPeerCert")} hint={t("inbounds.pinnedPeerCertHint")}>
        <TagInput
          value={tls.pinnedPeerCertificateChainSha256}
          onChange={(v) => setValue("tlsSettings.pinnedPeerCertificateChainSha256", v)}
          placeholder="hex hash"
        />
      </FieldRow>
      <FieldRow label={t("inbounds.verifyPeerCert")}>
        <TagInput
          value={tls.verifyPeerCertByName}
          onChange={(v) => setValue("tlsSettings.verifyPeerCertByName", v)}
          placeholder="example.com"
        />
      </FieldRow>
    </>
  );
}
