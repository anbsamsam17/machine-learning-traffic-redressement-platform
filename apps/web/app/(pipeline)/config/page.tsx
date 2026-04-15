"use client";

import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { ConfigForm } from "@/components/pipeline/config-form";
import { useAppStore } from "@/lib/store";

export default function ConfigPage() {
  const router = useRouter();
  const { mode, nextStep } = useAppStore();

  function handleSubmit(values: Record<string, unknown>) {
    console.log("Config submitted:", values);
    toast.success("Configuration enregistree");
    nextStep();
    router.push("/training");
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <GradientText as="h2" className="text-2xl">
          Configuration
        </GradientText>
        <p className="text-sm text-muted">
          Definissez les colonnes d&apos;entree, les hyperparametres et la grille de
          recherche pour l&apos;entrainement{" "}
          {mode === "pl" ? "PL" : "TV"}.
        </p>
      </div>

      <GlowCard>
        <ConfigForm mode={mode} onSubmit={handleSubmit} />
      </GlowCard>
    </div>
  );
}
