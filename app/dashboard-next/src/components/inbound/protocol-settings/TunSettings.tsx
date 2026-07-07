"use client";

import { UseFormReturn } from "react-hook-form";
import { FieldRow, inputClass } from "../shared/FieldRow";
import { TagInput } from "../shared/TagInput";
import { fieldError } from "../useInboundForm";
import type { InboundFormState } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
  errors: Record<string, string>;
}

export function TunSettings({ form, errors }: Props) {
  const { watch, setValue } = form;
  const t = watch("tun");

  return (
    <>
      <FieldRow label="Interface Name" required error={fieldError(errors, "tun.name")}>
        <input className={inputClass} value={t.name} onChange={(e) => setValue("tun.name", e.target.value)} />
      </FieldRow>
      <FieldRow label="MTU"><input type="number" className={inputClass} value={t.mtu} onChange={(e) => setValue("tun.mtu", parseInt(e.target.value, 10) || 1500)} /></FieldRow>
      <FieldRow label="Gateway Prefixes" required hint="Address prefixes, e.g. 10.0.0.1/16, fc00::1/64" error={fieldError(errors, "tun.gateway")}>
        <TagInput value={t.gateway} onChange={(v) => setValue("tun.gateway", v)} />
      </FieldRow>
      <FieldRow label="DNS Servers" hint="DNS IPs, e.g. 1.1.1.1, 8.8.8.8">
        <TagInput value={t.dns} onChange={(v) => setValue("tun.dns", v)} />
      </FieldRow>
      <FieldRow label="User Level"><input type="number" className={inputClass} value={t.userLevel} onChange={(e) => setValue("tun.userLevel", parseInt(e.target.value, 10) || 0)} /></FieldRow>
      <FieldRow label="Auto System Routing" hint="Routes automatically added to system routing table">
        <TagInput value={t.autoSystemRoutingTable} onChange={(v) => setValue("tun.autoSystemRoutingTable", v)} />
      </FieldRow>
      <FieldRow label="Auto Outbounds Interface"><input className={inputClass} value={t.autoOutboundsInterface} onChange={(e) => setValue("tun.autoOutboundsInterface", e.target.value)} /></FieldRow>
    </>
  );
}
