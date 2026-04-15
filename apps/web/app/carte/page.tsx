"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Map, ArrowLeft, Upload, Play, Download, Layers } from "lucide-react";
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

const CARTE_TARGETS = [
  "IDTroncon", "geometry", "TMJATV_Redresse", "TMJAPL_Redresse",
  "ClasseRoute", "NomRoute", "Commune",
];

export default function CartePage() {
  const router = useRouter();
  const { reset } = useAppStore();
  const [tvFile, setTvFile] = useState<File | null>(null);
  const [plFile, setPlFile] = useState<File | null>(null);
  const [fcdFile, setFcdFile] = useState<File | null>(null);
  const [mappings, setMappings] = useState<ColumnMapping[]>([]);
  const [showMapping, setShowMapping] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [done, setDone] = useState(false);

  function handleGenerate() {
    if (!tvFile || !fcdFile) {
      toast.error("Veuillez importer au minimum le ZIP TV et le fichier FCD");
      return;
    }
    setGenerating(true);
    setTimeout(() => {
      setGenerating(false);
      setDone(true);
      toast.success("Carte de debits generee avec succes");
    }, 3000);
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
          <div className="px-3 py-1 rounded-lg bg-cyan/10 text-cyan text-xs font-bold uppercase tracking-wide">
            Carte
          </div>
        </div>

        <div className="space-y-2">
          <GradientText as="h2" className="text-2xl">
            Generation de la Carte de Debits
          </GradientText>
          <p className="text-sm text-muted">
            Importez les resultats des modeles TV et PL, le fichier FCD source,
            et generez la carte geographique des debits redresses.
          </p>
        </div>

        {/* Uploads */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <GlowCard glowColor="accent">
            <div className="flex items-center gap-2 mb-3">
              <Upload size={16} className="text-accent" />
              <h3 className="text-xs font-semibold text-foreground">
                Resultats TV (ZIP)
              </h3>
            </div>
            <DropZone
              file={tvFile}
              onFile={setTvFile}
              onClear={() => setTvFile(null)}
              accept={{ "application/zip": [".zip"] }}
              label="ZIP modele TV"
              description=".zip"
            />
          </GlowCard>

          <GlowCard glowColor="violet">
            <div className="flex items-center gap-2 mb-3">
              <Upload size={16} className="text-violet" />
              <h3 className="text-xs font-semibold text-foreground">
                Resultats PL (ZIP)
              </h3>
            </div>
            <DropZone
              file={plFile}
              onFile={setPlFile}
              onClear={() => setPlFile(null)}
              accept={{ "application/zip": [".zip"] }}
              label="ZIP modele PL"
              description=".zip (optionnel)"
            />
          </GlowCard>

          <GlowCard glowColor="cyan">
            <div className="flex items-center gap-2 mb-3">
              <Upload size={16} className="text-cyan" />
              <h3 className="text-xs font-semibold text-foreground">
                Fichier FCD
              </h3>
            </div>
            <DropZone
              file={fcdFile}
              onFile={(f) => {
                setFcdFile(f);
                setShowMapping(true);
              }}
              onClear={() => {
                setFcdFile(null);
                setShowMapping(false);
              }}
              label="GeoJSON FCD"
              description=".geojson, .csv"
            />
          </GlowCard>
        </div>

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
                  targetColumns={CARTE_TARGETS}
                  sourceColumns={[
                    "id", "geom", "tmja_tv_r", "tmja_pl_r",
                    "classe", "nom", "commune",
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
            disabled={generating}
            icon={generating ? undefined : <Play size={16} />}
            className={generating ? "animate-pulse-glow" : ""}
          >
            {generating ? "Generation en cours..." : "Generer la carte"}
          </NeonButton>
        </div>

        {/* Results */}
        <AnimatePresence>
          {done && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <GlowCard glowColor="cyan">
                <div className="text-center py-6 space-y-4">
                  <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center mx-auto">
                    <Map size={28} />
                  </div>
                  <p className="text-sm font-medium text-foreground">
                    Carte generee avec succes
                  </p>
                  <div className="grid grid-cols-3 gap-3 max-w-md mx-auto">
                    <StatCard label="Segments" value="12 453" />
                    <StatCard label="TV redresses" value="11 987" />
                    <StatCard label="PL redresses" value="9 412" />
                  </div>
                  <NeonButton
                    variant="secondary"
                    icon={<Download size={16} />}
                  >
                    Telecharger la carte HTML
                  </NeonButton>
                </div>
              </GlowCard>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
