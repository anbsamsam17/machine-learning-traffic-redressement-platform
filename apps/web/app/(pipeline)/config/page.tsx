"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { ConfigForm, type TrainingConfig } from "@/components/pipeline/config-form";
import { useAppStore } from "@/lib/store";

export default function ConfigPage() {
  const router = useRouter();
  const { mode, territory, nextStep } = useAppStore();
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(config: TrainingConfig) {
    if (submitting) return;
    setSubmitting(true);

    try {
      const payload = {
        ...config,
        territory: territory ?? "default",
      };

      const res = await fetch("/api/training/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Erreur ${res.status}`);
      }

      toast.success("Configuration enregistree — entrainement lance");
      nextStep();
      router.push("/training");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Erreur inconnue";
      toast.error(`Echec : ${message}`);
      console.error("Config submit error:", error);
    } finally {
      setSubmitting(false);
    }
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
      </div>

      <GlowCard className="!p-0 overflow-visible">
        <div className="p-6">
          <ConfigForm mode={mode} onSubmit={handleSubmit} />
        </div>
      </GlowCard>
    </div>
  );
}
