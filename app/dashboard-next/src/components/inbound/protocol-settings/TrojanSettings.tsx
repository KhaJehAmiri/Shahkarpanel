"use client";

import { UseFormReturn } from "react-hook-form";
import { FieldRow, inputClass, btnSecondaryClass } from "../shared/FieldRow";
import { UserRepeater } from "../shared/UserRepeater";
import { FallbackRepeater } from "../shared/FallbackRepeater";
import { fieldError, generatePassword } from "../useInboundForm";
import type { InboundFormState, TrojanUser } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
  errors: Record<string, string>;
}

export function TrojanSettings({ form, errors }: Props) {
  const { watch, setValue } = form;
  const clients = watch("trojan.clients");
  const fallbacks = watch("trojan.fallbacks");

  return (
    <>
      <UserRepeater<TrojanUser>
        users={clients}
        onChange={(u) => setValue("trojan.clients", u)}
        createEmpty={() => ({ password: "", level: 0, email: "" })}
        renderUser={(u, i, update) => (
          <>
            <FieldRow label="Password" required error={fieldError(errors, `trojan.clients.${i}.password`)}>
              <div className="flex gap-2">
                <input className={inputClass} value={u.password} onChange={(e) => update({ password: e.target.value })} />
                <button type="button" className={btnSecondaryClass} onClick={() => update({ password: generatePassword() })}>Generate</button>
              </div>
            </FieldRow>
            <FieldRow label="Email"><input className={inputClass} value={u.email} onChange={(e) => update({ email: e.target.value })} /></FieldRow>
            <FieldRow label="Level"><input type="number" className={inputClass} value={u.level} onChange={(e) => update({ level: parseInt(e.target.value, 10) || 0 })} /></FieldRow>
          </>
        )}
      />
      <FallbackRepeater fallbacks={fallbacks} onChange={(f) => setValue("trojan.fallbacks", f)} />
    </>
  );
}
