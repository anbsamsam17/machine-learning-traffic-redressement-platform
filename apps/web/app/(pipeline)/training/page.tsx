"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { toast } from "sonner";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { TrainingProgress } from "@/components/pipeline/training-progress";
import { NeonButton } from "@/components/ui/neon-button";
import { useAppStore } from "@/lib/store";
import { BarChart3 } from "lucide-react";

export default function TrainingPage() {
  const router = useRouter();
  const { sessionId, nextStep, mode } = useAppStore();

  const handleComplete = useCallback(() => {
    toast.success("Entrainement termine avec succes !");
  }, []);

  function goToEvaluation() {
    nextStep();
    router.push("/evaluation");
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <GradientText as="h2" className="text-2xl">
          Entrainement
        </GradientText>
        <p className="text-sm text-muted">
          Entrainement grid search des modeles{" "}
          {mode === "pl" ? "PL" : "TV"}. Suivez la progression en temps
          reel.
        </p>
      </div>

      <GlowCard>
        {sessionId ? (
          <TrainingProgress
            sessionId={sessionId}
            onComplete={handleComplete}
          />
        ) : (
          <div className="text-center py-12 space-y-4">
            <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center mx-auto text-accent">
              <BarChart3 size={28} />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">
                En attente du lancement
              </p>
              <p className="text-xs text-muted mt-1">
                L&apos;entrainement demarrera automatiquement apres la
                configuration. Si cette page est atteinte directement, retournez
                a la page de configuration.
              </p>
            </div>
          </div>
        )}
      </GlowCard>

      {!sessionId && (
        <div className="flex justify-end">
          <NeonButton onClick={goToEvaluation}>
            Passer a l&apos;evaluation
          </NeonButton>
        </div>
      )}
    </div>
  );
}
