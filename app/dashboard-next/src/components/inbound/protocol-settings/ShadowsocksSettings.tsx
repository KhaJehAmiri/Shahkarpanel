"use client";

import { UseFormReturn } from "react-hook-form";
import { RefreshCw } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { FieldRow, inputClass } from "../shared/FieldRow";
import { fieldError, generateSs2022Key, ssPasswordLength } from "../useInboundForm";
import type { InboundFormState, SSMethod } from "../types";
import { SS_METHODS } from "../types";

function isSs2022(method: string): boolean {
  return method.startsWith("2022-blake3");
}

interface Props {
  form: UseFormReturn<InboundFormState>;
  errors: Record<string, string>;
}

export function ShadowsocksSettings({ form, errors }: Props) {
  const { watch, setValue } = form;
  const ss = watch("shadowsocks");

  const onMethodChange = (method: SSMethod) => {
    setValue("shadowsocks.method", method, { shouldDirty: true });
    if (isSs2022(method) !== isSs2022(ss.method)) {
      setValue("shadowsocks.password", "", { shouldDirty: true });
    }
  };

  return (
    <>
      <div className="mb-4 rounded-lg border border-sky-500/30 bg-sky-500/10 px-4 py-3 text-sm text-sky-200/90">
        Default v2ray subscription emits plain <span className="font-mono">ss://</span> links (no TLS/Reality
        transport). Stream and TLS can still be set on the server; use sing-box/clash-meta subs for complex transport.
      </div>
      <FieldRow label="Encryption method" required>
        <select
          className={inputClass}
          value={ss.method}
          onChange={(e) => onMethodChange(e.target.value as SSMethod)}
        >
          {SS_METHODS.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </FieldRow>

      {isSs2022(ss.method) && (
        <FieldRow label="Password" required error={fieldError(errors, "shadowsocks.password")} hint="Server PSK for SS-2022 (base64)">
          <div className="relative">
            <input
              className={`${inputClass} pr-10 font-mono`}
              value={ss.password}
              onChange={(e) => setValue("shadowsocks.password", e.target.value, { shouldDirty: true })}
              dir="ltr"
            />
            <button
              type="button"
              className="absolute inset-y-0 end-2 flex items-center text-[var(--text-hint)] hover:text-[var(--accent)]"
              onClick={() => setValue("shadowsocks.password", generateSs2022Key(ssPasswordLength(ss.method)), { shouldDirty: true })}
              title="Generate password"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        </FieldRow>
      )}

      <FieldRow label="Network">
        <select
          className={inputClass}
          value={ss.network}
          onChange={(e) => setValue("shadowsocks.network", e.target.value as typeof ss.network, { shouldDirty: true })}
        >
          <option value="tcp">TCP</option>
          <option value="udp">UDP</option>
          <option value="tcp,udp">TCP, UDP</option>
        </select>
      </FieldRow>

      <FieldRow label="ivCheck">
        <Switch checked={ss.ivCheck} onCheckedChange={(v) => setValue("shadowsocks.ivCheck", v, { shouldDirty: true })} />
      </FieldRow>
    </>
  );
}
