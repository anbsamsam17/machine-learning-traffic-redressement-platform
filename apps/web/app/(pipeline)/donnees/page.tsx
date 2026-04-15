"use client";

import { useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { FileSpreadsheet, Wand2, Table2 } from "lucide-react";
import { toast } from "sonner";
import { DropZone } from "@/components/upload/drop-zone";
import {
  ColumnMapper,
  type ColumnMapping,
} from "@/components/mapping/column-mapper";
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";
import { GradientText } from "@/components/ui/gradient-text";
import { StatCard } from "@/components/ui/stat-card";
import { useAppStore } from "@/lib/store";

const TARGET_COLUMNS = [
  "IDTroncon", "Longueur", "NbVoies", "ClasseRoute", "TypeZone",
  "VitesseMoy", "VitesseRef", "Capacite", "Rampe", "Sinuosite",
  "Largeur", "MedianeSeparee", "AccesBorde", "InterDist",
  "TxPen", "TMJAFCDTV", "TMJAFCDPL", "TMJATV", "TMJAPL",
  "DebitHoraire", "TxPoids", "Seuil", "geometry",
  "NomRoute", "Commune", "Departement", "Region",
  "SensCirculation", "RevetementType", "Urbain",
  "ZoneVitesse", "Peage", "PontTunnel", "Altitude", "Population",
];

export default function DonneesPage() {
  const { mode, setFileName } = useAppStore();
  const [file, setFile] = useState<File | null>(null);
  const [sourceColumns, setSourceColumns] = useState<string[]>([]);
  const [mappings, setMappings] = useState<ColumnMapping[]>([]);
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [step, setStep] = useState<"upload" | "mapping" | "preview">("upload");

  const handleFile = useCallback(
    (f: File) => {
      setFile(f);
      setFileName(f.name);

      // Simulate reading column headers from the file
      const mockSources = [
        "id_troncon", "longueur_m", "nb_voies", "classe_route",
        "type_zone", "vitesse_moy", "vitesse_ref", "capacite",
        "rampe", "sinuosite", "largeur", "mediane_sep",
        "acces_borde", "inter_dist", "tx_pen", "tmja_fcd_tv",
        "tmja_fcd_pl", "tmja_tv", "tmja_pl", "debit_horaire",
        "tx_poids", "seuil", "geometry", "nom_route",
        "commune", "departement", "region", "sens_circulation",
        "revetement", "urbain", "zone_vitesse", "peage",
        "pont_tunnel", "altitude", "population",
      ];
      setSourceColumns(mockSources);

      // Auto-mapping simulation
      const autoMappings: ColumnMapping[] = TARGET_COLUMNS.map((target, i) => ({
        target,
        source: mockSources[i] ?? null,
        confidence: mockSources[i] ? 75 + Math.floor(Math.random() * 25) : 0,
      }));
      setMappings(autoMappings);
      setStep("mapping");
      toast.success("Fichier charge avec succes");
    },
    [setFileName]
  );

  function handleClear() {
    setFile(null);
    setSourceColumns([]);
    setMappings([]);
    setPreviewRows([]);
    setStep("upload");
  }

  function handleGenerate() {
    const mapped = mappings.filter((m) => m.source !== null);
    if (mapped.length < 5) {
      toast.error("Mappez au moins 5 colonnes pour continuer");
      return;
    }

    // Simulate generating the learning table
    const rows = Array.from({ length: 5 }, (_, i) => {
      const row: Record<string, unknown> = {};
      mapped.forEach((m) => {
        row[m.target] = `val_${i}_${m.target.slice(0, 4)}`;
      });
      return row;
    });
    setPreviewRows(rows);
    setStep("preview");
    toast.success("Table d'apprentissage generee");
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <GradientText as="h2" className="text-2xl">
          Donnees
        </GradientText>
        <p className="text-sm text-muted">
          Importez votre fichier de donnees brutes et configurez le mapping des
          colonnes vers les 35 colonnes standard.
        </p>
      </div>

      {/* Upload */}
      <GlowCard>
        <div className="flex items-center gap-2 mb-4">
          <FileSpreadsheet size={18} className="text-accent" />
          <h3 className="text-sm font-semibold text-foreground">
            Fichier source
          </h3>
        </div>
        <DropZone file={file} onFile={handleFile} onClear={handleClear} />
      </GlowCard>

      {/* Mapping */}
      <AnimatePresence>
        {step === "mapping" && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            <GlowCard>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Table2 size={18} className="text-cyan" />
                  <h3 className="text-sm font-semibold text-foreground">
                    Mapping des colonnes
                  </h3>
                </div>
                <NeonButton
                  variant="secondary"
                  onClick={handleGenerate}
                  icon={<Wand2 size={14} />}
                  className="text-xs"
                >
                  Generer la table
                </NeonButton>
              </div>
              <ColumnMapper
                targetColumns={TARGET_COLUMNS}
                sourceColumns={sourceColumns}
                initialMappings={mappings}
                onMappingsChange={setMappings}
              />
            </GlowCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Preview */}
      <AnimatePresence>
        {step === "preview" && previewRows.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            <GlowCard glowColor="cyan">
              <div className="flex items-center gap-2 mb-4">
                <Table2 size={18} className="text-emerald-400" />
                <h3 className="text-sm font-semibold text-foreground">
                  Apercu de la table d&apos;apprentissage
                </h3>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                <StatCard
                  label="Lignes"
                  value={previewRows.length}
                />
                <StatCard
                  label="Colonnes mappees"
                  value={mappings.filter((m) => m.source).length}
                />
                <StatCard
                  label="Colonnes cibles"
                  value={TARGET_COLUMNS.length}
                />
                <StatCard
                  label="Confiance moy."
                  value={`${Math.round(
                    mappings
                      .filter((m) => m.source)
                      .reduce((s, m) => s + m.confidence, 0) /
                      Math.max(mappings.filter((m) => m.source).length, 1)
                  )}%`}
                />
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border">
                      {Object.keys(previewRows[0]).slice(0, 8).map((col) => (
                        <th
                          key={col}
                          className="px-2 py-1.5 text-left text-muted font-medium"
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {previewRows.map((row, i) => (
                      <tr
                        key={i}
                        className="border-b border-border/30 hover:bg-surface-light/30"
                      >
                        {Object.values(row)
                          .slice(0, 8)
                          .map((val, j) => (
                            <td
                              key={j}
                              className="px-2 py-1.5 text-foreground font-mono"
                            >
                              {String(val)}
                            </td>
                          ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted mt-3">
                Affichage des 8 premieres colonnes sur{" "}
                {Object.keys(previewRows[0]).length} colonnes totales.
              </p>
            </GlowCard>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
