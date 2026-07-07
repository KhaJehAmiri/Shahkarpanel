"use client";

import { Plus, Trash2 } from "lucide-react";
import { btnDangerClass, btnSecondaryClass, inputClass } from "./FieldRow";

interface StringListEditorProps {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}

export function StringListEditor({ label, values, onChange, placeholder }: StringListEditorProps) {
  const add = () => onChange([...values, ""]);
  const update = (idx: number, v: string) => onChange(values.map((x, i) => (i === idx ? v : x)));
  const remove = (idx: number) => onChange(values.filter((_, i) => i !== idx));

  return (
    <div className="w-full">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-[var(--text-muted)]">{label}</span>
        <button type="button" className={btnSecondaryClass} onClick={add}>
          <Plus className="mr-1 inline h-3.5 w-3.5" /> Add
        </button>
      </div>
      {values.length === 0 && (
        <p className="text-xs text-[var(--text-hint)]">No entries</p>
      )}
      {values.map((val, idx) => (
        <div key={idx} className="mb-2 flex items-center gap-2">
          <span className="w-6 text-xs text-[var(--text-hint)]">#{idx + 1}</span>
          <input
            className={`${inputClass} flex-1`}
            value={val}
            placeholder={placeholder}
            onChange={(e) => update(idx, e.target.value)}
            dir="ltr"
          />
          <button type="button" className={btnDangerClass} onClick={() => remove(idx)}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
