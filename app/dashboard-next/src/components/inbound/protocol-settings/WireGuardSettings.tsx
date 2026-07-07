"use client";

import { UseFormReturn } from "react-hook-form";
import { Plus, Trash2 } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { FieldRow, inputClass, btnPrimaryClass, btnSecondaryClass, btnDangerClass } from "../shared/FieldRow";
import { TagInput } from "../shared/TagInput";
import { fieldError } from "../useInboundForm";
import type { InboundFormState } from "../types";
import { DOMAIN_STRATEGIES } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
  errors: Record<string, string>;
  onGenerateKeys?: () => Promise<void>;
}

export function WireGuardSettings({ form, errors, onGenerateKeys }: Props) {
  const { watch, setValue } = form;
  const wg = watch("wireguard");
  const peers = wg.peers;

  return (
    <>
      <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-400">
        WireGuard traffic has distinct characteristics and may be blocked by firewalls.
      </div>
      <FieldRow label="Server Private Key" required error={fieldError(errors, "wireguard.secretKey")}>
        <div className="flex gap-2">
          <input className={inputClass} value={wg.secretKey} onChange={(e) => setValue("wireguard.secretKey", e.target.value)} />
          {onGenerateKeys && (
            <button type="button" className={btnPrimaryClass} onClick={() => void onGenerateKeys()}>Generate Keys</button>
          )}
        </div>
      </FieldRow>
      <FieldRow label="Address" hint="Server interface IPs, e.g. 10.0.0.1/24">
        <TagInput value={wg.address} onChange={(v) => setValue("wireguard.address", v)} />
      </FieldRow>
      <FieldRow label="DNS">
        <TagInput value={wg.dns} onChange={(v) => setValue("wireguard.dns", v)} placeholder="1.1.1.1" />
      </FieldRow>
      <FieldRow label="MTU"><input type="number" className={inputClass} value={wg.mtu} onChange={(e) => setValue("wireguard.mtu", parseInt(e.target.value, 10) || 1420)} /></FieldRow>
      <FieldRow label="No Kernel TUN" hint="Use userspace tun instead of kernel WireGuard">
        <Switch checked={wg.noKernelTun} onCheckedChange={(v) => setValue("wireguard.noKernelTun", v)} />
      </FieldRow>
      <FieldRow label="Domain Strategy">
        <Select value={wg.domainStrategy || "AsIs"} onValueChange={(v) => setValue("wireguard.domainStrategy", v === "AsIs" ? "" : v)}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {DOMAIN_STRATEGIES.map((d) => <SelectItem key={d} value={d}>{d}</SelectItem>)}
          </SelectContent>
        </Select>
      </FieldRow>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium">Peers</span>
        <button type="button" className={btnSecondaryClass} onClick={() => setValue("wireguard.peers", [...peers, { publicKey: "", allowedIPs: ["0.0.0.0/0"] }])}><Plus className="mr-1 inline h-3.5 w-3.5" />Add Peer</button>
      </div>
      {peers.map((p, i) => (
        <div key={i} className="mb-3 rounded-lg border border-[var(--border)] p-3">
          <FieldRow label="Client Public Key" required>
            <input className={inputClass} value={p.publicKey} onChange={(e) => { const n = [...peers]; n[i] = { ...n[i], publicKey: e.target.value }; setValue("wireguard.peers", n); }} />
          </FieldRow>
          <FieldRow label="Allowed IPs">
            <TagInput value={p.allowedIPs} onChange={(v) => { const n = [...peers]; n[i] = { ...n[i], allowedIPs: v }; setValue("wireguard.peers", n); }} />
          </FieldRow>
          {peers.length > 1 && (
            <button type="button" className={btnDangerClass} onClick={() => setValue("wireguard.peers", peers.filter((_, j) => j !== i))}><Trash2 className="mr-1 inline h-3 w-3" />Remove</button>
          )}
        </div>
      ))}
    </>
  );
}
