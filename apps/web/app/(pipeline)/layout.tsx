"use client";

import { useRouter, usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowLeft, ArrowRight, LogOut } from "lucide-react";
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
  const { mode, currentStep, prevStep, nextStep, goToStep, reset } =
    useAppStore();

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

  function handleQuit() {
    reset();
    router.push("/");
  }

  const modeLabel =
    mode === "tv" ? "Modele TV" : mode === "pl" ? "Modele PL" : "Pipeline";

  return (
    <div className="relative min-h-screen flex flex-col">
      <AuroraBg />

      {/* Header */}
      <header className="relative z-10 glass border-b border-border/50 rounded-none">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="px-3 py-1 rounded-lg bg-accent/10 text-accent text-xs font-bold uppercase tracking-wide">
              {modeLabel}
            </div>
          </div>
          <NeonButton
            variant="ghost"
            onClick={handleQuit}
            icon={<LogOut size={14} />}
            className="text-xs"
          >
            Quitter
          </NeonButton>
        </div>
        <div className="max-w-4xl mx-auto px-4 pb-3">
          <Stepper currentStep={activeStep} onStepClick={handleStepClick} />
        </div>
      </header>

      {/* Content */}
      <main className="relative z-10 flex-1 w-full max-w-4xl mx-auto px-4 py-8">
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
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between">
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
