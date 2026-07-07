"use client";

import { Plus, Trash2 } from "lucide-react";
import { UseFormReturn } from "react-hook-form";
import {
  TCP_MASK_TYPES,
  emptyTcpMask,
  type InboundFormState,
  type TcpMaskEntry,
} from "../types";
import { FieldRow, inputClass, btnDangerClass, btnPrimaryClass } from "../shared/FieldRow";
import { StringListEditor } from "../shared/StringListEditor";
import { CollapsibleSection } from "../shared/CollapsibleSection";

interface Props {
  form: UseFormReturn<InboundFormState>;
  /** When set, edits mkcp UDP masks instead of stream TCP masks. */
  udpMode?: boolean;
}

export function TcpMaskRepeater({ form, udpMode = false }: Props) {
  const { watch, setValue } = form;
  const masks = udpMode ? watch("mkcpSettings.udpMasks") : watch("tcpMasks");

  const setMasks = (next: TcpMaskEntry[]) => {
    if (udpMode) setValue("mkcpSettings.udpMasks", next, { shouldDirty: true });
    else setValue("tcpMasks", next, { shouldDirty: true });
  };

  const addMask = () => setMasks([...masks, emptyTcpMask()]);

  const updateMask = (idx: number, patch: Partial<TcpMaskEntry>) =>
    setMasks(masks.map((m, i) => (i === idx ? { ...m, ...patch } : m)));

  const updateSettings = (idx: number, patch: Partial<TcpMaskEntry["settings"]>) =>
    setMasks(
      masks.map((m, i) =>
        i === idx ? { ...m, settings: { ...m.settings, ...patch } } : m,
      ),
    );

  const removeMask = (idx: number) => setMasks(masks.filter((_, i) => i !== idx));

  return (
    <CollapsibleSection
      title={udpMode ? "UDP Masks (mKCP)" : "TCP Masks"}
      defaultOpen={masks.length > 0}
      action={
        <button type="button" className={btnPrimaryClass} onClick={addMask}>
          <Plus className="mr-1 inline h-3.5 w-3.5" /> Add
        </button>
      }
    >
      {masks.length === 0 ? (
        <p className="text-xs text-[var(--text-hint)]">
          FinalMask / noises for TCP (fragment, noise). Click Add to create a mask.
        </p>
      ) : (
        <div className="space-y-4">
          {masks.map((mask, idx) => (
            <div
              key={idx}
              className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4"
            >
              <div className="mb-3 flex items-center justify-between">
                <span className="text-sm font-medium text-[var(--text)]">TCP Mask {idx + 1}</span>
                <button type="button" className={btnDangerClass} onClick={() => removeMask(idx)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>

              <FieldRow label="Type">
                <select
                  className={inputClass}
                  value={mask.type}
                  onChange={(e) => updateMask(idx, { type: e.target.value as TcpMaskEntry["type"] })}
                >
                  {TCP_MASK_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </FieldRow>

              <FieldRow label="Packets" hint="e.g. 1-3 or tlshello">
                <input
                  className={inputClass}
                  value={mask.settings.packets}
                  onChange={(e) => updateSettings(idx, { packets: e.target.value })}
                  dir="ltr"
                />
              </FieldRow>

              <StringListEditor
                label="Lengths"
                values={mask.settings.lengths}
                onChange={(lengths) => updateSettings(idx, { lengths })}
                placeholder="100-200"
              />

              <StringListEditor
                label="Delays"
                values={mask.settings.delays}
                onChange={(delays) => updateSettings(idx, { delays })}
                placeholder="10-20"
              />

              <FieldRow label="Max Split" hint="Int32Range, e.g. 3-6; empty = unlimited">
                <input
                  className={inputClass}
                  value={mask.settings.maxSplit}
                  onChange={(e) => updateSettings(idx, { maxSplit: e.target.value })}
                  dir="ltr"
                />
              </FieldRow>
            </div>
          ))}
        </div>
      )}
    </CollapsibleSection>
  );
}
