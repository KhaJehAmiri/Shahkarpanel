"use client";

import { UseFormReturn } from "react-hook-form";
import { Switch } from "@/components/ui/switch";
import { FieldRow, inputClass, btnSecondaryClass } from "../shared/FieldRow";
import { UserRepeater } from "../shared/UserRepeater";
import { CollapsibleSection } from "../shared/CollapsibleSection";
import { WireGuardSettings } from "./WireGuardSettings";
import { fieldError, generatePassword } from "../useInboundForm";
import type { InboundFormState, Hysteria2User } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
  errors: Record<string, string>;
  onGenerateWgKeys?: () => Promise<void>;
}

export function Hysteria2SettingsPanel({ form, errors }: Props) {
  const { watch, setValue } = form;
  const users = watch("hysteria2.users");
  const masq = watch("hysteria2.masquerade");

  return (
    <>
      <div className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-4 py-3 text-sm text-[var(--text-muted)]">
        Hysteria2 requires TLS security and the hysteria transport layer.
      </div>
      <UserRepeater<Hysteria2User>
        users={users}
        onChange={(u) => setValue("hysteria2.users", u)}
        createEmpty={() => ({ auth: "", level: 0, email: "" })}
        renderUser={(u, i, update) => (
          <>
            <FieldRow label="Auth (password)" required error={fieldError(errors, "hysteria2.users")}>
              <div className="flex gap-2">
                <input className={inputClass} value={u.auth} onChange={(e) => update({ auth: e.target.value })} />
                <button type="button" className={btnSecondaryClass} onClick={() => update({ auth: generatePassword() })}>Generate</button>
              </div>
            </FieldRow>
            <FieldRow label="Email"><input className={inputClass} value={u.email} onChange={(e) => update({ email: e.target.value })} /></FieldRow>
            <FieldRow label="Level"><input type="number" className={inputClass} value={u.level} onChange={(e) => update({ level: parseInt(e.target.value, 10) || 0 })} /></FieldRow>
          </>
        )}
      />

      <CollapsibleSection title="Masquerade" defaultOpen={masq.enabled}>
        <FieldRow label="Enable Masquerade">
          <Switch checked={masq.enabled} onCheckedChange={(v) => setValue("hysteria2.masquerade.enabled", v)} />
        </FieldRow>
        {masq.enabled && (
          <>
            <FieldRow label="Type"><input className={inputClass} value={masq.type} onChange={(e) => setValue("hysteria2.masquerade.type", e.target.value)} placeholder="file, proxy, string" /></FieldRow>
            <FieldRow label="URL"><input className={inputClass} value={masq.url} onChange={(e) => setValue("hysteria2.masquerade.url", e.target.value)} /></FieldRow>
            <FieldRow label="Directory"><input className={inputClass} value={masq.dir} onChange={(e) => setValue("hysteria2.masquerade.dir", e.target.value)} /></FieldRow>
            <FieldRow label="Rewrite Host"><Switch checked={masq.rewriteHost} onCheckedChange={(v) => setValue("hysteria2.masquerade.rewriteHost", v)} /></FieldRow>
            <FieldRow label="Insecure TLS"><Switch checked={masq.insecure} onCheckedChange={(v) => setValue("hysteria2.masquerade.insecure", v)} /></FieldRow>
            <FieldRow label="Content"><textarea className={`${inputClass} min-h-[80px]`} value={masq.content} onChange={(e) => setValue("hysteria2.masquerade.content", e.target.value)} /></FieldRow>
            <FieldRow label="Status Code"><input type="number" className={inputClass} value={masq.statusCode} onChange={(e) => setValue("hysteria2.masquerade.statusCode", parseInt(e.target.value, 10) || 0)} /></FieldRow>
          </>
        )}
      </CollapsibleSection>
    </>
  );
}

export function AmneziaWgSettings({ form, errors, onGenerateWgKeys }: Props) {
  const { watch, setValue } = form;
  return (
    <>
      <WireGuardSettings form={form} errors={errors} onGenerateKeys={onGenerateWgKeys} />
      <CollapsibleSection title="Advanced AmneziaWG Options">
        <FieldRow label="Extra JSON" hint="Additional fields specific to AmneziaWG protocol" error={fieldError(errors, "amneziaExtraJson")}>
          <textarea
            className={`${inputClass} min-h-[120px] font-mono text-xs`}
            value={watch("amneziaExtraJson")}
            onChange={(e) => setValue("amneziaExtraJson", e.target.value)}
          />
        </FieldRow>
      </CollapsibleSection>
    </>
  );
}
