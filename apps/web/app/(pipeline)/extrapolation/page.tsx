"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Upload, Play, BarChart3, FileDown } from "lucide-react";
import { toast } from "sonner";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";
import { StatCard } from "@/components/ui/stat-card";
import { DropZone } from "@/components/upload/drop-zone";
import { useAppStore } from "@/lib/store";

export default function ExtrapolationPage() {
  const { mode } = useAppStore();
  const [file, setFile] = useState<File | null>(null);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<{
    totalSegments: number;
    extrapolated: number;
    avgConfidence: number;
    warnings: number;
  } | null>(null);

  function handleRun() {
    if (!file) {
      toast.error("Veuillez d'abord importer un fichier");
      return;
    }

    setRunning(true);

    // Simulate analysis
    setTimeout(() => {
      setResults({
        totalSegments: 12453,
        extrapolated: 11987,
        avgConfidence: 87.3,
        warnings: 234,
      });
      setRunning(false);
      toast.success("Analyse d'extrapolation terminee");
    }, 2000);
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <GradientText as="h2" className="text-2xl">
          Analyse d&apos;extrapolation
        </GradientText>
        <p className="text-sm text-muted">
          Evaluez la capacite du modele {mode === "pl" ? "PL" : "TV"} a
          extrapoler sur des donnees externes au jeu d&apos;entrainement.
        </p>
      </div>

      {/* Upload */}
      <GlowCard>
        <div className="flex items-center gap-2 mb-4">
          <Upload size={18} className="text-violet" />
          <h3 className="text-sm font-semibold text-foreground">
            Fichier externe a evaluer
          </h3>
        </div>
        <DropZone
          file={file}
          onFile={setFile}
          onClear={() => {
            setFile(null);
            setResults(null);
          }}
          label="Donnees externes pour extrapolation"
          description="GeoJSON ou CSV avec le reseau routier cible"
        />
      </GlowCard>

      {/* Launch */}
      <div className="flex justify-center">
        <NeonButton
          onClick={handleRun}
          disabled={!file || running}
          icon={<Play size={16} />}
          className={running ? "animate-pulse-glow" : ""}
        >
          {running ? "Analyse en cours..." : "Lancer l'analyse"}
        </NeonButton>
      </div>

      {/* Results */}
      <AnimatePresence>
        {results && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="space-y-4"
          >
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatCard
                label="Segments totaux"
                value={results.totalSegments.toLocaleString()}
                icon={<BarChart3 size={18} />}
              />
              <StatCard
                label="Segments extrapoles"
                value={results.extrapolated.toLocaleString()}
                icon={<BarChart3 size={18} />}
                trend="up"
              />
              <StatCard
                label="Confiance moyenne"
                value={`${results.avgConfidence}%`}
                trend={results.avgConfidence > 80 ? "up" : "down"}
              />
              <StatCard
                label="Alertes"
                value={results.warnings}
                trend={results.warnings > 100 ? "down" : "up"}
              />
            </div>

            <GlowCard glowColor="cyan">
              <div className="text-center py-6 space-y-4">
                <p className="text-sm text-foreground">
                  L&apos;extrapolation couvre{" "}
                  <span className="text-accent font-bold">
                    {(
                      (results.extrapolated / results.totalSegments) *
                      100
                    ).toFixed(1)}
                    %
                  </span>{" "}
                  des segments du reseau.
                </p>
                <NeonButton
                  variant="secondary"
                  icon={<FileDown size={16} />}
                >
                  Telecharger les resultats
                </NeonButton>
              </div>
            </GlowCard>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
