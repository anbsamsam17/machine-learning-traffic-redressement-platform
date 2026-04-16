"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { ConfigForm, type TrainingConfig } from "@/components/pipeline/config-form";
import { useAppStore } from "@/lib/store";

export default function ConfigPage() {
  const router = useRouter();
  const { mode, sessionId, nextStep } = useAppStore();
  const [availableColumns, setAvailableColumns] = useState<string[]>([]);

  // Fetch the columns from the learning table in the session
  useEffect(() => {
    if (!sessionId) return;
    fetch("/api/mapping/auto", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.source_columns) {
          setAvailableColumns(data.source_columns);
        }
      })
      .catch(() => {});
  }, [sessionId]);

  function handleSubmit(config: TrainingConfig) {
    if (!sessionId) {
      toast.error("Pas de session active. Importez d'abord un fichier.");
      return;
    }

    // Store the training config in Zustand for the training page to use
    useAppStore.getState().setTrainingConfig({
      ...config,
      session_id: sessionId,
    });

    toast.success("Configuration enregistree");
    nextStep();
    router.push("/training");
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <GradientText as="h2" className="text-2xl">
          Configuration {mode === "pl" ? "PL" : "TV"}
        </GradientText>
        <p className="text-sm text-muted">
          Definissez les colonnes d&apos;entree, les hyperparametres et la
          grille de recherche pour l&apos;entrainement{" "}
          <span className="font-semibold text-indigo-300">
            {mode === "pl" ? "Poids Lourds" : "Tous Vehicules"}
          </span>
          .
        </p>
        {!sessionId && (
          <p className="text-sm text-amber-400">
            Aucune session active. Retournez a l&apos;etape Donnees pour
            importer un fichier.
          </p>
        )}
      </div>

      <GlowCard className="!p-0 overflow-visible">
        <div className="p-6">
          <ConfigForm
            mode={mode}
            availableColumns={availableColumns}
            onSubmit={handleSubmit}
          />
        </div>
      </GlowCard>
    </div>
  );
}
