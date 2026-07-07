"use client";

import { UseFormReturn } from "react-hook-form";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { FieldRow, inputClass, btnSecondaryClass, btnDangerClass } from "../shared/FieldRow";
import { CollapsibleSection } from "../shared/CollapsibleSection";
import type { InboundFormState } from "../types";
import { Plus } from "lucide-react";

interface Props {
  form: UseFormReturn<InboundFormState>;
}

export function HttpSettings({ form }: Props) {
  const { watch, setValue } = form;
  const h = watch("http");
  const accounts = h.accounts;

  return (
    <>
      <FieldRow label="Timeout" hint="Seconds to wait for HTTP CONNECT"><input type="number" className={inputClass} value={h.timeout} onChange={(e) => setValue("http.timeout", parseInt(e.target.value, 10) || 300)} /></FieldRow>
      <FieldRow label="Allow Transparent" hint="Allow non-CONNECT HTTP requests"><Switch checked={h.allowTransparent} onCheckedChange={(v) => setValue("http.allowTransparent", v)} /></FieldRow>
      <FieldRow label="User Level"><input type="number" className={inputClass} value={h.userLevel} onChange={(e) => setValue("http.userLevel", parseInt(e.target.value, 10) || 0)} /></FieldRow>
      <CollapsibleSection title="Accounts" action={<button type="button" className={btnSecondaryClass} onClick={() => setValue("http.accounts", [...accounts, { user: "", pass: "" }])}><Plus className="mr-1 inline h-3.5 w-3.5" />Add</button>}>
        <Badge variant="default" className="mb-2">Empty accounts list = no authentication required</Badge>
        {accounts.map((a, i) => (
          <div key={i} className="mb-2 flex gap-2">
            <input className={inputClass} placeholder="Username" value={a.user} onChange={(e) => { const n = [...accounts]; n[i] = { ...n[i], user: e.target.value }; setValue("http.accounts", n); }} />
            <input className={inputClass} placeholder="Password" value={a.pass} onChange={(e) => { const n = [...accounts]; n[i] = { ...n[i], pass: e.target.value }; setValue("http.accounts", n); }} />
            <button type="button" className={btnDangerClass} onClick={() => setValue("http.accounts", accounts.filter((_, j) => j !== i))}>×</button>
          </div>
        ))}
      </CollapsibleSection>
    </>
  );
}
