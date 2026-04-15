"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft,
  CircleDot,
  Upload,
  Play,
  Download,
  Layers,
} from "lucide-react";
import { toast } from "sonner";
import { AuroraBg } from "@/components/backgrounds/aurora-bg";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";
import { StatCard } from "@/components/ui/stat-card";
import { DropZone } from "@/components/upload/drop-zone";
import {
  ColumnMapper,
  type ColumnMapping,
} from "@/components/mapping/column-mapper";
import { useAppStore } from "@/lib/store";

const COMPTEUR_TARGETS = [
  "IDTroncon", "geometry", "TMJATV", "TMJAPL",
  "ClasseRoute", "Localisation", "TypeCompteur",
];

export default function CompteursPage() {
  const router = useRouter();
  const { reset } = useAppStore();
  const [file, setFile] = useState<File | null>(null);
  const [mappings, setMappings] = useState<ColumnMapping[]>([]);
  const [showMapping, setShowMapping] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [done, setDone] = useState(false);

  function handleGenerate() {
    if (!file) {
      toast.error("Veuillez importer un fichier");
      return;
    }
    setGenerating(true);
    setTimeout(() => {
      setGenerating(false);
      setDone(true);
      toast.success("Boucles de comptage generees avec succes");
    }, 2500);
  }

  return (
    <div className="relative min-h-screen">
      <AuroraBg />
      <div className="relative z-10 max-w-4xl mx-auto px-4 py-8 space-y-6">
        <div className="flex items-center gap-3">
          <NeonButton
            variant="ghost"
            onClick={() => {
              reset();
              router.push("/");
            }}
            icon={<ArrowLeft size={14} />}
            className="text-xs"
          >
            Accueil
          </NeonButton>
          <div className="px-3 py-1 rounded-lg bg-accent/10 text-accent text-xs font-bold uppercase tracking-wide">
            Compteurs
          </div>
        </div>

        <div className="space-y-2">
          <GradientText as="h2" className="text-2xl">
            Generation des Boucles de Comptage
          </GradientText>
          <p className="text-sm text-muted">
            Importez les donnees du reseau et generez les boucles de comptage
            virtuelles a partir des modeles entraines.
          </p>
        </div>

        {/* Upload */}
        <GlowCard>
          <div className="flex items-center gap-2 mb-4">
            <Upload size={18} className="text-accent" />
            <h3 className="text-sm font-semibold text-foreground">
              Fichier reseau
            </h3>
          </div>
          <DropZone
            file={file}
            onFile={(f) => {
              setFile(f);
              setShowMapping(true);
            }}
            onClear={() => {
              setFile(null);
              setShowMapping(false);
              setDone(false);
            }}
            label="Deposez le fichier du reseau routier"
            description="GeoJSON, CSV ou Shapefile (ZIP)"
          />
        </GlowCard>

        {/* Mapping */}
        <AnimatePresence>
          {showMapping && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <GlowCard>
                <div className="flex items-center gap-2 mb-4">
                  <Layers size={18} className="text-cyan" />
                  <h3 className="text-sm font-semibold text-foreground">
                    Mapping des colonnes
                  </h3>
                </div>
                <ColumnMapper
                  targetColumns={COMPTEUR_TARGETS}
                  sourceColumns={[
                    "id_troncon", "geom", "tmja_tv", "tmja_pl",
                    "classe_route", "localisation", "type_compteur",
                  ]}
                  onMappingsChange={setMappings}
                />
              </GlowCard>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Generate */}
        <div className="flex justify-center">
          <NeonButton
            onClick={handleGenerate}
            disabled={!file || generating}
            icon={generating ? undefined : <Play size={16} />}
            className={generating ? "animate-pulse-glow" : ""}
          >
            {generating
              ? "Generation en cours..."
              : "Generer les boucles de comptage"}
          </NeonButton>
        </div>

        {/* Results */}
        <AnimatePresence>
          {done && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <GlowCard glowColor="accent">
                <div className="text-center py-6 space-y-4">
                  <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center mx-auto">
                    <CircleDot size={28} />
                  </div>
                  <p className="text-sm font-medium text-foreground">
                    Boucles de comptage generees
                  </p>
                  <div className="grid grid-cols-3 gap-3 max-w-md mx-auto">
                    <StatCard label="Boucles" value="347" />
                    <StatCard label="Couverture" value="94.2%" />
                    <StatCard label="Segments" value="8 231" />
                  </div>
                  <div className="flex items-center justify-center gap-3">
                    <NeonButton
                      variant="secondary"
                      icon={<Download size={16} />}
                    >
                      Telecharger GeoJSON
                    </NeonButton>
                    <NeonButton
                      variant="secondary"
                      icon={<Download size={16} />}
                    >
                      Telecharger CSV
                    </NeonButton>
                  </div>
                </div>
              </GlowCard>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
