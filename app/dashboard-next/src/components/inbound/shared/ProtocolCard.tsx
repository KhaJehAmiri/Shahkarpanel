"use client";

import {
  Zap, Hexagon, Shield, Lock, Globe, Network, Shuffle, KeyRound, Wind, Radio, Satellite, DoorOpen, Box,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ProtocolDefinition } from "../types";

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  Zap, Hexagon, Shield, Lock, Globe, Network, Shuffle, KeyRound, Wind, Radio, Satellite, DoorOpen, Box,
};

interface ProtocolCardProps {
  def: ProtocolDefinition;
  selected: boolean;
  onSelect: () => void;
}

export function ProtocolCard({ def, selected, onSelect }: ProtocolCardProps) {
  const Icon = ICONS[def.icon] ?? Box;
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "rounded-xl border-2 p-4 text-left transition-all",
        selected
          ? "border-[var(--accent)] bg-[var(--accent)]/10"
          : "border-[var(--border)] bg-[var(--surface-2)] hover:border-[var(--accent)]/50",
      )}
    >
      <Icon className="mb-2 h-5 w-5 text-[var(--accent)]" />
      <div className="mb-1 text-sm font-semibold text-[var(--text)]">{def.label}</div>
      <div className="text-xs leading-relaxed text-[var(--text-hint)]">{def.description}</div>
    </button>
  );
}
