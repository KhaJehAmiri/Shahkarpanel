"use client";

import { UseFormReturn } from "react-hook-form";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { FieldRow } from "../shared/FieldRow";
import { TagInput } from "../shared/TagInput";
import type { InboundFormState, SniffDestOverride } from "../types";
import { SNIFF_OPTIONS } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
}

const SNIFF_LABELS: Record<SniffDestOverride, string> = {
  http: "HTTP",
  tls: "TLS",
  quic: "QUIC",
  fakedns: "FakeDNS",
};

export function Step6Sniffing({ form }: Props) {
  const { watch, setValue } = form;
  const sniffing = watch("sniffing");

  const toggleOverride = (opt: SniffDestOverride) => {
    const current = sniffing.destOverride;
    if (current.includes(opt)) {
      setValue("sniffing.destOverride", current.filter((o) => o !== opt));
    } else {
      setValue("sniffing.destOverride", [...current, opt]);
    }
  };

  return (
    <div className="px-6 py-4">
      <FieldRow label="Enable Sniffing">
        <Switch checked={sniffing.enabled} onCheckedChange={(v) => setValue("sniffing.enabled", v)} />
      </FieldRow>

      {sniffing.enabled && (
        <>
          <FieldRow label="Destination Override" hint="Rewrite destination address based on detected protocol">
            <div className="flex flex-wrap gap-2">
              {SNIFF_OPTIONS.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  onClick={() => toggleOverride(opt)}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-xs font-medium transition",
                    sniffing.destOverride.includes(opt)
                      ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]"
                      : "border-[var(--border)] text-[var(--text-muted)]",
                  )}
                >
                  {SNIFF_LABELS[opt]}
                </button>
              ))}
            </div>
          </FieldRow>
          <FieldRow label="Metadata Only" hint="Sniff using only connection metadata, no payload inspection">
            <Switch checked={sniffing.metadataOnly} onCheckedChange={(v) => setValue("sniffing.metadataOnly", v)} />
          </FieldRow>
          <FieldRow label="Route Only" hint="Use sniffed result for routing only; do not override destination IP">
            <Switch checked={sniffing.routeOnly} onCheckedChange={(v) => setValue("sniffing.routeOnly", v)} />
          </FieldRow>
          <FieldRow label="Excluded Domains" hint="Domains whose destination will NOT be overridden, e.g. example.com">
            <TagInput value={sniffing.excludedDomains} onChange={(v) => setValue("sniffing.excludedDomains", v)} />
          </FieldRow>
          <FieldRow label="Excluded IPs" hint="IPs/CIDRs excluded from destination override">
            <TagInput value={sniffing.excludedIps} onChange={(v) => setValue("sniffing.excludedIps", v)} />
          </FieldRow>
        </>
      )}
    </div>
  );
}
