"use client";

import { Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface FieldRowProps {
  label: string;
  required?: boolean;
  hint?: string;
  error?: string;
  tooltip?: string;
  children: React.ReactNode;
  className?: string;
}

export function FieldRow({
  label,
  required,
  hint,
  error,
  tooltip,
  children,
  className,
}: FieldRowProps) {
  return (
    <div className={cn("mb-4 w-full", className)}>
      <div className="mb-1.5 flex items-center gap-1.5">
        <label className="text-sm font-medium text-[var(--text)]">
          {label}
          {required && <span className="ml-0.5 text-red-400">*</span>}
        </label>
        {tooltip && (
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="text-[var(--text-hint)] hover:text-[var(--text-muted)]">
                  <Info className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent>{tooltip}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-[var(--text-hint)]">{hint}</p>}
      {error && <p className="mt-1 text-xs text-red-400">{error}</p>}
    </div>
  );
}

export const inputClass =
  "w-full rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]/30";

export const btnSecondaryClass =
  "rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-1.5 text-xs font-medium text-[var(--text)] transition hover:bg-[var(--surface)]";

export const btnPrimaryClass =
  "rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white transition hover:bg-[var(--accent-hover)]";

export const btnDangerClass =
  "rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-1 text-xs text-red-400 transition hover:bg-red-500/20";
