"use client";

import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { PIPELINE_STEPS } from "@/lib/store";

interface StepperProps {
  currentStep: number;
  onStepClick?: (step: number) => void;
}

export function Stepper({ currentStep, onStepClick }: StepperProps) {
  return (
    <nav
      aria-label="Etapes du pipeline"
      className="w-full"
    >
      <ol className="flex items-center justify-between gap-2">
        {PIPELINE_STEPS.map((step, idx) => {
          const isCompleted = idx < currentStep;
          const isActive = idx === currentStep;
          const isFuture = idx > currentStep;

          return (
            <li key={step.id} className="flex items-center flex-1 last:flex-none">
              <button
                type="button"
                onClick={() => onStepClick?.(idx)}
                disabled={isFuture}
                aria-current={isActive ? "step" : undefined}
                aria-disabled={isFuture || undefined}
                className={cn(
                  "flex items-center gap-2 rounded px-1 py-1 transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  isFuture && "opacity-60 cursor-not-allowed",
                  !isFuture && "cursor-pointer hover:bg-bg-subtle"
                )}
              >
                <span
                  className={cn(
                    "w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-semibold border transition-colors shrink-0",
                    isCompleted &&
                      "bg-accent border-accent text-accent-fg",
                    isActive &&
                      "bg-accent-subtle border-accent text-accent",
                    isFuture &&
                      "bg-bg-elevated border-border text-text-muted"
                  )}
                >
                  {isCompleted ? <Check size={12} aria-hidden="true" /> : idx + 1}
                </span>
                <span
                  className={cn(
                    "text-xs font-medium hidden sm:block whitespace-nowrap",
                    isActive && "text-text",
                    isCompleted && "text-text-muted",
                    isFuture && "text-text-subtle"
                  )}
                >
                  {step.label}
                </span>
              </button>

              {idx < PIPELINE_STEPS.length - 1 && (
                <div className="flex-1 mx-2 h-px">
                  <div
                    className={cn(
                      "h-full transition-colors",
                      idx < currentStep ? "bg-accent" : "bg-border"
                    )}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
