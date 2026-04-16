"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { FolderOpen } from "lucide-react";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { ConfigForm, type TrainingConfig } from "@/components/pipeline/config-form";
import { useAppStore } from "@/lib/store";

export default function ConfigPage() {
  const router = useRouter();
  const { mode, sessionId, outputDir, setOutputDir, nextStep } = useAppStore();
  const [availableColumns, setAvailableColumns] = useState<string[]>([]);
  const [localOutputDir, setLocalOutputDir] = useState(outputDir ?? "");

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

    // Save output dir to store
    if (localOutputDir) {
      setOutputDir(localOutputDir);
    }

    // Store the training config in Zustand for the training page to use
    useAppStore.getState().setTrainingConfig({
      ...config,
      session_id: sessionId,
      output_dir: localOutputDir || undefined,
    });

    toast.success("Configuration enregistree — passez a l'entrainement");
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

      {/* Dossier de sortie */}
      <GlowCard>
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center text-indigo-400 shrink-0">
            <FolderOpen size={20} />
          </div>
          <div className="flex-1 space-y-2">
            <label className="text-sm font-medium text-slate-200">
              Dossier de sortie des modeles
            </label>
            <p className="text-xs text-slate-400">
              Chemin du dossier ou seront enregistres tous les modeles entraines
              (poids, config, coefficients de normalisation).
            </p>
            <input
              type="text"
              value={localOutputDir}
              onChange={(e) => setLocalOutputDir(e.target.value)}
              placeholder={`Ex: C:\\xMDL\\${mode === "pl" ? "PL" : "TV"}\\MonTerritoire`}
              className="w-full px-3 py-2 rounded-lg text-sm bg-slate-900/80 border border-white/[0.08] text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30 transition-colors"
            />
          </div>
        </div>
      </GlowCard>

      {/* Formulaire de configuration */}
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
