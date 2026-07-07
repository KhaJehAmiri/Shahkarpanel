"use client";

import { UseFormReturn } from "react-hook-form";
import { Plus, Trash2 } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import {
  DOMAIN_STRATEGIES,
  SOCKOPT_REAL_IP,
  TCP_CONGESTION,
  TPROXY_MODES,
  type InboundFormState,
  type SockoptSettings,
} from "../types";
import { FieldRow, inputClass, btnDangerClass, btnSecondaryClass } from "../shared/FieldRow";
import { SegChoice } from "../shared/SegChoice";

interface Props {
  form: UseFormReturn<InboundFormState>;
}

export function SockoptPanel({ form }: Props) {
  const { watch, setValue } = form;
  const s = watch("sockoptSettings");

  const set = <K extends keyof SockoptSettings>(key: K, val: SockoptSettings[K]) => {
    setValue(`sockoptSettings.${key}` as `sockoptSettings.${K}`, val as never, { shouldDirty: true });
  };

  const addCustom = () => set("customOptions", [...s.customOptions, { key: "", value: "" }]);
  const updateCustom = (idx: number, key: string, value: string) =>
    set(
      "customOptions",
      s.customOptions.map((o, i) => (i === idx ? { key, value } : o)),
    );
  const removeCustom = (idx: number) =>
    set("customOptions", s.customOptions.filter((_, i) => i !== idx));

  return (
    <div className="mb-6 border-t border-[var(--border)] pt-4">
      <FieldRow label="Sockopt" hint="Advanced socket options (streamSettings.sockopt)">
        <Switch checked={s.enabled} onCheckedChange={(v) => set("enabled", v)} />
      </FieldRow>

      {s.enabled && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-4">
          <FieldRow label="Real client IP">
            <SegChoice
              value={s.realClientIp}
              onChange={(v) => set("realClientIp", v as typeof s.realClientIp)}
              options={SOCKOPT_REAL_IP.map((o) => ({ value: o.value, label: o.label }))}
            />
          </FieldRow>

          <div className="grid gap-0 sm:grid-cols-2">
            <FieldRow label="Route Mark">
              <input className={inputClass} value={s.mark} onChange={(e) => set("mark", e.target.value)} dir="ltr" />
            </FieldRow>
            <FieldRow label="TCP Keep Alive Interval">
              <input className={inputClass} value={s.tcpKeepAliveInterval} onChange={(e) => set("tcpKeepAliveInterval", e.target.value)} dir="ltr" />
            </FieldRow>
            <FieldRow label="TCP Keep Alive Idle">
              <input className={inputClass} value={s.tcpKeepAliveIdle} onChange={(e) => set("tcpKeepAliveIdle", e.target.value)} dir="ltr" />
            </FieldRow>
            <FieldRow label="TCP Max Seg">
              <input className={inputClass} value={s.tcpMaxSeg} onChange={(e) => set("tcpMaxSeg", e.target.value)} dir="ltr" />
            </FieldRow>
            <FieldRow label="TCP User Timeout">
              <input className={inputClass} value={s.tcpUserTimeout} onChange={(e) => set("tcpUserTimeout", e.target.value)} dir="ltr" />
            </FieldRow>
            <FieldRow label="TCP Window Clamp">
              <input className={inputClass} value={s.tcpWindowClamp} onChange={(e) => set("tcpWindowClamp", e.target.value)} dir="ltr" />
            </FieldRow>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <FieldRow label="Proxy Protocol">
              <Switch checked={s.acceptProxyProtocol} onCheckedChange={(v) => set("acceptProxyProtocol", v)} />
            </FieldRow>
            <FieldRow label="TCP Fast Open">
              <Switch checked={s.tcpFastOpen} onCheckedChange={(v) => set("tcpFastOpen", v)} />
            </FieldRow>
            <FieldRow label="Penetrate">
              <Switch checked={s.penetrate} onCheckedChange={(v) => set("penetrate", v)} />
            </FieldRow>
            <FieldRow label="V6 Only">
              <Switch checked={s.v6Only} onCheckedChange={(v) => set("v6Only", v)} />
            </FieldRow>
          </div>

          <div className="grid gap-0 sm:grid-cols-2">
            <FieldRow label="TCP Congestion">
              <select className={inputClass} value={s.tcpCongestion} onChange={(e) => set("tcpCongestion", e.target.value)}>
                {TCP_CONGESTION.map((c) => (
                  <option key={c || "default"} value={c}>{c || "(default)"}</option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label="TProxy">
              <select className={inputClass} value={s.tproxy} onChange={(e) => set("tproxy", e.target.value)}>
                {TPROXY_MODES.map((m) => (
                  <option key={m || "off"} value={m}>{m || "Off"}</option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label="Trusted X-Forwarded-For" hint="Comma-separated CIDRs or geoip tags">
              <input className={inputClass} value={s.trustedXForwardedFor} onChange={(e) => set("trustedXForwardedFor", e.target.value)} dir="ltr" />
            </FieldRow>
            <FieldRow label="Domain Strategy">
              <select className={inputClass} value={s.domainStrategy} onChange={(e) => set("domainStrategy", e.target.value)}>
                <option value="">(default)</option>
                {DOMAIN_STRATEGIES.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </FieldRow>
          </div>

          <div className="mt-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium text-[var(--text)]">Custom sockopt</span>
              <button type="button" className={btnSecondaryClass} onClick={addCustom}>
                <Plus className="mr-1 inline h-3.5 w-3.5" /> Add custom option
              </button>
            </div>
            {s.customOptions.map((opt, idx) => (
              <div key={idx} className="mb-2 flex gap-2">
                <input
                  className={`${inputClass} w-1/3`}
                  placeholder="key"
                  value={opt.key}
                  onChange={(e) => updateCustom(idx, e.target.value, opt.value)}
                  dir="ltr"
                />
                <input
                  className={`${inputClass} flex-1 font-mono text-xs`}
                  placeholder="value"
                  value={opt.value}
                  onChange={(e) => updateCustom(idx, opt.key, e.target.value)}
                  dir="ltr"
                />
                <button type="button" className={btnDangerClass} onClick={() => removeCustom(idx)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
