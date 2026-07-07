"use client";

import { UseFormReturn } from "react-hook-form";
import { Copy } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { FieldRow, inputClass, btnPrimaryClass, btnSecondaryClass } from "../shared/FieldRow";
import { SecurityCard } from "../shared/SecurityCard";
import { TagInput } from "../shared/TagInput";
import { CollapsibleSection } from "../shared/CollapsibleSection";
import { fieldError, generateShortId } from "../useInboundForm";
import type { InboundFormState, ProtocolDefinition, SecurityType } from "../types";
import { findProtocolDef } from "../types";
import { TLS_FINGERPRINTS } from "../types";
import { TlsSettingsPanel } from "../shared/TlsSettingsPanel";

interface Props {
  form: UseFormReturn<InboundFormState>;
  errors: Record<string, string>;
  protocols: ProtocolDefinition[];
  setSecurity: (s: SecurityType) => void;
  isRealityIncompatible: boolean;
  isHysteria: boolean;
  generateRealityKeys: () => Promise<void>;
}

const SECURITIES: { id: SecurityType; label: string; desc: string }[] = [
  { id: "none", label: "None", desc: "No transport security. Only for local/trusted networks." },
  { id: "tls", label: "TLS", desc: "Standard TLS. Requires certificate files or ACME." },
  { id: "reality", label: "Reality", desc: "TLS-masquerading without certificates. Highest evasion." },
];

export function Step5Security({
  form,
  errors,
  protocols,
  setSecurity,
  isRealityIncompatible,
  isHysteria,
  generateRealityKeys,
}: Props) {
  const { watch, setValue } = form;
  const protocol = watch("protocol");
  const security = watch("security");
  const reality = watch("realitySettings");
  const protocolDef = findProtocolDef(protocols, protocol);
  if (!protocolDef?.hasSecurity) return null;

  return (
    <div className="px-6 py-4">
      {isRealityIncompatible && (
        <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-400">
          ⚠ Reality requires RAW, XHTTP, or gRPC transport. Please update your Stream settings.
        </div>
      )}

      {protocol === "shadowsocks" && (
        <div className="mb-4 rounded-lg border border-sky-500/30 bg-sky-500/10 px-4 py-3 text-sm text-sky-200/90">
          Reality is not available for Shadowsocks. Use <strong className="text-sky-100">VLESS + Reality</strong> for
          camouflage, or TLS/none here for transport-only encryption.
        </div>
      )}

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {SECURITIES.filter((s) => !(protocol === "shadowsocks" && s.id === "reality")).map((s) => {
          const realityBlocked = s.id === "reality" && isRealityIncompatible;
          const hysteriaBlocked = isHysteria && s.id !== "tls";
          const disabled = realityBlocked || hysteriaBlocked;
          const disabledReason = hysteriaBlocked
            ? "Hysteria2 requires TLS"
            : realityBlocked
              ? "Reality requires RAW, XHTTP, or gRPC transport"
              : undefined;
          return (
            <SecurityCard
              key={s.id}
              id={s.id}
              label={s.label}
              description={s.desc}
              selected={security === s.id}
              disabled={disabled}
              disabledReason={disabledReason}
              onSelect={() => setSecurity(s.id)}
            />
          );
        })}
      </div>

      {security === "tls" && <TlsSettingsPanel form={form} errors={errors} />}

      {security === "reality" && (
        <>
          <FieldRow label="Show Debug Logs" hint="Log Reality handshake details">
            <Switch checked={reality.show} onCheckedChange={(v) => setValue("realitySettings.show", v)} />
          </FieldRow>
          <FieldRow label="Target (Dest)" required hint="Masquerade target, e.g. yahoo.com:443" error={fieldError(errors, "realitySettings.target")}>
            <input className={inputClass} value={reality.target} onChange={(e) => setValue("realitySettings.target", e.target.value)} />
          </FieldRow>
          <FieldRow label="xver" hint="Proxy Protocol version to send to target">
            <Select value={String(reality.xver)} onValueChange={(v) => setValue("realitySettings.xver", parseInt(v, 10) as 0 | 1 | 2)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{["0", "1", "2"].map((v) => <SelectItem key={v} value={v}>{v}</SelectItem>)}</SelectContent>
            </Select>
          </FieldRow>
          <FieldRow label="Server Names" required hint="Allowed SNI list" error={fieldError(errors, "realitySettings.serverNames")}>
            <TagInput value={reality.serverNames} onChange={(v) => setValue("realitySettings.serverNames", v)} placeholder="yahoo.com" />
          </FieldRow>
          <FieldRow label="Private Key" required error={fieldError(errors, "realitySettings.privateKey")}>
            <div className="flex gap-2">
              <input className={inputClass} value={reality.privateKey} onChange={(e) => setValue("realitySettings.privateKey", e.target.value)} />
              <button type="button" className={btnPrimaryClass} onClick={() => void generateRealityKeys()}>Generate Keys</button>
            </div>
          </FieldRow>
          <FieldRow label="Public Key">
            <div className="flex gap-2">
              <input className={inputClass} readOnly value={reality.publicKey} />
              <button type="button" className={btnSecondaryClass} onClick={() => navigator.clipboard.writeText(reality.publicKey)}><Copy className="h-3.5 w-3.5" /></button>
            </div>
          </FieldRow>
          <FieldRow label="Fingerprint" hint="TLS fingerprint for Reality clients">
            <Select value={reality.fingerprint || "chrome"} onValueChange={(v) => setValue("realitySettings.fingerprint", v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {TLS_FINGERPRINTS.map((fp) => (
                  <SelectItem key={fp} value={fp}>{fp}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FieldRow>
          <FieldRow label="SpiderX" hint="Initial path for Reality spider crawl; e.g. /">
            <input className={inputClass} value={reality.spiderX} onChange={(e) => setValue("realitySettings.spiderX", e.target.value)} placeholder="/" />
          </FieldRow>
          <FieldRow label="Min Client Version" hint="Minimum xray-core version, e.g. 1.8.0">
            <input className={inputClass} value={reality.minClientVer} onChange={(e) => setValue("realitySettings.minClientVer", e.target.value)} />
          </FieldRow>
          <FieldRow label="Max Client Version"><input className={inputClass} value={reality.maxClientVer} onChange={(e) => setValue("realitySettings.maxClientVer", e.target.value)} /></FieldRow>
          <FieldRow label="Max Time Diff" hint="0 = disabled; max clock skew allowed">
            <input type="number" className={inputClass} value={reality.maxTimeDiff} onChange={(e) => setValue("realitySettings.maxTimeDiff", parseInt(e.target.value, 10) || 0)} />
          </FieldRow>
          <FieldRow label="Short IDs" required hint="Hex strings 2–16 chars. At least one required." error={fieldError(errors, "realitySettings.shortIds")}>
            <TagInput
              value={reality.shortIds}
              onChange={(v) => setValue("realitySettings.shortIds", v)}
              onRegenerate={(i) => {
                const next = [...reality.shortIds];
                next[i] = generateShortId();
                setValue("realitySettings.shortIds", next);
              }}
            />
          </FieldRow>
          <FieldRow label="MLDSA65 Seed" hint="Post-quantum seed; leave empty unless clients support it">
            <input className={inputClass} value={reality.mldsa65Seed} onChange={(e) => setValue("realitySettings.mldsa65Seed", e.target.value)} />
          </FieldRow>
          <FieldRow label="MLDSA65 Verify" hint="Verification key (separate from seed when needed)">
            <input className={inputClass} value={reality.mldsa65Verify} onChange={(e) => setValue("realitySettings.mldsa65Verify", e.target.value)} />
          </FieldRow>
          <CollapsibleSection title="Limit Fallback Upload">
            <FieldRow label="After Bytes"><input type="number" className={inputClass} value={reality.limitFallbackUpload.afterBytes} onChange={(e) => setValue("realitySettings.limitFallbackUpload.afterBytes", parseInt(e.target.value, 10) || 0)} /></FieldRow>
            <FieldRow label="Bytes Per Sec"><input type="number" className={inputClass} value={reality.limitFallbackUpload.bytesPerSec} onChange={(e) => setValue("realitySettings.limitFallbackUpload.bytesPerSec", parseInt(e.target.value, 10) || 0)} /></FieldRow>
            <FieldRow label="Burst Bytes Per Sec"><input type="number" className={inputClass} value={reality.limitFallbackUpload.burstBytesPerSec} onChange={(e) => setValue("realitySettings.limitFallbackUpload.burstBytesPerSec", parseInt(e.target.value, 10) || 0)} /></FieldRow>
          </CollapsibleSection>
          <CollapsibleSection title="Limit Fallback Download">
            <FieldRow label="After Bytes"><input type="number" className={inputClass} value={reality.limitFallbackDownload.afterBytes} onChange={(e) => setValue("realitySettings.limitFallbackDownload.afterBytes", parseInt(e.target.value, 10) || 0)} /></FieldRow>
            <FieldRow label="Bytes Per Sec"><input type="number" className={inputClass} value={reality.limitFallbackDownload.bytesPerSec} onChange={(e) => setValue("realitySettings.limitFallbackDownload.bytesPerSec", parseInt(e.target.value, 10) || 0)} /></FieldRow>
            <FieldRow label="Burst Bytes Per Sec"><input type="number" className={inputClass} value={reality.limitFallbackDownload.burstBytesPerSec} onChange={(e) => setValue("realitySettings.limitFallbackDownload.burstBytesPerSec", parseInt(e.target.value, 10) || 0)} /></FieldRow>
          </CollapsibleSection>
        </>
      )}
    </div>
  );
}
