"use client";

import { UseFormReturn } from "react-hook-form";
import { FieldRow, inputClass } from "../shared/FieldRow";
import { fieldError } from "../useInboundForm";
import type { InboundFormState } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
  errors: Record<string, string>;
  isTun: boolean;
}

export function Step1Basics({ form, errors, isTun }: Props) {
  const { register, setValue, watch } = form;
  const port = watch("basics.port");

  return (
    <div className="px-6 py-4">
      <FieldRow label="Remark" required hint="Friendly name stored as xray tag" error={fieldError(errors, "basics.remark")}>
        <input {...register("basics.remark")} className={inputClass} placeholder="My Inbound" />
      </FieldRow>
      {!isTun && (
        <>
          <FieldRow label="Listen IP" hint="IPv4, IPv6, or Unix socket path. 0.0.0.0 = all interfaces">
            <input {...register("basics.listen")} className={inputClass} placeholder="0.0.0.0" />
          </FieldRow>
          <FieldRow label="Port" required hint="Single: 443 | Range: 5-10 | List: 11,13,15-17. Port 443 must be free (not used by panel nginx)." error={fieldError(errors, "basics.port")}>
            <input className={inputClass} value={port} onChange={(e) => setValue("basics.port", e.target.value, { shouldValidate: true })} placeholder="443" />
          </FieldRow>
        </>
      )}
      {isTun && (
        <p className="text-xs text-[var(--text-hint)]">TUN name, gateway, and DNS are configured in Settings (Step 3).</p>
      )}
    </div>
  );
}
