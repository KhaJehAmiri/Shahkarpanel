"use client";

import { UseFormReturn } from "react-hook-form";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { FieldRow, inputClass, btnSecondaryClass, btnDangerClass } from "../shared/FieldRow";
import { CollapsibleSection } from "../shared/CollapsibleSection";
import type { InboundFormState } from "../types";
import { Plus } from "lucide-react";

interface Props {
  form: UseFormReturn<InboundFormState>;
}

export function SocksSettings({ form }: Props) {
  const { watch, setValue } = form;
  const s = watch("socks");
  const accounts = s.accounts;

  return (
    <>
      <FieldRow label="Auth">
        <Select value={s.auth} onValueChange={(v) => setValue("socks.auth", v as "noauth" | "password")}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="noauth">noauth</SelectItem>
            <SelectItem value="password">password</SelectItem>
          </SelectContent>
        </Select>
      </FieldRow>
      {s.auth === "password" && (
        <CollapsibleSection title="Accounts" defaultOpen action={<button type="button" className={btnSecondaryClass} onClick={() => setValue("socks.accounts", [...accounts, { user: "", pass: "" }])}><Plus className="mr-1 inline h-3.5 w-3.5" />Add</button>}>
          {accounts.map((a, i) => (
            <div key={i} className="mb-2 flex gap-2">
              <input className={inputClass} placeholder="Username" value={a.user} onChange={(e) => { const n = [...accounts]; n[i] = { ...n[i], user: e.target.value }; setValue("socks.accounts", n); }} />
              <input className={inputClass} placeholder="Password" value={a.pass} onChange={(e) => { const n = [...accounts]; n[i] = { ...n[i], pass: e.target.value }; setValue("socks.accounts", n); }} />
              <button type="button" className={btnDangerClass} onClick={() => setValue("socks.accounts", accounts.filter((_, j) => j !== i))}>×</button>
            </div>
          ))}
        </CollapsibleSection>
      )}
      <FieldRow label="UDP" hint="Enable UDP relay"><Switch checked={s.udp} onCheckedChange={(v) => setValue("socks.udp", v)} /></FieldRow>
      {s.udp && <FieldRow label="UDP Local IP" hint="Local IP for UDP packets"><input className={inputClass} value={s.ip} onChange={(e) => setValue("socks.ip", e.target.value)} /></FieldRow>}
      <FieldRow label="User Level"><input type="number" className={inputClass} value={s.userLevel} onChange={(e) => setValue("socks.userLevel", parseInt(e.target.value, 10) || 0)} /></FieldRow>
    </>
  );
}
