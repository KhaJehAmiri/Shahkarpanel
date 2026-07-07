"use client";

import { CollapsibleSection } from "./CollapsibleSection";
import { FieldRow, inputClass, btnSecondaryClass, btnDangerClass } from "./FieldRow";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export interface FallbackItem {
  name: string;
  alpn: string;
  path: string;
  dest: string | number;
  xver: 0 | 1 | 2;
}

interface FallbackRepeaterProps {
  fallbacks: FallbackItem[];
  onChange: (f: FallbackItem[]) => void;
}

export function FallbackRepeater({ fallbacks, onChange }: FallbackRepeaterProps) {
  return (
    <CollapsibleSection
      title="Fallbacks"
      action={
        <button
          type="button"
          className={btnSecondaryClass}
          onClick={() =>
            onChange([...fallbacks, { name: "", alpn: "", path: "", dest: "", xver: 0 }])
          }
        >
          + Add Fallback
        </button>
      }
    >
      {fallbacks.length === 0 && (
        <p className="text-xs text-[var(--text-hint)]">No fallbacks configured.</p>
      )}
      {fallbacks.map((fb, i) => (
        <div key={i} className="mb-3 rounded-lg border border-[var(--border)] p-3">
          <FieldRow label="Name" hint="Optional label">
            <input className={inputClass} value={fb.name} onChange={(e) => {
              const n = [...fallbacks]; n[i] = { ...n[i], name: e.target.value }; onChange(n);
            }} />
          </FieldRow>
          <FieldRow label="ALPN" hint="Match on ALPN, e.g. h2 or http/1.1">
            <input className={inputClass} value={fb.alpn} onChange={(e) => {
              const n = [...fallbacks]; n[i] = { ...n[i], alpn: e.target.value }; onChange(n);
            }} />
          </FieldRow>
          <FieldRow label="Path" hint="Match on HTTP path; empty = match all">
            <input className={inputClass} value={fb.path} onChange={(e) => {
              const n = [...fallbacks]; n[i] = { ...n[i], path: e.target.value }; onChange(n);
            }} />
          </FieldRow>
          <FieldRow label="Dest" required hint="Port number, Unix socket, or serve-ws-none">
            <input className={inputClass} value={String(fb.dest)} onChange={(e) => {
              const v = e.target.value;
              const n = [...fallbacks];
              n[i] = { ...n[i], dest: /^\d+$/.test(v) ? parseInt(v, 10) : v };
              onChange(n);
            }} />
          </FieldRow>
          <FieldRow label="xver" hint="Proxy Protocol version forwarded to dest">
            <Select value={String(fb.xver)} onValueChange={(v) => {
              const n = [...fallbacks];
              n[i] = { ...n[i], xver: parseInt(v, 10) as 0 | 1 | 2 };
              onChange(n);
            }}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="0">0 (disabled)</SelectItem>
                <SelectItem value="1">1</SelectItem>
                <SelectItem value="2">2</SelectItem>
              </SelectContent>
            </Select>
          </FieldRow>
          <button type="button" className={btnDangerClass} onClick={() => onChange(fallbacks.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
    </CollapsibleSection>
  );
}
