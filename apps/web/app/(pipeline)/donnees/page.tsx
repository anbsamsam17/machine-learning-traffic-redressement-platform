"use client";

import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { apiUrl } from "@/lib/api-url";
import { FileSpreadsheet, Wand2, Table2, AlertTriangle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { samNotify, samMood } from "@/lib/sam-fallback";
import { DropZone } from "@/components/upload/drop-zone";
import {
  ColumnMapper,
  type ColumnMapping,
} from "@/components/mapping/column-mapper";
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";
import { GradientText } from "@/components/ui/gradient-text";
import { StatCard } from "@/components/ui/stat-card";
import { SuccessBanner } from "@/components/ui/success-banner";
import { useAppStore } from "@/lib/store";
import { spawnConfetti } from "@/lib/success-effects";

// ── 26 target columns (Etape1_MDL_TV refonte FCD HERE) ────────────────────
// Mirrored from apps/api/app/routers/mapping.py:TARGET_COLUMNS.
const TARGET_COLUMNS = [
  // Identification (4)
  "Identifiant", "Annee", "Adresse", "Type Compteur",
  // Comptage capteur (4)
  "TMJOBCTV", "TMJOBCPL", "TMJOBCTV_HPM", "TMJOBCTV_HPS",
  // FCD HERE (2)
  "TMJOFCDTV", "TMJOFCDPL",
  // Taux de penetration (2)
  "TxPen", "TxPenPL",
  // Mapping (2)
  "segment_id_match", "mapmatch_status",
  // Reseau (1)
  "functional_class",
  // Vitesses (2)
  "avg_speed_kmh", "truck_avg_speed_kmh",
  // Distances VL (4)
  "avg_distance_m", "avg_distance_before_m",
  "avg_distance_after_m", "avg_min_distance_m",
  // Distances PL (4)
  "truck_avg_distance_m", "truck_avg_distance_before_m",
  "truck_avg_distance_after_m", "truck_avg_min_distance_m",
  // Geometrie (1)
  "geometry",
];

// ── Critical columns required for model training ──────────────────────────
const CRITICAL_COLS = [
  "TMJOBCTV",          // target principale TV
  "TMJOFCDTV",         // feature principale FCD TV
  "TMJOFCDPL",         // feature FCD PL
  "TxPen",             // cible derivable
  "avg_distance_m",
  "avg_speed_kmh",
  "truck_avg_min_distance_m",
  "truck_avg_speed_kmh",
  "functional_class",
];

export default function DonneesPage() {
  const { mode, setFileName } = useAppStore();
  const [file, setFile] = useState<File | null>(null);
  const [sourceColumns, setSourceColumns] = useState<string[]>([]);
  const [mappings, setMappings] = useState<ColumnMapping[]>([]);
  const [groups, setGroups] = useState<Record<string, string[]>>({});
  const [extraCandidates, setExtraCandidates] = useState<string[]>([]);
  const [selectedExtras, setSelectedExtras] = useState<string[]>([]);
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [totalRows, setTotalRows] = useState<number>(0);
  const [step, setStep] = useState<"upload" | "mapping" | "preview">("upload");
  const [isAutoMapping, setIsAutoMapping] = useState(false);
  const [showStepComplete, setShowStepComplete] = useState(false);
  const previewContainerRef = useRef<HTMLDivElement>(null);

  // Welcome message is delivered by SamPageBinder via PAGE_MESSAGES['/donnees'].
  // We deliberately skip a mount-time samNotify.info here so the toast doesn't
  // duplicate the SamWidget bubble.

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

      const samToastId = "donnees-upload";
      samNotify.analysing("Je lis ton fichier, ca prend quelques secondes...", {
        id: samToastId,
      });

      try {
        // Step 1: Upload file to get session_id
        const formData = new FormData();
        formData.append("file", f);
        formData.append("mode", mode ?? "tv");

        const uploadResponse = await fetch(apiUrl("/api/upload"), {
          method: "POST",
          body: formData,
        });

        if (!uploadResponse.ok) {
          const err = await uploadResponse.json().catch(() => ({}));
          throw new Error(err.detail ?? `Upload failed: ${uploadResponse.statusText}`);
        }

        const uploadData = await uploadResponse.json();
        const sessionId = uploadData.session_id;

        // Store session_id for later use
        useAppStore.getState().setSessionId(sessionId);

        // Step 2: Call auto-mapping with session_id
        const mapResponse = await fetch(apiUrl("/api/mapping/auto"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId }),
        });

        if (!mapResponse.ok) {
          const err = await mapResponse.json().catch(() => ({}));
          throw new Error(err.detail ?? `Auto-mapping failed: ${mapResponse.statusText}`);
        }

        const mapData = await mapResponse.json();
        const srcCols: string[] = mapData.source_columns ?? [];
        setSourceColumns(srcCols);
        setGroups(mapData.groups ?? {});
        setExtraCandidates(mapData.extra_candidates ?? []);
        setSelectedExtras([]);

        // Build mappings from backend response
        const backendMappings: Array<{target: string; source: string | null; confidence: string}> = mapData.mappings ?? [];
        const confidenceToScore: Record<string, number> = {
          exact: 100,
          synonym: 85,
          fuzzy: 70,
          missing: 0,
        };
        const autoMappings: ColumnMapping[] = backendMappings.map((m) => ({
          target: m.target,
          source: m.source,
          confidence: confidenceToScore[m.confidence] ?? 0,
        }));
        setMappings(autoMappings);
        setPreviewRows(uploadData.preview ?? []);
        setTotalRows(typeof uploadData.rows === "number" ? uploadData.rows : (uploadData.preview?.length ?? 0));
        setStep("mapping");

        // Compute auto-mapping confidence
        const totalMapped = autoMappings.filter((m) => m.source !== null).length;
        const avgConfidence =
          totalMapped > 0
            ? Math.round(
                autoMappings
                  .filter((m) => m.source !== null)
                  .reduce((s, m) => s + m.confidence, 0) / totalMapped
              )
            : 0;

        // Atomic replace (same id) — no flicker, no overlap with the analysing toast.
        samNotify.info(
          `Mapping auto detecte avec confiance ${avgConfidence}%. Verifie et confirme.`,
          { id: samToastId },
        );
        toast.success(`Fichier charge : ${uploadData.rows} lignes, ${srcCols.length} colonnes`);

        // Warn if critical columns are missing
        const missingCritical = CRITICAL_COLS.filter(
          (col) => !backendMappings.find((m) => m.target === col && m.source !== null)
        );
        if (missingCritical.length > 0) {
          toast.warning(
            `${missingCritical.length} colonne(s) critique(s) non mappee(s) : ${missingCritical.join(", ")}`
          );
        }
      } catch (err) {
        console.error("Auto-mapping error:", err);
        const message = err instanceof Error ? err.message : "Erreur inconnue";
        // Atomic replace (same id) — no flicker, no overlap with the analysing toast.
        samNotify.error(`Echec: ${message}`, { id: samToastId, title: "Erreur" });
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
    setGroups({});
    setExtraCandidates([]);
    setSelectedExtras([]);
    setPreviewRows([]);
    setTotalRows(0);
    setStep("upload");
    setShowStepComplete(false);
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

      const currentSessionId = useAppStore.getState().sessionId;
      if (!currentSessionId) {
        toast.error("Pas de session active. Re-importez le fichier.");
        return;
      }

      const response = await fetch(apiUrl("/api/mapping/validate"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: currentSessionId,
          mapping: mappingPayload,
          territory: "default",
          extra_cols: selectedExtras,
        }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail ?? `Validation failed: ${response.statusText}`);
      }

      const data = await response.json();

      // Use preview rows from backend response
      setPreviewRows(data.preview ?? []);
      if (typeof data.rows === "number") {
        setTotalRows(data.rows);
      }
      setStep("preview");

      if (data.missing_critical?.length > 0) {
        toast.warning(
          `Colonnes critiques manquantes : ${data.missing_critical.join(", ")}`
        );
      }
      if (data.warnings?.length > 0) {
        data.warnings.forEach((w: string) => toast.warning(w));
      }
      toast.success(`Table d'apprentissage generee : ${data.rows} lignes, ${data.columns?.length} colonnes`);
      samNotify.success("Mapping valide. Direction config !");

      // Success effects: confetti + badge
      setShowStepComplete(true);
      setTimeout(() => {
        spawnConfetti(previewContainerRef.current, 28);
      }, 200);
    } catch (err) {
      console.error("Validation error:", err);
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      samNotify.error(`Echec: ${message}`, { title: "Validation echouee" });
    }
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <GradientText as="h1" className="text-2xl">
          Donnees
        </GradientText>
        <p className="text-sm text-slate-300">
          Importez votre fichier de donnees brutes et configurez le mapping des
          colonnes vers les {TARGET_COLUMNS.length} colonnes standard.
        </p>
      </div>

      {/* Upload */}
      <GlowCard>
        <div className="flex items-center gap-2 mb-4">
          <FileSpreadsheet size={18} className="text-accent" />
          <h3 className="text-sm font-semibold text-white">
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
                  <h3 className="text-sm font-semibold text-white">
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
                    <p className="text-slate-400 mt-1">
                      {unmappedCritical.join(", ")}
                    </p>
                  </div>
                </motion.div>
              )}

              <ColumnMapper
                targetColumns={TARGET_COLUMNS}
                sourceColumns={sourceColumns}
                criticalColumns={CRITICAL_COLS}
                groups={groups}
                extraCandidates={extraCandidates}
                selectedExtras={selectedExtras}
                onExtrasChange={setSelectedExtras}
                initialMappings={mappings}
                onMappingsChange={setMappings}
              />
            </GlowCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Success banner */}
      <SuccessBanner
        message="Etape completee — Table d'apprentissage generee avec succes"
        visible={showStepComplete}
        onClose={() => setShowStepComplete(false)}
      />

      {/* Preview */}
      <AnimatePresence>
        {step === "preview" && previewRows.length > 0 && (
          <motion.div
            ref={previewContainerRef}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="relative"
          >
            <GlowCard glowColor="cyan">
              <div className="flex items-center gap-2 mb-4">
                <Table2 size={18} className="text-emerald-400" />
                <h3 className="text-sm font-semibold text-white">
                  Apercu de la table d&apos;apprentissage
                </h3>
                {showStepComplete && (
                  <motion.span
                    initial={{ opacity: 0, scale: 0.7 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="ml-auto inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-[11px] font-semibold"
                  >
                    <CheckCircle2 size={12} />
                    Etape completee
                  </motion.span>
                )}
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                <StatCard
                  label="Lignes"
                  value={(totalRows || previewRows.length).toLocaleString("fr-FR")}
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
                          className="px-2 py-1.5 text-left text-slate-300 font-medium"
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
                              className="px-2 py-1.5 text-white font-mono"
                            >
                              {String(val)}
                            </td>
                          ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-slate-400 mt-3">
                Apercu de {previewRows.length} ligne{previewRows.length > 1 ? "s" : ""}
                {totalRows > previewRows.length ? ` sur ${totalRows.toLocaleString("fr-FR")}` : ""}
                {" — "}
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
