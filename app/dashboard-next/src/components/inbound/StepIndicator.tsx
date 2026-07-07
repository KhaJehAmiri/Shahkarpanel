"use client";

import { cn } from "@/lib/utils";
import { STEP_LABELS, type StepId } from "./types";

interface StepIndicatorProps {
  activeSteps: StepId[];
  currentIndex: number;
  onStepClick?: (index: number) => void;
  /** Step indices that have validation errors (shown after save attempt). */
  errorSteps?: number[];
}

export function StepIndicator({
  activeSteps,
  currentIndex,
  onStepClick,
  errorSteps = [],
}: StepIndicatorProps) {
  return (
    <div className="inbound-tab-bar" role="tablist">
      {activeSteps.map((stepId, i) => {
        const active = i === currentIndex;
        const hasError = errorSteps.includes(i);
        const label = STEP_LABELS[stepId];
        return (
          <button
            key={stepId}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onStepClick?.(i)}
            className={cn(
              "inbound-tab",
              active && "inbound-tab--active",
              hasError && "inbound-tab--error",
            )}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
