"use client";

import { useRouter, usePathname } from "next/navigation";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { Stepper } from "@/components/pipeline/stepper";
import { Button } from "@/components/ui/button";
import { useAppStore, PIPELINE_STEPS } from "@/lib/store";

const pathToStep: Record<string, number> = {
  "/donnees": 0,
  "/config": 1,
  "/training": 2,
  "/evaluation": 3,
  "/extrapolation": 4,
};

export default function PipelineLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { currentStep, goToStep } = useAppStore();

  const activeStep = pathToStep[pathname] ?? currentStep;

  function handleStepClick(step: number) {
    goToStep(step);
    router.push(PIPELINE_STEPS[step].path);
  }

  function handleBack() {
    if (activeStep > 0) {
      const prev = activeStep - 1;
      goToStep(prev);
      router.push(PIPELINE_STEPS[prev].path);
    }
  }

  function handleNext() {
    if (activeStep < PIPELINE_STEPS.length - 1) {
      const next = activeStep + 1;
      goToStep(next);
      router.push(PIPELINE_STEPS[next].path);
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-bg">
      {/* Stepper */}
      <div className="border-b border-border bg-bg/95 backdrop-blur supports-[backdrop-filter]:bg-bg/80 sticky top-12 z-30">
        <div className="max-w-5xl mx-auto px-4 py-3">
          <Stepper currentStep={activeStep} onStepClick={handleStepClick} />
        </div>
      </div>

      {/* Content */}
      <main className="flex-1 w-full max-w-5xl mx-auto px-4 py-8">
        {children}
      </main>

      {/* Footer nav */}
      <footer className="border-t border-border bg-bg-elevated/60">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleBack}
            disabled={activeStep === 0}
            icon={<ArrowLeft size={14} aria-hidden="true" />}
          >
            Retour
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleNext}
            disabled={activeStep === PIPELINE_STEPS.length - 1}
            iconAfter={<ArrowRight size={14} aria-hidden="true" />}
          >
            Continuer
          </Button>
        </div>
      </footer>
    </div>
  );
}
