"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Database, ArrowRight } from "lucide-react";
import { apiUrl } from "@/lib/api-url";
import { toast } from "sonner";
import { samNotify } from "@/lib/sam-fallback";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";
import { ConfigForm, type TrainingConfig } from "@/components/pipeline/config-form";
import { SamCoachingPanel } from "@/components/sam/sam-coaching-panel";
import { useAppStore } from "@/lib/store";

/**
 * Placeholder rendu avant l'hydration Zustand. Garantit que SSR et premier
 * rendu client produisent le même HTML (zéro warning hydration), tout en
 * laissant à `persist` le temps de charger `mode` depuis localStorage avant
 * de monter le ConfigForm avec les bons défauts TV/PL.
 */
function ConfigFormSkeleton() {
  return (
    <div
      className="space-y-3 animate-pulse"
      aria-busy="true"
      aria-label="Chargement de la configuration"
    >
      <div className="h-8 w-64 rounded bg-bg-elevated/60" />
      <div className="h-32 rounded bg-bg-elevated/40" />
      <div className="h-32 rounded bg-bg-elevated/40" />
      <div className="h-32 rounded bg-bg-elevated/40" />
    </div>
  );
}

export default function ConfigPage() {
  const router = useRouter();
  const { mode, sessionId, nextStep } = useAppStore();
  const [availableColumns, setAvailableColumns] = useState<string[]>([]);
  // Gate ConfigForm rendering until the client has mounted and Zustand's
  // `persist` middleware has rehydrated `mode` from localStorage. Without
  // this, the SSR/initial render sees `mode === null` → isTv defaults to
  // true → all useState(...) inside <ConfigForm /> initialise with TV
  // values, and re-rendering with mode="pl" does NOT re-run those
  // initializers (useState only reads its initial value once). Bug
  // reported by the Playwright reviewer (PL config defaults stuck on TV).
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    setHydrated(true);
  }, []);

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
          Configuration {
            mode === "pl"
              ? "PL"
              : mode === "hpm"
                ? "HPM"
                : mode === "hps"
                  ? "HPS"
                  : "TV"
          }
        </GradientText>
        <p className="text-sm text-slate-300">
          Definissez les colonnes d&apos;entree, les hyperparametres et la
          grille de recherche pour l&apos;entrainement{" "}
          <span className="font-semibold text-indigo-300">
            {mode === "pl"
              ? "Poids Lourds"
              : mode === "hpm"
                ? "Heure de Pointe Matin (8h-9h, v/h)"
                : mode === "hps"
                  ? "Heure de Pointe Soir (17h-18h, v/h)"
                  : "Tous Vehicules"}
          </span>
          .
        </p>
      </div>

      {/* Empty-state: pas de session active. On laisse la page se rendre
          (Tache 1 : pas de redirection) mais on guide l'utilisateur. */}
      {!sessionId && (
        <GlowCard glowColor="cyan">
          <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-indigo-500/10 flex items-center justify-center text-indigo-300 shrink-0">
              <Database size={22} aria-hidden="true" />
            </div>
            <div className="flex-1 space-y-1">
              <h3 className="text-sm font-semibold text-white">
                Aucun jeu de donnees charge
              </h3>
              <p className="text-xs text-slate-300">
                Pour configurer un modele, importe d&apos;abord un jeu de
                donnees via <strong>Etape 1 — Donnees</strong>.
              </p>
            </div>
            <Link href="/donnees" className="shrink-0">
              <NeonButton icon={<ArrowRight size={14} />}>
                Aller a l&apos;etape Donnees
              </NeonButton>
            </Link>
          </div>
        </GlowCard>
      )}

      <SamCoachingPanel mode={mode} />

      <GlowCard className="!p-0 overflow-visible">
        <div className="p-6">
          {/* `key={mode ?? "init"}` force le remount de ConfigForm quand le
              store Zustand passe de null (avant hydration) à "tv"/"pl". Sans
              ce remount, tous les useState(...) du formulaire restent figés
              sur les valeurs TV par défaut (calculées au premier render avec
              mode === null → isTv === true). Combiné avec le gate `hydrated`
              ci-dessous, le rendu SSR et le premier rendu client sont
              identiques (skeleton) → pas de hydration mismatch React. */}
          {hydrated ? (
            <ConfigForm
              key={mode ?? "init"}
              mode={mode}
              availableColumns={availableColumns}
              onSubmit={handleSubmit}
            />
          ) : (
            <ConfigFormSkeleton />
          )}
        </div>
      </GlowCard>
    </div>
  );
}
