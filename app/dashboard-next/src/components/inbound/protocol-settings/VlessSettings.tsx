"use client";

import { useState } from "react";
import { UseFormReturn } from "react-hook-form";
import { api } from "@/panel/api/client";
import { FieldRow, inputClass, btnPrimaryClass, btnSecondaryClass } from "../shared/FieldRow";
import { FallbackRepeater } from "../shared/FallbackRepeater";
import type { InboundFormState } from "../types";
import { KEY_GEN_TYPES, VLESS_FLOWS, type VlessFlow } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
  showFlow: boolean;
  showFallbackHint: boolean;
}

export function VlessSettings({ form, showFlow, showFallbackHint }: Props) {
  const { watch, setValue, getValues } = form;
  const v = watch("vless");
  const [genLoading, setGenLoading] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  const genKeys = async () => {
    const current = getValues("vless");
    const keyGenType = current.keyGenType === "none" ? "x25519" : current.keyGenType;
    setGenLoading(true);
    setGenError(null);
    try {
      const res = await api.get<{
        decryption: string;
        encryption: string;
        keyGenType: string;
      }>(`/core/vlessenc?type=${encodeURIComponent(keyGenType)}`);
      setValue("vless.keyGenType", res.keyGenType || keyGenType, { shouldDirty: true });
      setValue("vless.decryption", res.decryption, { shouldDirty: true });
      setValue("vless.encryption", res.encryption, { shouldDirty: true });
    } catch (e: unknown) {
      setGenError(e instanceof Error ? e.message : "Key generation failed");
    } finally {
      setGenLoading(false);
    }
  };

  const clearKeys = () => {
    setValue("vless.decryption", "none", { shouldDirty: true });
    setValue("vless.encryption", "none", { shouldDirty: true });
    setValue("vless.keyGenType", "none", { shouldDirty: true });
    setGenError(null);
  };

  return (
    <>
      <FieldRow label="Decryption" hint="Server-side VLESS encryption (from xray vlessenc)">
        <input
          className={`${inputClass} font-mono text-xs`}
          value={v.decryption}
          onChange={(e) => setValue("vless.decryption", e.target.value, { shouldDirty: true })}
          dir="ltr"
          placeholder="none"
        />
      </FieldRow>

      <FieldRow label="Encryption" hint="Client-side matching encryption string">
        <input
          className={`${inputClass} font-mono text-xs`}
          value={v.encryption}
          onChange={(e) => setValue("vless.encryption", e.target.value, { shouldDirty: true })}
          dir="ltr"
          placeholder="none"
        />
      </FieldRow>

      <FieldRow label="Generate keys">
        <div className="flex flex-wrap items-center gap-2">
          <select
            className={`${inputClass} min-w-[200px]`}
            value={v.keyGenType}
            onChange={(e) => setValue("vless.keyGenType", e.target.value, { shouldDirty: true })}
          >
            {KEY_GEN_TYPES.map((k) => (
              <option key={k.value} value={k.value}>{k.label}</option>
            ))}
          </select>
          <button
            type="button"
            className={btnPrimaryClass}
            onClick={genKeys}
            disabled={genLoading}
          >
            {genLoading ? "Generating…" : "Generate"}
          </button>
          <button type="button" className={btnSecondaryClass} onClick={clearKeys} disabled={genLoading}>
            Clear
          </button>
        </div>
        {genError && <p className="mt-1 text-xs text-[var(--danger)]">{genError}</p>}
        <p className="mt-1 text-xs text-[var(--text-hint)]">
          Uses <code className="text-[var(--text-muted)]">xray vlessenc</code> — fills both Decryption (server) and Encryption (client).
        </p>
      </FieldRow>

      <FieldRow label="Vision testseed" hint="Applies only to clients using xtls-rprx-vision flow">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <input className={inputClass} value={v.visionTestSeed1} onChange={(e) => setValue("vless.visionTestSeed1", e.target.value)} dir="ltr" />
          <input className={inputClass} value={v.visionTestSeed2} onChange={(e) => setValue("vless.visionTestSeed2", e.target.value)} dir="ltr" />
          <input className={inputClass} value={v.visionTestSeed3} onChange={(e) => setValue("vless.visionTestSeed3", e.target.value)} dir="ltr" />
          <input className={inputClass} value={v.visionTestSeed4} onChange={(e) => setValue("vless.visionTestSeed4", e.target.value)} dir="ltr" />
        </div>
      </FieldRow>

      {showFlow && (
        <FieldRow label="Flow" tooltip="Default flow for new clients; requires TLS/Reality">
          <select
            className={inputClass}
            value={v.flow || ""}
            onChange={(e) => setValue("vless.flow", e.target.value as VlessFlow)}
          >
            {VLESS_FLOWS.map((fl) => (
              <option key={fl || "none"} value={fl}>{fl || "(none)"}</option>
            ))}
          </select>
        </FieldRow>
      )}

      {showFallbackHint && (
        <div className="mb-4 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-xs text-blue-300">
          Fallbacks become available once TLS/Reality is enabled in the Security step (VLESS/Trojan over RAW only).
        </div>
      )}

      <FallbackRepeater fallbacks={v.fallbacks} onChange={(f) => setValue("vless.fallbacks", f)} />
    </>
  );
}
