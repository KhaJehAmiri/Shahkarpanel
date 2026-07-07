"use client";

import { UseFormReturn } from "react-hook-form";
import { Switch } from "@/components/ui/switch";
import { FieldRow, inputClass } from "../shared/FieldRow";
import { CollapsibleSection } from "../shared/CollapsibleSection";
import { fieldError } from "../useInboundForm";
import type { InboundFormState } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
  errors: Record<string, string>;
}

export function DokodemoSettings({ form, errors }: Props) {
  const { watch, setValue } = form;
  const d = watch("dokodemo");

  return (
    <>
      <FieldRow label="Tunnel Rewrite Mode" hint="Transparent proxy rewrite instead of fixed destination">
        <Switch checked={d.tunnelRewriteEnabled} onCheckedChange={(v) => setValue("dokodemo.tunnelRewriteEnabled", v)} />
      </FieldRow>

      {d.tunnelRewriteEnabled ? (
        <CollapsibleSection title="Tunnel Rewrite" defaultOpen>
          <FieldRow label="Rewrite Address" required error={fieldError(errors, "dokodemo.rewriteAddress")}>
            <input className={inputClass} value={d.rewriteAddress} onChange={(e) => setValue("dokodemo.rewriteAddress", e.target.value)} />
          </FieldRow>
          <FieldRow label="Rewrite Port">
            <input type="number" className={inputClass} value={d.rewritePort} onChange={(e) => setValue("dokodemo.rewritePort", parseInt(e.target.value, 10) || 0)} />
          </FieldRow>
          <FieldRow label="Allowed Network">
            <div className="flex gap-2">
              {(["tcp", "udp", "tcp,udp"] as const).map((n) => (
                <button key={n} type="button" className={`rounded-lg border px-3 py-1.5 text-xs ${d.allowedNetwork === n ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]" : "border-[var(--border)] text-[var(--text-muted)]"}`} onClick={() => setValue("dokodemo.allowedNetwork", n)}>{n === "tcp,udp" ? "TCP+UDP" : n.toUpperCase()}</button>
              ))}
            </div>
          </FieldRow>
          <FieldRow label="Port Map JSON" hint='e.g. {"80":8080,"443":8443}'>
            <textarea className={`${inputClass} min-h-[80px] font-mono text-xs`} value={d.portMapJson} onChange={(e) => setValue("dokodemo.portMapJson", e.target.value)} />
          </FieldRow>
        </CollapsibleSection>
      ) : (
        <>
          <FieldRow label="Destination Address" required error={fieldError(errors, "dokodemo.address")}>
            <input className={inputClass} value={d.address} onChange={(e) => setValue("dokodemo.address", e.target.value)} />
          </FieldRow>
          <FieldRow label="Destination Port" required error={fieldError(errors, "dokodemo.port")}>
            <input type="number" className={inputClass} value={d.port} onChange={(e) => setValue("dokodemo.port", parseInt(e.target.value, 10) || 0)} />
          </FieldRow>
          <FieldRow label="Network">
            <div className="flex gap-2">
              {(["tcp", "udp", "tcp,udp"] as const).map((n) => (
                <button key={n} type="button" className={`rounded-lg border px-3 py-1.5 text-xs ${d.network === n ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]" : "border-[var(--border)] text-[var(--text-muted)]"}`} onClick={() => setValue("dokodemo.network", n)}>{n === "tcp,udp" ? "TCP+UDP" : n.toUpperCase()}</button>
              ))}
            </div>
          </FieldRow>
        </>
      )}

      <FieldRow label="Timeout"><input type="number" className={inputClass} value={d.timeout} onChange={(e) => setValue("dokodemo.timeout", parseInt(e.target.value, 10) || 300)} /></FieldRow>
      <FieldRow label="Follow Redirect"><Switch checked={d.followRedirect} onCheckedChange={(v) => setValue("dokodemo.followRedirect", v)} /></FieldRow>
      <FieldRow label="User Level"><input type="number" className={inputClass} value={d.userLevel} onChange={(e) => setValue("dokodemo.userLevel", parseInt(e.target.value, 10) || 0)} /></FieldRow>
    </>
  );
}
