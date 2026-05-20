"use client";

import { useEffect, useRef } from "react";
import {
  Check,
  Database,
  Settings2,
  Brain,
  LineChart,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { PIPELINE_STEPS } from "@/lib/store";
import { stepperTransition } from "@/lib/animations/gsap";

interface StepperProps {
  currentStep: number;
  onStepClick?: (step: number) => void;
  /**
   * Optional per-step "ready" flag — when provided, completed/ready steps get
   * the cyan check badge, future steps stay neutral. Even "not ready" steps
   * remain clickable: the user can navigate freely (Tache 1).
   */
  stepReady?: boolean[];
}

// Icons keyed by step index (donnees, config, training, evaluation).
// We use lucide-react icons (no emojis) per project conventions.
const STEP_ICONS: LucideIcon[] = [Database, Settings2, Brain, LineChart];

export function Stepper({ currentStep, onStepClick, stepReady }: StepperProps) {
  const navRef = useRef<HTMLElement>(null);
  const prevStepRef = useRef<number>(currentStep);

  // M1 — animate stepper transitions when the active step changes.
  useEffect(() => {
    if (prevStepRef.current === currentStep) return;
    prevStepRef.current = currentStep;

    const nav = navRef.current;
    if (!nav) return;
    const activeEl = nav.querySelector<HTMLElement>(`[data-step="${currentStep}"]`);
    const connectors = Array.from(
      nav.querySelectorAll<HTMLElement>(`[data-step-connector][data-completed="true"]`)
    );
    const cleanup = stepperTransition(activeEl, connectors, nav);
    return cleanup;
  }, [currentStep]);

  return (
    <nav ref={navRef} aria-label="Etapes du pipeline" className="w-full">
      <ol className="flex items-stretch justify-between gap-2 sm:gap-3">
        {PIPELINE_STEPS.map((step, idx) => {
          const isActive = idx === currentStep;
          // A step is "completed/ready" when (a) it lies strictly before the
          // current step, OR (b) the parent provided an explicit ready flag.
          // We deliberately DO NOT disable future steps — the user can jump
          // freely through the pipeline (Tache 1).
          const isCompleted =
            (stepReady?.[idx] ?? false) || idx < currentStep;
          const Icon = STEP_ICONS[idx] ?? Database;

          return (
            <li key={step.id} className="flex items-center flex-1 last:flex-none min-w-0">
              <button
                type="button"
                data-step={idx}
                onClick={() => onStepClick?.(idx)}
                aria-current={isActive ? "step" : undefined}
                title={`Etape ${idx + 1} — ${step.label}`}
                className={cn(
                  // Larger touch target (min-h-11 = 44px) + group for hover FX
                  "group relative flex w-full min-h-11 items-center gap-2.5 sm:gap-3 rounded-xl border px-3 py-2 transition-all duration-200",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
                  "cursor-pointer",
                  isActive &&
                    "border-accent bg-accent-subtle shadow-[0_0_24px_-4px_rgba(99,102,241,0.55)] animate-pulse-glow",
                  !isActive && isCompleted &&
                    "border-accent/40 bg-bg-elevated hover:border-accent hover:bg-accent-subtle/50",
                  !isActive && !isCompleted &&
                    "border-border bg-bg-elevated/60 hover:border-accent/40 hover:bg-bg-subtle"
                )}
              >
                <span
                  className={cn(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border text-[12px] font-bold transition-colors",
                    isActive &&
                      "bg-accent border-accent text-accent-fg",
                    !isActive && isCompleted &&
                      "bg-accent/15 border-accent/60 text-accent",
                    !isActive && !isCompleted &&
                      "bg-bg border-border text-text-muted group-hover:text-text"
                  )}
                  aria-hidden="true"
                >
                  {isCompleted && !isActive ? (
                    <Check size={14} />
                  ) : (
                    <Icon size={14} />
                  )}
                </span>
                <span className="flex min-w-0 flex-col items-start leading-tight">
                  <span
                    className={cn(
                      "text-[10px] uppercase tracking-wider font-semibold",
                      isActive ? "text-accent" : "text-text-subtle"
                    )}
                  >
                    Etape {idx + 1}
                  </span>
                  <span
                    className={cn(
                      "text-xs sm:text-sm font-medium truncate hidden sm:block",
                      isActive && "text-text",
                      !isActive && isCompleted && "text-text-muted",
                      !isActive && !isCompleted && "text-text-subtle group-hover:text-text-muted"
                    )}
                  >
                    {step.label}
                  </span>
                </span>
              </button>

              {idx < PIPELINE_STEPS.length - 1 && (
                <div className="flex-1 mx-1.5 sm:mx-2 h-px hidden md:block">
                  <div
                    data-step-connector
                    data-completed={isCompleted ? "true" : "false"}
                    className={cn(
                      "h-full transition-colors",
                      isCompleted ? "bg-accent/60" : "bg-border"
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
