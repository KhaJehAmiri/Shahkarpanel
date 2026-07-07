"use client";

import { Plus, Trash2 } from "lucide-react";
import { FieldRow, inputClass, btnSecondaryClass, btnDangerClass } from "./FieldRow";

interface KeyValueRepeaterProps {
  value: Record<string, string[]>;
  onChange: (v: Record<string, string[]>) => void;
  label?: string;
}

export function KeyValueRepeater({ value, onChange, label = "Headers" }: KeyValueRepeaterProps) {
  const entries = Object.entries(value);

  const updateKey = (oldKey: string, newKey: string, vals: string[]) => {
    const next = { ...value };
    delete next[oldKey];
    if (newKey.trim()) next[newKey.trim()] = vals;
    onChange(next);
  };

  const addRow = () => onChange({ ...value, "": [""] });

  return (
    <div className="w-full">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-[var(--text)]">{label}</span>
        <button type="button" className={btnSecondaryClass} onClick={addRow}>
          <Plus className="mr-1 inline h-3.5 w-3.5" /> Add
        </button>
      </div>
      {entries.length === 0 && (
        <p className="text-xs text-[var(--text-hint)]">No entries. Click Add to create one.</p>
      )}
      {entries.map(([key, vals], i) => (
        <div key={`${key}-${i}`} className="mb-2 flex gap-2">
          <input
            className={`${inputClass} w-1/3`}
            placeholder="Header name"
            value={key}
            onChange={(e) => updateKey(key, e.target.value, vals)}
          />
          <input
            className={`${inputClass} flex-1`}
            placeholder="Values (comma-separated)"
            value={vals.join(", ")}
            onChange={(e) =>
              updateKey(
                key,
                key,
                e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
              )
            }
          />
          <button type="button" className={btnDangerClass} onClick={() => {
            const next = { ...value };
            delete next[key];
            onChange(next);
          }}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
