"use client";

import { useState, KeyboardEvent } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface TagInputProps {
  value: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
  hint?: string;
  onRegenerate?: (index: number) => void;
  className?: string;
}

export function TagInput({
  value,
  onChange,
  placeholder = "Type and press Enter",
  hint,
  onRegenerate,
  className,
}: TagInputProps) {
  const [input, setInput] = useState("");

  const addTag = (raw: string) => {
    const tag = raw.trim().replace(/,$/, "");
    if (!tag || value.includes(tag)) return;
    onChange([...value, tag]);
    setInput("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(input);
    } else if (e.key === "Backspace" && !input && value.length) {
      onChange(value.slice(0, -1));
    }
  };

  return (
    <div className={cn("w-full", className)}>
      <div className="flex min-h-[42px] flex-wrap gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-2 focus-within:border-[var(--accent)] focus-within:ring-1 focus-within:ring-[var(--accent)]/30">
        {value.map((tag, i) => (
          <span
            key={`${tag}-${i}`}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-0.5 text-xs text-[var(--text)]"
          >
            {tag}
            {onRegenerate && (
              <button type="button" onClick={() => onRegenerate(i)} className="text-[var(--text-hint)] hover:text-[var(--accent)]" title="Regenerate">↻</button>
            )}
            <button type="button" onClick={() => onChange(value.filter((_, j) => j !== i))} className="text-[var(--text-hint)] hover:text-red-400">
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => input && addTag(input)}
          placeholder={value.length ? "" : placeholder}
          className="min-w-[120px] flex-1 bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-hint)]"
        />
      </div>
      {hint && <p className="mt-1 text-xs text-[var(--text-hint)]">{hint}</p>}
    </div>
  );
}
