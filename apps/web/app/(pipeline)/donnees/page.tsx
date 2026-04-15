"use client";

import { useState, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { FileSpreadsheet, Wand2, Table2, AlertTriangle } from "lucide-react";
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

// ── Real 36 target columns from column_mapper.py (35 + geometry) ──────────
const TARGET_COLUMNS = [
  "Type", "Identifiant", "Commune", "Route", "PRD",
  "MJA TV 2023", "MJA PL 2023", "MJA TV 2024", "MJA PL 2024",
  "MJA TV 2025", "MJA PL 2025",
  "TMJABCTV", "TMJABCPL", "Annee", "Road", "TMJAVL", "TMJAPL", "TMJATV",
  "TxPen", "TxPenPL", "variabilite_FCD",
  "car_count", "car_average_speed_kmh", "car_average_distance_km",
  "truck_count", "truck_average_speed_kmh", "truck_min_average_distance_km",
  "REF_IN_ID", "NREF_IN_ID", "TUNNEL", "status", "RAMP", "ROUNDABOUT",
  "ST_NAME", "flag_comptage", "geometry",
];

// ── Critical columns required for model training (from df_builder.py) ─────
const CRITICAL_COLS = [
  "TMJATV",
  "TMJAPL",
  "TxPen",
  "car_average_distance_km",
  "car_average_speed_kmh",
  "truck_min_average_distance_km",
  "truck_average_speed_kmh",
];

export default function DonneesPage() {
  const { setFileName } = useAppStore();
  const [file, setFile] = useState<File | null>(null);
  const [sourceColumns, setSourceColumns] = useState<string[]>([]);
  const [mappings, setMappings] = useState<ColumnMapping[]>([]);
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [step, setStep] = useState<"upload" | "mapping" | "preview">("upload");
  const [isAutoMapping, setIsAutoMapping] = useState(false);

  const mappedCriticalCount = useMemo(() => {
    return mappings.filter(
      (m) => m.source !== null && CRITICAL_COLS.includes(m.target)
    ).length;
  }, [mappings]);

  const unmappedCritical = useMemo(() => {
    return CRITICAL_COLS.filter(
      (col) => !mappings.find((m) => m.target === col && m.source !== null)
    );
  }, [mappings]);

  const handleFile = useCallback(
    async (f: File) => {
      setFile(f);
      setFileName(f.name);
      setIsAutoMapping(true);

      try {
        // Upload file and get auto-mapping from backend
        const formData = new FormData();
        formData.append("file", f);

        const response = await fetch("/api/mapping/auto", {
          method: "POST",
          body: formData,
        });

        if (!response.ok) {
          throw new Error(`Auto-mapping failed: ${response.statusText}`);
        }

        const data = await response.json();
        const srcCols: string[] = data.sourceColumns ?? [];
        setSourceColumns(srcCols);

        // Build mappings from backend response
        // data.mapping = { targetCol: sourceCol | null, ... }
        const backendMapping: Record<string, string | null> = data.mapping ?? {};
        const autoMappings: ColumnMapping[] = TARGET_COLUMNS.map((target) => ({
          target,
          source: backendMapping[target] ?? null,
          confidence: backendMapping[target]
            ? (data.confidences?.[target] ?? 80)
            : 0,
        }));
        setMappings(autoMappings);
        setStep("mapping");
        toast.success("Fichier charge avec succes");

        // Warn if critical columns are missing
        const missingCritical = CRITICAL_COLS.filter(
          (col) => !backendMapping[col]
        );
        if (missingCritical.length > 0) {
          toast.warning(
            `${missingCritical.length} colonne(s) critique(s) non mappee(s) : ${missingCritical.join(", ")}`
          );
        }
      } catch (err) {
        console.error("Auto-mapping error:", err);
        toast.error(
          "Erreur lors de l'auto-mapping. Verifiez que le backend est accessible."
        );
        // Fallback: set empty mappings so user can map manually
        setSourceColumns([]);
        const fallbackMappings: ColumnMapping[] = TARGET_COLUMNS.map(
          (target) => ({ target, source: null, confidence: 0 })
        );
        setMappings(fallbackMappings);
        setStep("mapping");
      } finally {
        setIsAutoMapping(false);
      }
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

  async function handleValidateMapping() {
    const mapped = mappings.filter((m) => m.source !== null);
    if (mapped.length < 5) {
      toast.error("Mappez au moins 5 colonnes pour continuer");
      return;
    }

    // Warn about unmapped critical columns
    if (unmappedCritical.length > 0) {
      toast.warning(
        `Attention : ${unmappedCritical.length} colonne(s) critique(s) non mappee(s). L'entrainement risque d'echouer.`
      );
    }

    try {
      // Validate mapping via backend
      const mappingPayload: Record<string, string | null> = {};
      mappings.forEach((m) => {
        mappingPayload[m.target] = m.source;
      });

      const response = await fetch("/api/mapping/validate", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mapping: mappingPayload, fileName: file?.name }),
      });

      if (!response.ok) {
        throw new Error(`Validation failed: ${response.statusText}`);
      }

      const data = await response.json();

      // Use preview rows from backend if available
      const rows = data.previewRows ?? Array.from({ length: 5 }, (_, i) => {
        const row: Record<string, unknown> = {};
        mapped.forEach((m) => {
          row[m.target] = `val_${i}_${m.target.slice(0, 4)}`;
        });
        return row;
      });
      setPreviewRows(rows);
      setStep("preview");
      toast.success("Mapping valide - Table d'apprentissage generee");
    } catch (err) {
      console.error("Validation error:", err);
      toast.error(
        "Erreur lors de la validation du mapping. Verifiez que le backend est accessible."
      );
    }
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <GradientText as="h2" className="text-2xl">
          Donnees
        </GradientText>
        <p className="text-sm text-muted">
          Importez votre fichier de donnees brutes et configurez le mapping des
          colonnes vers les {TARGET_COLUMNS.length} colonnes standard.
        </p>
      </div>

      {/* Upload */}
      <GlowCard>
        <div className="flex items-center gap-2 mb-4">
          <FileSpreadsheet size={18} className="text-accent" />
          <h3 className="text-sm font-semibold text-foreground">
            Fichier source
          </h3>
          {isAutoMapping && (
            <span className="text-xs text-cyan animate-pulse ml-2">
              Auto-mapping en cours...
            </span>
          )}
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
                  onClick={handleValidateMapping}
                  icon={<Wand2 size={14} />}
                  className="text-xs"
                >
                  Valider et generer la table
                </NeonButton>
              </div>

              {/* Critical columns warning */}
              {unmappedCritical.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  className="flex items-start gap-2 p-3 mb-4 rounded-lg border border-amber-500/30 bg-amber-500/5"
                >
                  <AlertTriangle size={16} className="text-amber-400 flex-shrink-0 mt-0.5" />
                  <div className="text-xs">
                    <span className="text-amber-400 font-semibold">
                      {unmappedCritical.length}/{CRITICAL_COLS.length} colonnes critiques non mappees
                    </span>
                    <p className="text-muted mt-1">
                      {unmappedCritical.join(", ")}
                    </p>
                  </div>
                </motion.div>
              )}

              <ColumnMapper
                targetColumns={TARGET_COLUMNS}
                sourceColumns={sourceColumns}
                criticalColumns={CRITICAL_COLS}
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
                  value={`${mappings.filter((m) => m.source).length}/${TARGET_COLUMNS.length}`}
                />
                <StatCard
                  label="Critiques mappees"
                  value={`${mappedCriticalCount}/${CRITICAL_COLS.length}`}
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
                          {CRITICAL_COLS.includes(col) && (
                            <span className="text-amber-400 ml-1">*</span>
                          )}
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
