"use client";

import { UseFormReturn } from "react-hook-form";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { FieldRow, inputClass, btnSecondaryClass } from "../shared/FieldRow";
import { UserRepeater } from "../shared/UserRepeater";
import { fieldError, generateUuid } from "../useInboundForm";
import type { InboundFormState, VMessUser } from "../types";
import { VMESS_SECURITY_OPTIONS } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
  errors: Record<string, string>;
}

export function VmessSettings({ form, errors }: Props) {
  const { watch, setValue } = form;
  const clients = watch("vmess.clients");

  return (
    <UserRepeater<VMessUser>
      users={clients}
      onChange={(u) => setValue("vmess.clients", u)}
      createEmpty={() => ({ id: "", alterId: 0, security: "auto", level: 0, email: "" })}
      renderUser={(u, i, update) => (
        <>
          <FieldRow label="UUID" required error={fieldError(errors, `vmess.clients.${i}.id`)}>
            <div className="flex gap-2">
              <input className={inputClass} value={u.id} onChange={(e) => update({ id: e.target.value })} />
              <button type="button" className={btnSecondaryClass} onClick={() => update({ id: generateUuid() })}>Generate UUID</button>
            </div>
          </FieldRow>
          <FieldRow label="AlterID" hint="Keep at 0 for AEAD">
            <input type="number" className={inputClass} value={u.alterId} onChange={(e) => update({ alterId: parseInt(e.target.value, 10) || 0 })} />
            {u.alterId > 0 && <Badge variant="warning" className="mt-1">⚠ AlterID &gt; 0 disables AEAD encryption. Keep at 0.</Badge>}
          </FieldRow>
          <FieldRow label="Security" hint="Payload encryption; auto selects best for client">
            <Select value={u.security} onValueChange={(v) => update({ security: v as VMessUser["security"] })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{VMESS_SECURITY_OPTIONS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
            </Select>
          </FieldRow>
          <FieldRow label="Email"><input className={inputClass} value={u.email} onChange={(e) => update({ email: e.target.value })} /></FieldRow>
          <FieldRow label="Level"><input type="number" className={inputClass} value={u.level} onChange={(e) => update({ level: parseInt(e.target.value, 10) || 0 })} /></FieldRow>
        </>
      )}
    />
  );
}
