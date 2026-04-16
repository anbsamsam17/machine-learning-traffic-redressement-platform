"use client";

import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { PIPELINE_STEPS } from "@/lib/store";

interface StepperProps {
  currentStep: number;
  onStepClick?: (step: number) => void;
}

export function Stepper({ currentStep, onStepClick }: StepperProps) {
  return (
    <nav className="w-full px-4 py-3">
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
                className={cn(
                  "flex items-center gap-2 group transition-all",
                  isFuture && "opacity-50 cursor-not-allowed",
                  !isFuture && "cursor-pointer"
                )}
              >
                <motion.div
                  initial={false}
                  animate={{
                    scale: isActive ? 1.15 : 1,
                    boxShadow: isActive
                      ? "0 0 20px rgba(99,102,241,0.4)"
                      : "0 0 0px transparent",
                  }}
                  className={cn(
                    "w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-colors flex-shrink-0",
                    isCompleted &&
                      "bg-indigo-500 border-indigo-500 text-white",
                    isActive &&
                      "bg-indigo-500/20 border-indigo-400 text-indigo-300",
                    isFuture &&
                      "bg-slate-800/50 border-slate-600/50 text-slate-400"
                  )}
                >
                  {isCompleted ? <Check size={14} /> : idx + 1}
                </motion.div>
                <span
                  className={cn(
                    "text-xs font-medium hidden sm:block whitespace-nowrap",
                    isActive && "text-indigo-300",
                    isCompleted && "text-slate-200",
                    isFuture && "text-slate-400"
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
                      idx < currentStep ? "bg-indigo-500" : "bg-white/10"
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
