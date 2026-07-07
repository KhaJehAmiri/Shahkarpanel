"use client";

import { UseFormReturn } from "react-hook-form";
import { Switch } from "@/components/ui/switch";
import { FieldRow, inputClass } from "../shared/FieldRow";
import { KeyValueRepeater } from "../shared/KeyValueRepeater";
import type { InboundFormState } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
}

export function RawStreamPanel({ form }: Props) {
  const { watch, setValue } = form;
  const raw = watch("rawSettings");

  return (
    <>
      <FieldRow label="Proxy Protocol" hint="For HAProxy/nginx with proxy_protocol">
        <Switch
          checked={raw.acceptProxyProtocol}
          onCheckedChange={(v) => setValue("rawSettings.acceptProxyProtocol", v, { shouldDirty: true })}
        />
      </FieldRow>

      <FieldRow label="HTTP Obfuscation" hint="Camouflage traffic as HTTP (tcp header type http)">
        <Switch
          checked={raw.httpObfuscation}
          onCheckedChange={(v) => setValue("rawSettings.httpObfuscation", v, { shouldDirty: true })}
        />
      </FieldRow>

      {raw.httpObfuscation && (
        <div className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-4">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">Request</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <FieldRow label="Version">
              <input
                className={inputClass}
                value={raw.request.version}
                onChange={(e) => setValue("rawSettings.request.version", e.target.value, { shouldDirty: true })}
                dir="ltr"
              />
            </FieldRow>
            <FieldRow label="Method">
              <input
                className={inputClass}
                value={raw.request.method}
                onChange={(e) => setValue("rawSettings.request.method", e.target.value, { shouldDirty: true })}
                dir="ltr"
              />
            </FieldRow>
            <FieldRow label="Path">
              <input
                className={inputClass}
                value={raw.request.path}
                onChange={(e) => setValue("rawSettings.request.path", e.target.value, { shouldDirty: true })}
                dir="ltr"
              />
            </FieldRow>
          </div>
          <KeyValueRepeater
            label="Request headers"
            value={raw.request.headers}
            onChange={(h) => setValue("rawSettings.request.headers", h, { shouldDirty: true })}
          />

          <p className="mb-3 mt-4 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">Response</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <FieldRow label="Version">
              <input className={inputClass} value={raw.response.version} readOnly dir="ltr" />
            </FieldRow>
            <FieldRow label="Status">
              <input
                className={inputClass}
                value={raw.response.status}
                onChange={(e) => setValue("rawSettings.response.status", e.target.value, { shouldDirty: true })}
                dir="ltr"
              />
            </FieldRow>
            <FieldRow label="Reason">
              <input
                className={inputClass}
                value={raw.response.reason}
                onChange={(e) => setValue("rawSettings.response.reason", e.target.value, { shouldDirty: true })}
                dir="ltr"
              />
            </FieldRow>
          </div>
          <KeyValueRepeater
            label="Response headers"
            value={raw.response.headers}
            onChange={(h) => setValue("rawSettings.response.headers", h, { shouldDirty: true })}
          />
        </div>
      )}
    </>
  );
}
