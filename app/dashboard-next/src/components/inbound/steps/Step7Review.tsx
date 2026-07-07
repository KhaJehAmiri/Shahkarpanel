"use client";

import { useMemo, useState } from "react";
import { Copy, ChevronDown } from "lucide-react";
import { UseFormReturn } from "react-hook-form";
import { btnSecondaryClass } from "../shared/FieldRow";
import type { InboundFormState, ProtocolDefinition, StepId } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
  protocols: ProtocolDefinition[];
  activeSteps: StepId[];
  getXrayJson: () => Record<string, unknown>;
  onEditStep: (index: number) => void;
}

function SummaryCard({
  title,
  stepIndex,
  children,
  onEdit,
}: {
  title: string;
  stepIndex: number;
  children: React.ReactNode;
  onEdit: (i: number) => void;
}) {
  return (
    <div className="mb-3 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-4">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-sm font-semibold text-[var(--text)]">{title}</h4>
        <button type="button" className="text-xs text-[var(--accent)] hover:underline" onClick={() => onEdit(stepIndex)}>Edit</button>
      </div>
      <div className="space-y-1 text-xs text-[var(--text-muted)]">{children}</div>
    </div>
  );
}

export function Step7Review({ form, protocols, activeSteps, getXrayJson, onEditStep }: Props) {
  const [jsonOpen, setJsonOpen] = useState(false);
  const values = form.watch();
  const def = protocols.find((p) => p.id === values.protocol);
  const jsonStr = useMemo(() => JSON.stringify(getXrayJson(), null, 2), [getXrayJson, values]);

  const stepIdx = (id: StepId) => activeSteps.indexOf(id);

  return (
    <div className="px-6 py-4">
      <SummaryCard title="Basics" stepIndex={stepIdx("basics")} onEdit={onEditStep}>
        <p>Remark: <strong className="text-[var(--text)]">{values.basics.remark || "—"}</strong></p>
        {values.protocol !== "tun" && (
          <>
            <p>Listen: {values.basics.listen}</p>
            <p>Port: {values.basics.port}</p>
          </>
        )}
      </SummaryCard>

      <SummaryCard title="Protocol" stepIndex={stepIdx("protocol")} onEdit={onEditStep}>
        <p>Protocol: <strong className="text-[var(--text)]">{def?.label ?? values.protocol}</strong></p>
      </SummaryCard>

      <SummaryCard title="Settings" stepIndex={stepIdx("settings")} onEdit={onEditStep}>
        <p>Configured for {def?.label ?? values.protocol}</p>
      </SummaryCard>

      {activeSteps.includes("stream") && (
        <SummaryCard title="Stream" stepIndex={stepIdx("stream")} onEdit={onEditStep}>
          <p>Transport: <strong className="text-[var(--text)]">{values.network.toUpperCase()}</strong></p>
        </SummaryCard>
      )}

      {activeSteps.includes("security") && (
        <SummaryCard title="Security" stepIndex={stepIdx("security")} onEdit={onEditStep}>
          <p>Security: <strong className="text-[var(--text)]">{values.security.toUpperCase()}</strong></p>
        </SummaryCard>
      )}

      {activeSteps.includes("sniffing") && (
        <SummaryCard title="Sniffing" stepIndex={stepIdx("sniffing")} onEdit={onEditStep}>
          <p>Enabled: {values.sniffing.enabled ? "Yes" : "No"}</p>
        </SummaryCard>
      )}

      <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)]">
        <button type="button" className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-[var(--text)]" onClick={() => setJsonOpen(!jsonOpen)}>
          JSON Preview
          <ChevronDown className={`h-4 w-4 transition-transform ${jsonOpen ? "rotate-180" : ""}`} />
        </button>
        {jsonOpen && (
          <div className="border-t border-[var(--border)] p-4">
            <div className="mb-2 flex justify-end">
              <button type="button" className={btnSecondaryClass} onClick={() => navigator.clipboard.writeText(jsonStr)}>
                <Copy className="mr-1 inline h-3.5 w-3.5" /> Copy JSON
              </button>
            </div>
            <pre className="max-h-64 overflow-auto rounded-lg bg-[var(--bg)] p-3 font-mono text-xs leading-relaxed text-[var(--text-muted)]">{jsonStr}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
