"use client";

import { motion } from "framer-motion";
import { Loader2, Play } from "lucide-react";
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";

// ---------------------------------------------------------------------------
// GenerationSection — bouton "Generer la carte" + progress + hint d'erreur
// ---------------------------------------------------------------------------

export interface GenerationSectionProps {
  canGenerate: boolean;
  generating: boolean;
  done: boolean;
  progress: number;
  progressText: string;
  onGenerate: () => void;
  // Hints affiches sous le bouton si !canGenerate
  tvValid: boolean | null;
  plValid: boolean | null;
  sessionId: string | null;
  requiredMapped: boolean;
}

export function GenerationSection(props: GenerationSectionProps) {
  const {
    canGenerate,
    generating,
    done,
    progress,
    progressText,
    onGenerate,
    tvValid,
    plValid,
    sessionId,
    requiredMapped,
  } = props;

  return (
    <GlowCard>
      <div className="flex items-center gap-2 mb-5">
        <div className="w-7 h-7 rounded-lg bg-accent/20 flex items-center justify-center text-accent text-xs font-bold">
          4
        </div>
        <h3 className="text-sm font-semibold text-white">Generation</h3>
      </div>

      {/* Progress */}
      {(generating || done) && (
        <div className="mb-5 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">{progressText}</span>
            <span className="text-xs font-mono text-accent">{progress}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-surface-light overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.5 }}
              className={`h-full rounded-full ${
                done
                  ? "bg-gradient-to-r from-emerald-500 to-emerald-400"
                  : "bg-gradient-to-r from-accent to-cyan"
              }`}
            />
          </div>
        </div>
      )}

      {/* Generate button */}
      <div className="flex justify-center">
        <NeonButton
          onClick={onGenerate}
          disabled={!canGenerate || generating}
          icon={
            generating ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Play size={16} />
            )
          }
          className={generating ? "animate-pulse" : ""}
        >
          {generating
            ? "Generation en cours..."
            : "Generer la carte des debits"}
        </NeonButton>
      </div>

      {!canGenerate && !generating && !done && (
        <p className="text-center text-[10px] text-slate-400 mt-3">
          {tvValid !== true && "Modele TV non valide. "}
          {plValid !== true && "Modele PL non valide. "}
          {!sessionId && "Aucun fichier FCD charge. "}
          {!requiredMapped && "Mapping des colonnes incomplet."}
        </p>
      )}
    </GlowCard>
  );
}
