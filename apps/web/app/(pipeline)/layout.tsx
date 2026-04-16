"use client";

import { useRouter, usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { AuroraBg } from "@/components/backgrounds/aurora-bg";
import { Stepper } from "@/components/pipeline/stepper";
import { NeonButton } from "@/components/ui/neon-button";
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
    <div className="relative min-h-screen flex flex-col">
      <AuroraBg />

      {/* Stepper */}
      <div className="relative z-10 glass border-b border-border/50 rounded-none">
        <div className="max-w-5xl mx-auto px-4 py-3">
          <Stepper currentStep={activeStep} onStepClick={handleStepClick} />
        </div>
      </div>

      {/* Content */}
      <main className="relative z-10 flex-1 w-full max-w-5xl mx-auto px-4 py-8">
        <motion.div
          key={pathname}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          {children}
        </motion.div>
      </main>

      {/* Footer nav */}
      <footer className="relative z-10 glass border-t border-border/50 rounded-none">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <NeonButton
            variant="ghost"
            onClick={handleBack}
            disabled={activeStep === 0}
            icon={<ArrowLeft size={14} />}
          >
            Retour
          </NeonButton>
          <NeonButton
            onClick={handleNext}
            disabled={activeStep === PIPELINE_STEPS.length - 1}
            icon={<ArrowRight size={14} />}
          >
            Continuer
          </NeonButton>
        </div>
      </footer>
    </div>
  );
}
