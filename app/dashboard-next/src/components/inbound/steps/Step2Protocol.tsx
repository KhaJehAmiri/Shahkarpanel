"use client";

import { useState } from "react";
import { UseFormReturn } from "react-hook-form";
import { ProtocolCard } from "../shared/ProtocolCard";
import type { InboundFormState, ProtocolDefinition } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
  protocols: ProtocolDefinition[];
  setProtocol: (id: string) => boolean;
}

export function Step2Protocol({ form, protocols, setProtocol }: Props) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const selected = form.watch("protocol");

  const userProtos = protocols.filter((p) => p.category === "user");
  const advancedProtos = protocols.filter((p) => p.category === "advanced");

  const pick = (id: string) => {
    if (id !== selected) setProtocol(id);
    else form.setValue("protocol", id);
  };

  return (
    <div className="px-6 py-4">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-hint)]">Product (User Assignment)</div>
      <div className="mb-4 grid grid-cols-2 gap-3">
        {userProtos.map((p) => (
          <ProtocolCard key={p.id} def={p} selected={selected === p.id} onSelect={() => pick(p.id)} />
        ))}
      </div>
      {!showAdvanced ? (
        <button type="button" className="text-xs font-medium text-[var(--accent)] underline" onClick={() => setShowAdvanced(true)}>
          Show advanced protocols
        </button>
      ) : (
        <>
          <div className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-[var(--text-hint)]">Advanced (No User Assignment)</div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {advancedProtos.map((p) => (
              <ProtocolCard key={p.id} def={p} selected={selected === p.id} onSelect={() => pick(p.id)} />
            ))}
          </div>
          <button type="button" className="mt-3 text-xs font-medium text-[var(--accent)] underline" onClick={() => setShowAdvanced(false)}>
            Hide advanced protocols
          </button>
        </>
      )}
    </div>
  );
}
