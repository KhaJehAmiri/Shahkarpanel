"use client";

import { cn } from "@/lib/utils";

interface Option {
  value: string;
  label: string;
}

interface SegChoiceProps {
  value: string;
  onChange: (v: string) => void;
  options: Option[];
}

export function SegChoice({ value, onChange, options }: SegChoiceProps) {
  return (
    <div className="flex flex-wrap gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-md px-2.5 py-1.5 text-xs font-medium transition",
            value === o.value
              ? "bg-[var(--accent)] text-white"
              : "text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
