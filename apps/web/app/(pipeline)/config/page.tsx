"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { apiUrl } from "@/lib/api-url";
import { toast } from "sonner";
import { samNotify, samMood } from "@/lib/sam-fallback";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { ConfigForm, type TrainingConfig } from "@/components/pipeline/config-form";
import { useAppStore } from "@/lib/store";

export default function ConfigPage() {
  const router = useRouter();
  const { mode, sessionId, nextStep } = useAppStore();
  const [availableColumns, setAvailableColumns] = useState<string[]>([]);

  // Ambient mood while user configures the grid search
  useEffect(() => {
  }, []);

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
      samNotify.error("Pas de session active. Importez d'abord un fichier.");
      return;
    }

    // Store the training config in Zustand for the training page to use
    useAppStore.getState().setTrainingConfig({
      ...config,
      session_id: sessionId,
    });

    // Compute number of combinations for the toast summary.
    // Must mirror config-form.tsx logic: feature_subsets × hyperparams
    // (NOT just hyperparams — the previous version always told the user
    // "2 combinaisons" when feature_subset_grid was on with 31 subsets,
    // because it omitted the subset multiplier completely).
    const len = (v: unknown) => (Array.isArray(v) ? v.length : 1);
    const hyperparams =
      len(config.activations) *
      len(config.learning_rates) *
      len(config.min_nb_epochs_list) *
      len(config.losses) *
      len(config.dropouts) *
      len(config.neurons_factors_list) *
      len(config.batch_sizes);

    let featureSets = 1;
    if (config.feature_subset_grid) {
      const inputCols = config.input_cols ?? [];
      const mandatory = config.mandatory_input_cols ?? [];
      const minInput = config.min_input_count ?? 0;
      const optionalCols = inputCols.filter((c) => !mandatory.includes(c));
      const minOptional = Math.max(0, minInput - mandatory.length);
      const comb = (n: number, k: number): number => {
        if (k > n || k < 0) return 0;
        if (k === 0 || k === n) return 1;
        let result = 1;
        for (let i = 0; i < Math.min(k, n - k); i++) {
          result = (result * (n - i)) / (i + 1);
        }
        return Math.round(result);
      };
      featureSets = 0;
      for (let k = minOptional; k <= optionalCols.length; k++) {
        featureSets += comb(optionalCols.length, k);
      }
      featureSets = Math.max(featureSets, 1);
    }
    const combos = featureSets * hyperparams;

    samNotify.info(
      `${combos.toLocaleString("fr-FR")} combinaison${combos > 1 ? "s" : ""} prevue${combos > 1 ? "s" : ""}`
    );
    toast.success(
      `Configuration enregistree — ${combos.toLocaleString("fr-FR")} combinaison${combos > 1 ? "s" : ""} a entrainer`
    );

    // Slight delay for user to see the toast before navigating
    nextStep();
    setTimeout(() => router.push("/training"), 600);
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <GradientText as="h1" className="text-2xl">
          Configuration {mode === "pl" ? "PL" : "TV"}
        </GradientText>
        <p className="text-sm text-slate-300">
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
