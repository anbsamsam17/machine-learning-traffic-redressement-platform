"use client";

import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { apiUrl } from "@/lib/api-url";
import { fetchWithAuth } from "@/lib/auth";
import { FileSpreadsheet, Wand2, Table2, AlertTriangle, CheckCircle2, ArrowRight } from "lucide-react";
import { toast } from "sonner";
import { samNotify } from "@/lib/sam-fallback";
import { DropZone } from "@/components/upload/drop-zone";
import {
  ColumnMapper,
  type ColumnMapping,
} from "@/components/mapping/column-mapper";
import { SuccessBanner } from "@/components/ui/success-banner";
import {
  GlowCardPremium,
  MagneticButton,
  NeonBorder,
  RevealOnScroll,
  ShimmerText,
  StatBadge,
} from "@/components/ui";
import { useAppStore } from "@/lib/store";
import { spawnConfetti } from "@/lib/success-effects";

// ── 30 target columns (Etape1_MDL_TV refonte FCD HERE + HPM/HPS) ──────────
// Mirrored from apps/api/app/routers/mapping.py:TARGET_COLUMNS.
const TARGET_COLUMNS = [
  // Identification (4)
  "Identifiant", "Annee", "Adresse", "Type Compteur",
  // Comptage capteur (4)
  "TMJOBCTV", "TMJOBCPL", "TMJOBCTV_HPM", "TMJOBCTV_HPS",
  // FCD HERE (4) — TV/PL journalier + HPM/HPS horaires
  "TMJOFCDTV", "TMJOFCDPL", "FCD_HPM_TV", "FCD_HPS_TV",
  // Taux de penetration (4) — TV/PL journalier + HPM/HPS horaires
  "TxPen", "TxPenPL", "TxPen_HPM", "TxPen_HPS",
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
// TV — cible TxPen, features FCD TV/PL + distances/vitesses.
const CRITICAL_COLS_TV = [
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

// PL — cible TxPenPL.
const CRITICAL_COLS_PL = [
  "TMJOBCPL",
  "TMJOFCDPL",
  "TxPenPL",
  "truck_avg_distance_m",
  "truck_avg_min_distance_m",
  "truck_avg_speed_kmh",
  "functional_class",
];

// HPM — fenetre 8h-9h, cible TxPen_HPM (v/h).
const CRITICAL_COLS_HPM = [
  "TMJOBCTV_HPM",   // boucle de comptage 8h-9h (cible derivable)
  "FCD_HPM_TV",     // FCD HERE 8h-9h
  "TxPen_HPM",      // cible (recalculable si manquante)
  "avg_distance_m",
  "avg_speed_kmh",
  "functional_class",
];

// HPS — fenetre 17h-18h, cible TxPen_HPS (v/h).
const CRITICAL_COLS_HPS = [
  "TMJOBCTV_HPS",
  "FCD_HPS_TV",
  "TxPen_HPS",
  "avg_distance_m",
  "avg_speed_kmh",
  "functional_class",
];

function pickCriticalCols(mode: string | null | undefined): string[] {
  switch (mode) {
    case "hpm":
      return CRITICAL_COLS_HPM;
    case "hps":
      return CRITICAL_COLS_HPS;
    case "pl":
      return CRITICAL_COLS_PL;
    default:
      return CRITICAL_COLS_TV;
  }
}

// Mode → backend ModelKind (uppercase). The backend `mode` payload uses
// "TV" | "PL" | "HPM" | "HPS". The frontend store keeps lowercase.
function modeToBackend(mode: string | null | undefined): string {
  switch (mode) {
    case "hpm":
      return "HPM";
    case "hps":
      return "HPS";
    case "pl":
      return "PL";
    default:
      return "TV";
  }
}

// Pretty mode labels for headers and copy.
function modeMeta(mode: string | null | undefined) {
  switch (mode) {
    case "hpm":
      return {
        kind: "HPM" as const,
        label: "Heure de Pointe Matin (8h-9h)",
        unit: "v/h",
        outputName: "HPM_FCDr",
      };
    case "hps":
      return {
        kind: "HPS" as const,
        label: "Heure de Pointe Soir (17h-18h)",
        unit: "v/h",
        outputName: "HPS_FCDr",
      };
    case "pl":
      return {
        kind: "PL" as const,
        label: "Poids Lourds",
        unit: "v/j",
        outputName: "DPL",
      };
    default:
      return {
        kind: "TV" as const,
        label: "Tous Vehicules",
        unit: "v/j",
        outputName: "TVr",
      };
  }
}

export default function DonneesPage() {
  const { mode, setFileName, setMappingValidated, setPreviewReady } = useAppStore();
  const storedSessionId = useAppStore((s) => s.sessionId);
  // Mode-aware constants (TV/PL/HPM/HPS). Recomputed when the store hydrates.
  const CRITICAL_COLS = useMemo(() => pickCriticalCols(mode), [mode]);
  const meta = useMemo(() => modeMeta(mode), [mode]);
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

  // ── Bug 1 (T1) — Defensive guard contre sessionId perime ─────────────────
  // Quand le store contient un sessionId mais que le backend ne le reconnait
  // plus (TTL expire / serveur redemarre / session purgee), on doit
  // SILENCIEUSEMENT clear l'etat local et RESTER sur /donnees au lieu de
  // naviguer ailleurs. Sans ce guard, restoreFromBackend + autres useEffect
  // pouvaient produire des navigations imprevisibles ~1-2s apres le mount.
  useEffect(() => {
    if (!storedSessionId) return;
    // On a deja une nouvelle session locale (fichier vient d'etre uploade) :
    // on saute le check, l'upload aura cree une session valide cote backend.
    if (file) return;

    let cancelled = false;
    (async () => {
      try {
        const res = await fetchWithAuth(apiUrl("/api/sessions/current"));
        if (cancelled) return;
        if (res.status === 404) {
          // Backend ne connait plus de session active pour cet user.
          // Clear le sessionId local + flags de pipeline, et RESTE sur la page.
          useAppStore.setState({
            sessionId: null,
            taskId: null,
            mappingValidated: false,
            previewReady: false,
          });
          toast.info("Session expiree — charge un nouveau fichier");
          return;
        }
        if (!res.ok) return;
        const data = await res.json().catch(() => null);
        if (cancelled || !data) return;
        // Si le backend a une session pour cet user mais l'id ne matche pas
        // le sessionId local (ex. autre device, store stale), on align sur
        // le backend sans naviguer.
        if (data.session_id && data.session_id !== storedSessionId) {
          useAppStore.setState({ sessionId: data.session_id });
        }
      } catch {
        // Network error — on n'a pas la confirmation, on laisse l'etat tel
        // quel. L'utilisateur peut re-uploader si quelque chose casse.
      }
    })();
    return () => {
      cancelled = true;
    };
    // Le guard ne doit s'executer qu'une fois par session active connue.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storedSessionId]);

  const handleFile = useCallback(
    async (f: File) => {
      setFile(f);
      setFileName(f.name);
      setIsAutoMapping(true);
      // Reset gating flags — a new upload invalidates any previous mapping
      // confirmation. Without this, the layout footer "Continuer" button
      // stays enabled and the user can advance to Config with stale state.
      setMappingValidated(false);
      setPreviewReady(false);

      const samToastId = "donnees-upload";
      samNotify.analysing("Je lis ton fichier, ca prend quelques secondes...", {
        id: samToastId,
      });

      try {
        // Step 1: Upload file to get session_id
        const formData = new FormData();
        formData.append("file", f);
        // Backend ModelKind expects uppercase (TV/PL/HPM/HPS).
        formData.append("mode", modeToBackend(mode));

        const uploadResponse = await fetchWithAuth(apiUrl("/api/upload"), {
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
        const mapResponse = await fetchWithAuth(apiUrl("/api/mapping/auto"), {
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
    // `mode` change → backend payload changes (TV/PL/HPM/HPS), and
    // `CRITICAL_COLS` flips per mode → missingCritical warning must reflect
    // the right cible set.
    [setFileName, setMappingValidated, setPreviewReady, mode, CRITICAL_COLS]
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
    setMappingValidated(false);
    setPreviewReady(false);
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

      const response = await fetchWithAuth(apiUrl("/api/mapping/validate"), {
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
      // APP-P1-6: mark pipeline guard flags so Continuer button unlocks
      setMappingValidated(true);
      setPreviewReady(true);

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

  // Mapping confidence aggregates — surfaced as StatBadges in the preview
  // section. Auto-detection confidence per row keeps the mapping panel honest.
  const mappedCount = useMemo(
    () => mappings.filter((m) => m.source !== null).length,
    [mappings]
  );
  const avgConfidence = useMemo(() => {
    const mapped = mappings.filter((m) => m.source !== null);
    if (mapped.length === 0) return 0;
    return Math.round(
      mapped.reduce((s, m) => s + m.confidence, 0) / mapped.length
    );
  }, [mappings]);

  return (
    <div className="space-y-6">
      {/* Header — ShimmerText H1 + meta line */}
      <RevealOnScroll variant="fade" stagger={0.05}>
        <div className="space-y-2">
          <ShimmerText as="h1" variant="neon-white" className="text-2xl sm:text-3xl">
            {meta.kind === "HPM" || meta.kind === "HPS"
              ? `Donnees - Pipeline ${meta.kind} (${meta.kind === "HPM" ? "8h-9h" : "17h-18h"})`
              : "Donnees"}
          </ShimmerText>
          <p className="text-sm text-text-muted">
            Importez votre fichier de donnees brutes et configurez le mapping
            des colonnes vers les {TARGET_COLUMNS.length} colonnes standard.
            {(meta.kind === "HPM" || meta.kind === "HPS") && (
              <>
                {" "}Cible : <span className="font-mono text-amber-300">TxPen_{meta.kind}</span>
                {" "}- sortie : <span className="font-mono text-amber-300">{meta.outputName}</span>
                {" "}({meta.unit}).
              </>
            )}
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <StatBadge label="Mode" value={meta.kind} tone="violet" size="sm" />
            <StatBadge
              label="Cibles standard"
              value={TARGET_COLUMNS.length}
              tone="accent"
              size="sm"
            />
            <StatBadge
              label="Cles critiques"
              value={CRITICAL_COLS.length}
              tone="amber"
              size="sm"
            />
            {file && (
              <StatBadge
                label="Fichier"
                value={file.name.length > 24 ? `${file.name.slice(0, 22)}...` : file.name}
                tone="cyan"
                size="sm"
              />
            )}
          </div>
        </div>
      </RevealOnScroll>

      {/* Upload — NeonBorder cyan quand auto-mapping en cours, sinon GlowCardPremium */}
      {isAutoMapping ? (
        <NeonBorder tone="cyan" speed={2.2} thickness={1}>
          <div className="p-5">
            <div className="flex items-center gap-2 mb-4">
              <FileSpreadsheet size={18} className="text-[#22d3ee]" />
              <h3 className="text-sm font-semibold text-text">Fichier source</h3>
              <span className="text-xs text-[#22d3ee] ml-2 inline-flex items-center gap-1.5">
                <span className="size-1.5 rounded-full bg-[#22d3ee] animate-pulse" />
                Auto-mapping en cours...
              </span>
            </div>
            <DropZone file={file} onFile={handleFile} onClear={handleClear} />
          </div>
        </NeonBorder>
      ) : (
        <GlowCardPremium tone="cyan" intensity={0.5}>
          <div className="flex items-center gap-2 mb-4">
            <FileSpreadsheet size={18} className="text-[#22d3ee]" />
            <h3 className="text-sm font-semibold text-text">Fichier source</h3>
          </div>
          <DropZone file={file} onFile={handleFile} onClear={handleClear} />
        </GlowCardPremium>
      )}

      {/* Mapping — GlowCardPremium accent + StatBadge confidence + MagneticButton validation */}
      <AnimatePresence>
        {step === "mapping" && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            <GlowCardPremium tone="accent" intensity={0.55}>
              <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="flex items-center gap-2">
                    <Table2 size={18} className="text-[#22d3ee]" />
                    <h3 className="text-sm font-semibold text-text">
                      Mapping des colonnes
                    </h3>
                  </div>
                  <StatBadge
                    label="Mappees"
                    value={`${mappedCount}/${TARGET_COLUMNS.length}`}
                    tone={mappedCount >= 5 ? "success" : "neutral"}
                    size="sm"
                  />
                  <StatBadge
                    label="Critiques"
                    value={`${mappedCriticalCount}/${CRITICAL_COLS.length}`}
                    tone={
                      mappedCriticalCount === CRITICAL_COLS.length
                        ? "success"
                        : mappedCriticalCount >= CRITICAL_COLS.length - 2
                          ? "amber"
                          : "danger"
                    }
                    size="sm"
                  />
                  {avgConfidence > 0 && (
                    <StatBadge
                      label="Confiance"
                      value={`${avgConfidence}%`}
                      tone={
                        avgConfidence >= 90
                          ? "success"
                          : avgConfidence >= 70
                            ? "amber"
                            : "danger"
                      }
                      size="sm"
                    />
                  )}
                </div>
                <MagneticButton
                  variant="primary"
                  size="md"
                  onClick={handleValidateMapping}
                  disabled={mappedCount < 5}
                  title={
                    mappedCount < 5
                      ? "Mappez au moins 5 colonnes pour continuer"
                      : undefined
                  }
                >
                  <Wand2 size={14} />
                  Valider et generer la table
                </MagneticButton>
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
                    <p className="text-text-muted mt-1">
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
            </GlowCardPremium>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Success banner */}
      <SuccessBanner
        message="Etape completee — Table d'apprentissage generee avec succes"
        visible={showStepComplete}
        onClose={() => setShowStepComplete(false)}
      />

      {/* Preview — NeonBorder success quand validation faite, StatBadge tone-aware */}
      <AnimatePresence>
        {step === "preview" && previewRows.length > 0 && (
          <motion.div
            ref={previewContainerRef}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="relative"
          >
            <NeonBorder
              tone={showStepComplete ? "success" : "cyan"}
              speed={3.5}
              thickness={1}
            >
              <div className="p-5">
                <div className="flex items-center gap-2 mb-4">
                  <Table2 size={18} className="text-emerald-400" />
                  <h3 className="text-sm font-semibold text-text">
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
                <div className="flex flex-wrap gap-2 mb-4">
                  <StatBadge
                    label="Lignes"
                    value={(totalRows || previewRows.length).toLocaleString("fr-FR")}
                    tone="cyan"
                  />
                  <StatBadge
                    label="Mappees"
                    value={`${mappings.filter((m) => m.source).length}/${TARGET_COLUMNS.length}`}
                    tone="accent"
                  />
                  <StatBadge
                    label="Critiques"
                    value={`${mappedCriticalCount}/${CRITICAL_COLS.length}`}
                    tone={
                      mappedCriticalCount === CRITICAL_COLS.length
                        ? "success"
                        : "amber"
                    }
                  />
                  <StatBadge
                    label="Confiance moy."
                    value={`${avgConfidence}%`}
                    tone={
                      avgConfidence >= 90
                        ? "success"
                        : avgConfidence >= 70
                          ? "amber"
                          : "danger"
                    }
                  />
                </div>
                <div className="overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-bg-elevated/95 backdrop-blur">
                      <tr className="border-b border-border">
                        {Object.keys(previewRows[0]).slice(0, 8).map((col) => (
                          <th
                            key={col}
                            className="px-3 py-2 text-left text-text font-semibold uppercase tracking-wider text-[10px]"
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
                          className="border-b border-border/30 hover:bg-[rgba(99,102,241,0.06)] transition-colors"
                        >
                          {Object.values(row)
                            .slice(0, 8)
                            .map((val, j) => (
                              <td
                                key={j}
                                className="px-3 py-1.5 text-text font-mono tabular-nums"
                              >
                                {String(val)}
                              </td>
                            ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-xs text-text-muted mt-3">
                  Apercu de {previewRows.length} ligne{previewRows.length > 1 ? "s" : ""}
                  {totalRows > previewRows.length ? ` sur ${totalRows.toLocaleString("fr-FR")}` : ""}
                  {" - "}
                  Affichage des 8 premieres colonnes sur{" "}
                  {Object.keys(previewRows[0]).length} colonnes totales.
                </p>

                {/* CTA — Continuer vers Config en MagneticButton lg */}
                {showStepComplete && (
                  <div className="mt-5 pt-5 border-t border-border flex justify-end">
                    <MagneticButton
                      asChild
                      variant="primary"
                      size="lg"
                    >
                      <a href="/config">
                        Continuer vers Configuration
                        <ArrowRight size={16} />
                      </a>
                    </MagneticButton>
                  </div>
                )}
              </div>
            </NeonBorder>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
