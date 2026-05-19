"use client";

import { useEffect, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { Stepper } from "@/components/pipeline/stepper";
import { NeonButton } from "@/components/ui/neon-button";
import { useAppStore, PIPELINE_STEPS } from "@/lib/store";

const pathToStep: Record<string, number> = {
  "/donnees": 0,
  "/config": 1,
  "/training": 2,
  "/evaluation": 3,
};

export default function PipelineLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { currentStep, goToStep, sessionId, restoreFromBackend } = useAppStore();

  // APP-P0-4: on first mount, ask the backend whether the user already has
  // an active session and hydrate the store accordingly. Without this, F5
  // on /donnees (or any pipeline page) drops the user back to step 0 even
  // though the backend session is still alive.
  const restoredOnceRef = useRef(false);
  useEffect(() => {
    if (restoredOnceRef.current) return;
    if (sessionId) {
      // Store already has a session — sessionStorage survived, no need to
      // round-trip the backend.
      restoredOnceRef.current = true;
      return;
    }
    restoredOnceRef.current = true;
    void restoreFromBackend();
  }, [sessionId, restoreFromBackend]);

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
    <div className="bg-pipeline relative min-h-screen flex flex-col">
      {/* Stepper */}
      <div className="relative z-10 glass border-b border-white/[0.08] rounded-none">
        <div className="max-w-5xl mx-auto px-4 py-3">
          <Stepper currentStep={activeStep} onStepClick={handleStepClick} />
        </div>
      </div>

      {/* Content — wrapped in <main> by the root layout (id="main-content") */}
      <div className="relative z-10 flex-1 w-full max-w-5xl mx-auto px-4 py-8">
        <motion.div
          key={pathname}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          {children}
        </motion.div>
      </div>

      {/* Footer nav */}
      <footer className="relative z-10 glass border-t border-white/[0.08] rounded-none">
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
