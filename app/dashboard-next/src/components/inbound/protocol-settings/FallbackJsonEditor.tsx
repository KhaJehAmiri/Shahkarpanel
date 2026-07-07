"use client";

import { useState } from "react";
import { UseFormReturn } from "react-hook-form";
import { FieldRow, inputClass } from "../shared/FieldRow";
import type { InboundFormState } from "../types";

interface Props {
  form: UseFormReturn<InboundFormState>;
  protocolLabel: string;
  errors: Record<string, string>;
}

export function FallbackJsonEditor({ form, protocolLabel, errors }: Props) {
  const { watch, setValue } = form;
  const [raw, setRaw] = useState(() => JSON.stringify(watch("customSettings"), null, 2));
  const [parseError, setParseError] = useState<string | undefined>();

  const onBlur = () => {
    try {
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      setValue("customSettings", parsed);
      setParseError(undefined);
    } catch {
      setParseError("Invalid JSON syntax");
    }
  };

  return (
    <>
      <p className="mb-3 text-sm text-[var(--text-muted)]">
        Configure settings for custom protocol <strong className="text-[var(--text)]">{protocolLabel}</strong> as raw JSON matching xray-core documentation.
      </p>
      <FieldRow label="Settings JSON" error={parseError || errors["customSettings"]}>
        <textarea
          className={`${inputClass} min-h-[200px] font-mono text-xs`}
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          onBlur={onBlur}
          spellCheck={false}
        />
      </FieldRow>
    </>
  );
}
