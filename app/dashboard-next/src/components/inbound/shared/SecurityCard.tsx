"use client";

import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface SecurityCardProps {
  id: string;
  label: string;
  description: string;
  selected: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onSelect: () => void;
}

export function SecurityCard({
  id,
  label,
  description,
  selected,
  disabled,
  disabledReason,
  onSelect,
}: SecurityCardProps) {
  const card = (
    <button
      type="button"
      id={id}
      disabled={disabled}
      onClick={() => !disabled && onSelect()}
      className={cn(
        "rounded-xl border-2 p-4 text-left transition-all",
        disabled && "cursor-not-allowed opacity-40",
        selected && !disabled
          ? "border-[var(--accent)] bg-[var(--accent)]/10"
          : "border-[var(--border)] bg-[var(--surface-2)] hover:border-[var(--accent)]/50",
      )}
    >
      <div className="mb-1 text-sm font-semibold text-[var(--text)]">{label}</div>
      <div className="text-xs leading-relaxed text-[var(--text-hint)]">{description}</div>
    </button>
  );

  if (disabled && disabledReason) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>{card}</TooltipTrigger>
          <TooltipContent>{disabledReason}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }
  return card;
}
