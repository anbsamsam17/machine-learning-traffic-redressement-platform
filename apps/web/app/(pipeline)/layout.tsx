"use client";

import { useEffect, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { toast } from "sonner";
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
  const {
    currentStep,
    goToStep,
    sessionId,
    restoreFromBackend,
    mappingValidated,
    previewReady,
    trainingConfig,
  } = useAppStore();

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
    // Tache 1: navigation libre — l'utilisateur peut sauter sur n'importe
    // quelle etape, meme si les prerequis ne sont pas remplis. La page cible
    // affichera un empty-state inline si besoin.
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

  // Per-step readiness flags — used by the Stepper to render the cyan check
  // badge on steps whose prerequisites are met. Note: this is purely VISUAL,
  // every step remains clickable (Tache 1).
  const stepReady: boolean[] = [
    Boolean(sessionId && mappingValidated && previewReady), // 0 Donnees
    Boolean(trainingConfig),                                // 1 Configuration
    false, // 2 Entrainement — has no persistent "done" flag in the store
    false, // 3 Evaluation
  ];

  // Informational "why is the next button greyed?" hint — does NOT block
  // clicks anymore. The button itself stays enabled so users can always
  // advance; pages render an empty-state when prerequisites are missing.
  function getNextHint(step: number): string | null {
    if (step === 0) {
      if (!sessionId) return "Astuce : charge un fichier sur l'etape Donnees";
      if (!mappingValidated || !previewReady)
        return "Astuce : valide le mapping des colonnes pour activer la suite";
    }
    if (step === 1) {
      if (!trainingConfig) return "Astuce : enregistre une configuration pour activer l'entrainement";
    }
    if (step === 2) {
      if (!sessionId) return "Astuce : importe d'abord un jeu de donnees";
    }
    return null;
  }

  const nextHint = getNextHint(activeStep);
  const isLastStep = activeStep === PIPELINE_STEPS.length - 1;

  function handleNext() {
    if (activeStep >= PIPELINE_STEPS.length - 1) return;
    const hint = getNextHint(activeStep);
    if (hint) {
      // On informe mais on n'empeche plus la navigation (Tache 1).
      toast.info(hint);
    }
    const next = activeStep + 1;
    goToStep(next);
    router.push(PIPELINE_STEPS[next].path);
  }

  return (
    <div className="bg-pipeline relative min-h-screen flex flex-col">
      {/* Stepper — mis en evidence pour permettre la navigation libre entre
          etapes (Tache 1 + 2). Largeur etendue + padding genereux. */}
      <div className="sticky top-12 z-30 glass border-b border-white/[0.08] rounded-none backdrop-blur-md">
        <div className="max-w-6xl mx-auto px-4 py-4 sm:py-5">
          <Stepper
            currentStep={activeStep}
            onStepClick={handleStepClick}
            stepReady={stepReady}
          />
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
            disabled={isLastStep}
            icon={<ArrowRight size={14} />}
            title={nextHint ?? undefined}
          >
            Continuer
          </NeonButton>
        </div>
      </footer>
    </div>
  );
}
