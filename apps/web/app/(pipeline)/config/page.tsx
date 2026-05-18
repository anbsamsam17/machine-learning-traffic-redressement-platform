"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { apiUrl } from "@/lib/api-url";
import { toast } from "sonner";
import { ConfigForm, type TrainingConfig } from "@/components/pipeline/config-form";
import { useAppStore } from "@/lib/store";

export default function ConfigPage() {
  const router = useRouter();
  const { mode, sessionId, nextStep } = useAppStore();
  const [availableColumns, setAvailableColumns] = useState<string[]>([]);

  // Fetch the columns from the learning table in the session
  useEffect(() => {
    if (!sessionId) return;
    fetch(apiUrl("/api/mapping/auto"), {
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

    useAppStore.getState().setTrainingConfig({
      ...config,
      session_id: sessionId,
    });

    const len = (v: unknown) => (Array.isArray(v) ? v.length : 1);
    const combos =
      len(config.activations) *
      len(config.learning_rates) *
      len(config.min_nb_epochs_list) *
      len(config.losses) *
      len(config.dropouts) *
      len(config.neurons_factors_list) *
      len(config.batch_sizes);

    toast.success(
      `Configuration enregistree — ${combos.toLocaleString("fr-FR")} combinaison${combos > 1 ? "s" : ""} a entrainer`
    );

    nextStep();
    setTimeout(() => router.push("/training"), 600);
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1.5">
        <h2 className="text-2xl font-semibold text-text">
          Configuration {mode === "pl" ? "PL" : "TV"}
        </h2>
        <p className="text-sm text-text-muted">
          Definissez les colonnes d&apos;entree, les hyperparametres et la grille
          de recherche pour l&apos;entrainement{" "}
          <span className="text-text">
            {mode === "pl" ? "Poids Lourds" : "Tous Vehicules"}
          </span>
          .
        </p>
        {!sessionId && (
          <p className="text-sm text-warning">
            Aucune session active. Retournez a l&apos;etape Donnees pour
            importer un fichier.
          </p>
        )}
      </div>

      <ConfigForm
        mode={mode}
        availableColumns={availableColumns}
        onSubmit={handleSubmit}
      />
    </div>
  );
}
