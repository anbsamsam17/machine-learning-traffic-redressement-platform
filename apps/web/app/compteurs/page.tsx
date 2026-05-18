"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft,
  CircleDot,
  Upload,
  Play,
  Download,
  Layers,
  Settings2,
  FileText,
  MapPin,
  ChevronDown,
  Check,
  AlertCircle,
} from "lucide-react";
import { toast } from "sonner";
import { AuroraBg } from "@/components/backgrounds/aurora-bg";

// ---------------------------------------------------------------------------
// Sam notify/mood — fallback stub if agent N's @/lib/sam is not yet delivered.
// When N ships, replace the locals below with:
//   import { samNotify } from "@/lib/sam/notify";
//   import { samMood } from "@/lib/sam/store";
// ---------------------------------------------------------------------------
type SamMood =
  | "based"
  | "thinking"
  | "analysing"
  | "goodjob"
  | "error"
  | "welcome"
  | "info";

const samNotify = {
  success: (m: string) => toast.success(m),
  error: (m: string) => toast.error(m),
  analysing: (m: string) => toast.loading(m),
  thinking: (m: string) => toast.loading(m),
  info: (m: string) => toast(m),
  welcome: (m: string) => toast.success(m),
  dismiss: (id?: string | number) => toast.dismiss(id),
  promise: <T,>(
    p: Promise<T>,
    msgs: { loading: string; success: string; error: string }
  ) => toast.promise(p, msgs),
};

const samMood = {
  set: (_mood: SamMood, _message?: string, _autoResetMs?: number) => {
    /* no-op stub until agent N delivers the global mood widget */
  },
  reset: () => {
    /* no-op */
  },
};

import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";
import { StatCard } from "@/components/ui/stat-card";
import { DropZone } from "@/components/upload/drop-zone";
import { useAppStore } from "@/lib/store";
import { uploadFile, fetchJSON } from "@/lib/api";
import { apiUrl } from "@/lib/api-url";
import { cn } from "@/lib/utils";

// ============================================================================
// Constants
// ============================================================================

const TARGET_COLUMNS = [
  {
    key: "Identifiant du Poste / Section",
    label: "Identifiant du Poste / Section",
    description: "Identifiant unique du capteur (ex: 071.0001.03.3)",
    type: "text" as const,
  },
  {
    key: "Annee",
    label: "Annee",
    description: "Annee du comptage (ex: 2023)",
    type: "numeric" as const,
  },
  {
    key: "Nom de la Commune",
    label: "Nom de la Commune",
    description: "Nom de la commune ou se situe le capteur",
    type: "text" as const,
  },
  {
    key: "RD",
    label: "RD",
    description: "Route departementale (ex: D1, N7)",
    type: "text" as const,
  },
  {
    key: "PRD",
    label: "PRD",
    description: "Point de Reference Departemental (nombre)",
    type: "numeric" as const,
  },
  {
    key: "Type de capteur",
    label: "Type de capteur",
    description: "Type : Permanent, Tournant ou Temporaire",
    type: "text" as const,
  },
  {
    key: "TMJA Tous Vehicules (veh/jour)",
    label: "TMJA Tous Vehicules (veh/jour)",
    description: "TMJA tous vehicules (nombre entier)",
    type: "integer" as const,
  },
  {
    key: "TMJA Poids Lourds (veh/jour)",
    label: "TMJA Poids Lourds (veh/jour)",
    description: "TMJA poids lourds (nombre entier)",
    type: "integer" as const,
  },
];

const SENS_OPTIONS = [
  "Cumul des deux sens",
  "Moyenne des deux sens",
  "Comptage par sens de circulation",
];

interface UploadResult {
  session_id: string;
  filename: string;
  rows: number;
  columns: string[];
  preview: Record<string, unknown>[];
}

interface GenerateResult {
  session_id: string;
  stats: {
    total_rows: number;
    output_features: number;
    columns: string[];
    type_distribution: Record<string, number> | null;
    year_distribution: Record<string, number> | null;
  };
  geojson_feature_count: number;
}

type MissingAction = "default" | "remove";

// ============================================================================
// Auto-mapping helper
// ============================================================================

function autoMap(
  targetKey: string,
  sourceColumns: string[]
): string | null {
  const lower = targetKey.toLowerCase();
  const words = lower.split(/[\s/()]+/).filter((w) => w.length > 2);

  // Exact match (case insensitive)
  for (const col of sourceColumns) {
    if (col.toLowerCase() === lower) return col;
  }

  // Partial keyword match
  for (const col of sourceColumns) {
    const colLower = col.toLowerCase();
    const matchCount = words.filter((w) => colLower.includes(w)).length;
    if (matchCount >= 2 || (words.length === 1 && colLower.includes(words[0]))) {
      return col;
    }
  }

  // Common aliases
  const aliases: Record<string, string[]> = {
    "identifiant du poste / section": ["identifiant", "id_poste", "id_section", "poste", "section", "idtroncon"],
    annee: ["annee", "year", "an"],
    "nom de la commune": ["commune", "nom_commune", "city", "ville"],
    rd: ["route", "rd", "road", "nom_route"],
    prd: ["prd", "pr", "point_ref"],
    "type de capteur": ["type_capteur", "type", "capteur", "typecompteur"],
    "tmja tous vehicules (veh/jour)": ["tmjatv", "tmja_tv", "tmja_tous", "mja tv", "tmjabctv"],
    "tmja poids lourds (veh/jour)": ["tmjapl", "tmja_pl", "tmja_poids", "mja pl", "tmjabcpl"],
  };

  const targetAliases = aliases[lower] || [];
  for (const alias of targetAliases) {
    for (const col of sourceColumns) {
      if (col.toLowerCase().includes(alias)) return col;
    }
  }

  return null;
}

// ============================================================================
// Component
// ============================================================================

export default function CompteursPage() {
  const router = useRouter();
  const { reset, setSessionId } = useAppStore();

  // Section 1: Upload
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [filterFlag, setFilterFlag] = useState(true);

  // Section 2: Mapping
  const [mappings, setMappings] = useState<Record<string, string | null>>({});
  const [sensComptage, setSensComptage] = useState(SENS_OPTIONS[0]);
  const [missingActions, setMissingActions] = useState<Record<string, MissingAction>>({});
  const [missingDefaults, setMissingDefaults] = useState<Record<string, string>>({});
  const [longitudeCol, setLongitudeCol] = useState<string | null>(null);
  const [latitudeCol, setLatitudeCol] = useState<string | null>(null);

  // Section 3: Generation
  const [outputFilename, setOutputFilename] = useState("counting-loops");
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<GenerateResult | null>(null);

  // ---- Sam mood on mount ----
  useEffect(() => {
    samMood.set("based", "Charge tes donnees brutes pour generer le fichier compteurs.");
    return () => {
      samMood.reset();
    };
  }, []);

  // Derived: source columns (exclude internal cols)
  const sourceColumns = useMemo(() => {
    if (!uploadResult) return [];
    return uploadResult.columns.filter(
      (c) => !c.startsWith("__") && c !== "geometry"
    );
  }, [uploadResult]);

  const hasGeometry = useMemo(() => {
    if (!uploadResult) return false;
    return (
      uploadResult.columns.includes("geometry") ||
      uploadResult.columns.includes("__geometry_json")
    );
  }, [uploadResult]);

  const hasFlagComptage = useMemo(() => {
    if (!uploadResult) return false;
    return uploadResult.columns.includes("flag_comptage");
  }, [uploadResult]);

  // Auto-map on upload
  useEffect(() => {
    if (!uploadResult || sourceColumns.length === 0) return;
    const newMappings: Record<string, string | null> = {};
    for (const col of TARGET_COLUMNS) {
      newMappings[col.key] = autoMap(col.key, sourceColumns);
    }
    setMappings(newMappings);

    // Auto-detect lon/lat
    if (!hasGeometry) {
      for (const col of sourceColumns) {
        const l = col.toLowerCase();
        if (
          l.includes("longitude") ||
          l === "lon" ||
          l === "x" ||
          l === "lng"
        ) {
          setLongitudeCol(col);
        }
        if (
          l.includes("latitude") ||
          l === "lat" ||
          l === "y"
        ) {
          setLatitudeCol(col);
        }
      }
    }
  }, [uploadResult, sourceColumns, hasGeometry]);

  // Determine unmapped columns
  const unmappedColumns = useMemo(() => {
    return TARGET_COLUMNS.filter((col) => !mappings[col.key]).map(
      (col) => col.key
    );
  }, [mappings]);

  const mappedCount = useMemo(
    () => TARGET_COLUMNS.filter((c) => mappings[c.key]).length,
    [mappings]
  );

  // Check completeness
  const isComplete = useMemo(() => {
    // All mapped columns are valid, or unmapped ones have a proper action
    for (const col of TARGET_COLUMNS) {
      if (mappings[col.key]) continue;
      const action = missingActions[col.key];
      if (action === "remove") continue;
      if (action === "default" && missingDefaults[col.key]) continue;
      // Not mapped and no action defined → incomplete
      return false;
    }
    // If not a GeoJSON, must have lon/lat
    if (!hasGeometry && (!longitudeCol || !latitudeCol)) return false;
    return true;
  }, [mappings, missingActions, missingDefaults, hasGeometry, longitudeCol, latitudeCol]);

  // ---- Handlers -----------------------------------------------------------

  const handleUpload = useCallback(
    async (f: File) => {
      setFile(f);
      setUploading(true);
      setResult(null);
      const analysingId = samNotify.analysing("Je lis ton fichier...");
      try {
        const res = (await uploadFile("/api/upload", f, {
          mode: "TV",
        })) as UploadResult;
        setUploadResult(res);
        setSessionId(res.session_id);
        samNotify.dismiss(analysingId);
        samNotify.info(
          `Fichier charge (${res.rows.toLocaleString("fr-FR")} lignes). Configure le mapping et les colonnes.`
        );
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Erreur inconnue";
        samNotify.dismiss(analysingId);
        samNotify.error(`Erreur upload : ${msg}`);
        setFile(null);
      } finally {
        setUploading(false);
      }
    },
    [setSessionId]
  );

  const handleClear = useCallback(() => {
    setFile(null);
    setUploadResult(null);
    setMappings({});
    setMissingActions({});
    setMissingDefaults({});
    setResult(null);
    setLongitudeCol(null);
    setLatitudeCol(null);
  }, []);

  const handleGenerate = useCallback(async () => {
    if (!uploadResult) return;
    setGenerating(true);
    const thinkingId = samNotify.thinking(
      "Standardisation des colonnes et export du GeoJSON..."
    );
    samMood.set("thinking", "Generation compteurs...");
    try {
      // Build column_mapping (only mapped ones)
      const columnMapping: Record<string, string> = {};
      for (const col of TARGET_COLUMNS) {
        const src = mappings[col.key];
        if (src) columnMapping[col.key] = src;
      }

      const res = await fetchJSON<GenerateResult>("/api/compteurs/generate", {
        method: "POST",
        body: JSON.stringify({
          session_id: uploadResult.session_id,
          column_mapping: columnMapping,
          missing_columns_action: missingActions,
          missing_columns_default: {
            ...missingDefaults,
            "Sens de comptage": sensComptage,
          },
          filter_flag_comptage: filterFlag && hasFlagComptage,
          longitude_col: hasGeometry ? null : longitudeCol,
          latitude_col: hasGeometry ? null : latitudeCol,
          output_filename: outputFilename,
        }),
      });
      setResult(res);
      samNotify.dismiss(thinkingId);
      const nbLoops = res.geojson_feature_count.toLocaleString("fr-FR");
      samNotify.success(`Fichier compteurs genere. ${nbLoops} boucles standardisees.`);
      samMood.set("goodjob", "Compteurs ok", 5000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erreur inconnue";
      samNotify.dismiss(thinkingId);
      samNotify.error(`Generation echouee: ${msg}`);
      samMood.set("error", msg, 6000);
    } finally {
      setGenerating(false);
    }
  }, [
    uploadResult,
    mappings,
    missingActions,
    missingDefaults,
    sensComptage,
    filterFlag,
    hasFlagComptage,
    hasGeometry,
    longitudeCol,
    latitudeCol,
    outputFilename,
  ]);

  const handleDownload = useCallback(() => {
    if (!uploadResult) return;
    samNotify.info("Telechargement lance.");
    window.open(
      apiUrl(`/api/compteurs/download/${uploadResult.session_id}`),
      "_blank"
    );
  }, [uploadResult]);

  // ---- Render --------------------------------------------------------------

  return (
    <div className="relative min-h-screen">
      <AuroraBg />
      <div className="relative z-10 max-w-4xl mx-auto px-4 py-8 space-y-6">
        {/* Header */}
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
            Fichier Compteurs
          </div>
        </div>

        <div className="space-y-2">
          <GradientText as="h2" className="text-2xl">
            Generation du Fichier Compteurs
          </GradientText>
          <p className="text-sm text-slate-300">
            Importez vos donnees de comptage, mappez les colonnes au format
            standard counting-loops.geojson, puis generez le fichier.
          </p>
        </div>

        {/* ================================================================
            SECTION 1 : Chargement des donnees
            ================================================================ */}
        <GlowCard>
          <div className="flex items-center gap-2 mb-4">
            <Upload size={18} className="text-accent" />
            <h3 className="text-sm font-semibold text-foreground">
              1. Chargement des donnees
            </h3>
          </div>

          <DropZone
            file={file}
            onFile={handleUpload}
            onClear={handleClear}
            accept={{
              "application/json": [".geojson", ".json"],
              "text/csv": [".csv"],
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                [".xlsx"],
              "application/vnd.ms-excel": [".xls"],
            }}
            label="Deposez le fichier de comptage"
            description="CSV, Excel (.xlsx), ou GeoJSON"
          />

          {uploading && (
            <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
              <div className="w-4 h-4 border-2 border-accent border-t-transparent rounded-full animate-spin" />
              Lecture du fichier en cours...
            </div>
          )}

          {/* Upload result info */}
          <AnimatePresence>
            {uploadResult && !uploading && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="mt-4 space-y-3"
              >
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="glass-light px-3 py-1.5 rounded-lg text-xs">
                    <span className="text-accent font-bold">
                      {uploadResult.rows.toLocaleString("fr-FR")}
                    </span>{" "}
                    <span className="text-muted">lignes</span>
                  </div>
                  <div className="glass-light px-3 py-1.5 rounded-lg text-xs">
                    <span className="text-cyan font-bold">
                      {sourceColumns.length}
                    </span>{" "}
                    <span className="text-muted">colonnes</span>
                  </div>
                  {hasGeometry && (
                    <div className="glass-light px-3 py-1.5 rounded-lg text-xs text-emerald-400">
                      <MapPin size={12} className="inline mr-1" />
                      Geometrie detectee
                    </div>
                  )}
                </div>

                {/* flag_comptage filter */}
                {hasFlagComptage && (
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <div
                      className={cn(
                        "w-5 h-5 rounded border-2 flex items-center justify-center transition-all",
                        filterFlag
                          ? "bg-accent border-accent"
                          : "border-border group-hover:border-accent/40"
                      )}
                      onClick={() => setFilterFlag(!filterFlag)}
                    >
                      {filterFlag && <Check size={12} className="text-white" />}
                    </div>
                    <span
                      className="text-xs text-foreground"
                      onClick={() => setFilterFlag(!filterFlag)}
                    >
                      Conserver uniquement les capteurs avec{" "}
                      <code className="text-accent">flag_comptage = 1</code>
                    </span>
                  </label>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </GlowCard>

        {/* ================================================================
            SECTION 2 : Mapping des colonnes
            ================================================================ */}
        <AnimatePresence>
          {uploadResult && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="space-y-4"
            >
              <GlowCard>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Layers size={18} className="text-cyan" />
                    <h3 className="text-sm font-semibold text-foreground">
                      2. Mapping des colonnes
                    </h3>
                  </div>
                  <div className="glass-light px-3 py-1.5 rounded-lg text-xs font-medium">
                    <span className="text-accent">{mappedCount}</span>
                    <span className="text-muted">
                      {" "}
                      / {TARGET_COLUMNS.length} mappees
                    </span>
                  </div>
                </div>

                {/* Progress bar */}
                <div className="h-1.5 rounded-full bg-surface-light overflow-hidden mb-4">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{
                      width: `${(mappedCount / TARGET_COLUMNS.length) * 100}%`,
                    }}
                    className="h-full rounded-full bg-gradient-to-r from-accent to-cyan"
                  />
                </div>

                <p className="text-xs text-muted mb-4">
                  Associez chaque colonne requise du format counting-loops a une
                  colonne de votre fichier source.
                </p>

                {/* Mapping rows */}
                <div className="space-y-2">
                  {TARGET_COLUMNS.map((col, idx) => {
                    const mapped = mappings[col.key];
                    return (
                      <motion.div
                        key={col.key}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: idx * 0.03 }}
                        className={cn(
                          "grid grid-cols-[1fr_auto_1fr] items-center gap-3 p-3 rounded-lg transition-colors",
                          mapped
                            ? "bg-accent/5 border border-accent/10"
                            : "bg-surface-light/50 border border-amber-500/20"
                        )}
                      >
                        {/* Target */}
                        <div className="flex items-center gap-2 min-w-0">
                          <div
                            className={cn(
                              "w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0",
                              mapped
                                ? "bg-emerald-500/20 text-emerald-400"
                                : "bg-amber-500/20 text-amber-400"
                            )}
                          >
                            {mapped ? (
                              <Check size={10} />
                            ) : (
                              <AlertCircle size={10} />
                            )}
                          </div>
                          <div className="min-w-0">
                            <span className="text-xs font-medium text-foreground block truncate">
                              {col.label}
                            </span>
                            <span className="text-[10px] text-muted block truncate">
                              {col.description}
                            </span>
                          </div>
                        </div>

                        {/* Arrow */}
                        <span className="text-muted text-xs">&larr;</span>

                        {/* Source dropdown */}
                        <div className="relative">
                          <select
                            value={mapped ?? ""}
                            onChange={(e) =>
                              setMappings((prev) => ({
                                ...prev,
                                [col.key]: e.target.value || null,
                              }))
                            }
                            className={cn(
                              "w-full text-xs bg-surface border rounded-lg px-3 py-2 text-foreground outline-none focus:border-accent/40 cursor-pointer truncate appearance-none pr-8",
                              !mapped ? "border-amber-500/40" : "border-border"
                            )}
                          >
                            <option value="">-- Non mappe --</option>
                            {sourceColumns.map((sc) => (
                              <option key={sc} value={sc}>
                                {sc}
                              </option>
                            ))}
                          </select>
                          <ChevronDown
                            size={14}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted pointer-events-none"
                          />
                        </div>
                      </motion.div>
                    );
                  })}
                </div>

                {/* Sens de comptage (always as extra config) */}
                <div className="mt-6 p-4 rounded-lg bg-surface-light/50 border border-border">
                  <div className="flex items-center gap-2 mb-3">
                    <Settings2 size={14} className="text-accent" />
                    <span className="text-xs font-semibold text-foreground">
                      Sens de comptage
                    </span>
                    <span className="text-[10px] text-muted">
                      (colonne obligatoire, valeur par defaut appliquee a toutes
                      les lignes)
                    </span>
                  </div>
                  <div className="flex gap-2 flex-wrap">
                    {SENS_OPTIONS.map((opt) => (
                      <button
                        key={opt}
                        type="button"
                        onClick={() => setSensComptage(opt)}
                        className={cn(
                          "px-3 py-1.5 rounded-lg text-xs font-medium transition-all border",
                          sensComptage === opt
                            ? "bg-accent/20 border-accent/50 text-accent"
                            : "bg-surface border-border text-muted hover:border-accent/30 hover:text-foreground"
                        )}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Longitude / Latitude (only if no geometry) */}
                {!hasGeometry && (
                  <div className="mt-4 p-4 rounded-lg bg-amber-500/5 border border-amber-500/20">
                    <div className="flex items-center gap-2 mb-3">
                      <MapPin size={14} className="text-amber-400" />
                      <span className="text-xs font-semibold text-amber-300">
                        Coordonnees geographiques requises
                      </span>
                    </div>
                    <p className="text-[10px] text-muted mb-3">
                      Votre fichier ne contient pas de geometrie. Selectionnez
                      les colonnes longitude et latitude (WGS84).
                    </p>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-[10px] text-muted block mb-1">
                          Longitude
                        </label>
                        <select
                          value={longitudeCol ?? ""}
                          onChange={(e) =>
                            setLongitudeCol(e.target.value || null)
                          }
                          className="w-full text-xs bg-surface border border-border rounded-lg px-3 py-2 text-foreground outline-none focus:border-accent/40"
                        >
                          <option value="">-- Selectionner --</option>
                          {sourceColumns.map((sc) => (
                            <option key={sc} value={sc}>
                              {sc}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="text-[10px] text-muted block mb-1">
                          Latitude
                        </label>
                        <select
                          value={latitudeCol ?? ""}
                          onChange={(e) =>
                            setLatitudeCol(e.target.value || null)
                          }
                          className="w-full text-xs bg-surface border border-border rounded-lg px-3 py-2 text-foreground outline-none focus:border-accent/40"
                        >
                          <option value="">-- Selectionner --</option>
                          {sourceColumns.map((sc) => (
                            <option key={sc} value={sc}>
                              {sc}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>
                )}
              </GlowCard>

              {/* Unmapped columns config */}
              {unmappedColumns.length > 0 && (
                <GlowCard glowColor="violet">
                  <div className="flex items-center gap-2 mb-4">
                    <Settings2 size={18} className="text-violet" />
                    <h3 className="text-sm font-semibold text-foreground">
                      Colonnes supplementaires
                    </h3>
                    <span className="glass-light px-2 py-0.5 rounded text-[10px] text-muted">
                      {unmappedColumns.length} non mappee(s)
                    </span>
                  </div>
                  <p className="text-xs text-muted mb-4">
                    Pour chaque colonne non mappee, choisissez une valeur par
                    defaut ou supprimez-la du fichier de sortie.
                  </p>

                  <div className="space-y-3">
                    {unmappedColumns.map((colKey) => {
                      const colDef = TARGET_COLUMNS.find(
                        (c) => c.key === colKey
                      );
                      const action = missingActions[colKey] || "default";
                      const defaultVal = missingDefaults[colKey] || "";

                      // Suggested defaults
                      let suggestedDefault = "";
                      if (colKey.includes("Type de capteur"))
                        suggestedDefault = "Permanent";
                      if (colKey === "Annee")
                        suggestedDefault = "2023";

                      return (
                        <div
                          key={colKey}
                          className="p-3 rounded-lg bg-surface-light/50 border border-border"
                        >
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs font-medium text-foreground">
                              {colKey}
                            </span>
                            <span className="text-[10px] text-muted">
                              {colDef?.description}
                            </span>
                          </div>

                          {/* Action radio */}
                          <div className="flex gap-2 mb-2">
                            <button
                              type="button"
                              onClick={() =>
                                setMissingActions((prev) => ({
                                  ...prev,
                                  [colKey]: "default",
                                }))
                              }
                              className={cn(
                                "flex-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border text-center",
                                action === "default"
                                  ? "bg-accent/15 border-accent/40 text-accent"
                                  : "bg-surface border-border text-muted hover:border-accent/30"
                              )}
                            >
                              Valeur par defaut
                            </button>
                            <button
                              type="button"
                              onClick={() =>
                                setMissingActions((prev) => ({
                                  ...prev,
                                  [colKey]: "remove",
                                }))
                              }
                              className={cn(
                                "flex-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border text-center",
                                action === "remove"
                                  ? "bg-red-500/15 border-red-500/40 text-red-400"
                                  : "bg-surface border-border text-muted hover:border-red-500/30"
                              )}
                            >
                              Supprimer
                            </button>
                          </div>

                          {/* Default value input */}
                          {action === "default" && (
                            <input
                              type="text"
                              value={defaultVal}
                              onChange={(e) =>
                                setMissingDefaults((prev) => ({
                                  ...prev,
                                  [colKey]: e.target.value,
                                }))
                              }
                              placeholder={
                                suggestedDefault
                                  ? `Suggestion : ${suggestedDefault}`
                                  : "Saisir une valeur par defaut..."
                              }
                              className="w-full text-xs bg-surface border border-border rounded-lg px-3 py-2 text-foreground placeholder:text-muted/50 outline-none focus:border-accent/40"
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                </GlowCard>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* ================================================================
            SECTION 3 : Generation
            ================================================================ */}
        <AnimatePresence>
          {uploadResult && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <GlowCard>
                <div className="flex items-center gap-2 mb-4">
                  <FileText size={18} className="text-accent" />
                  <h3 className="text-sm font-semibold text-foreground">
                    3. Generation
                  </h3>
                </div>

                <div className="flex items-center gap-4 mb-4">
                  <div className="flex-1">
                    <label className="text-[10px] text-muted block mb-1">
                      Nom du fichier de sortie
                    </label>
                    <div className="flex items-center">
                      <input
                        type="text"
                        value={outputFilename}
                        onChange={(e) => setOutputFilename(e.target.value)}
                        className="flex-1 text-xs bg-surface border border-border rounded-l-lg px-3 py-2 text-foreground outline-none focus:border-accent/40"
                      />
                      <span className="text-xs bg-surface-light border border-l-0 border-border rounded-r-lg px-3 py-2 text-muted">
                        .geojson
                      </span>
                    </div>
                  </div>
                </div>

                {!isComplete && (
                  <div className="mb-4 p-3 rounded-lg bg-amber-500/5 border border-amber-500/20 text-xs text-amber-300">
                    <AlertCircle
                      size={12}
                      className="inline mr-1 -mt-0.5"
                    />
                    Configuration incomplete. Completez le mapping ou
                    configurez les colonnes manquantes.
                  </div>
                )}

                <div className="flex justify-center">
                  <NeonButton
                    onClick={handleGenerate}
                    disabled={!isComplete || generating}
                    icon={
                      generating ? undefined : <Play size={16} />
                    }
                    className={generating ? "animate-pulse-glow" : ""}
                  >
                    {generating
                      ? "Generation en cours..."
                      : "Generer le fichier compteurs"}
                  </NeonButton>
                </div>
              </GlowCard>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ================================================================
            RESULTS
            ================================================================ */}
        <AnimatePresence>
          {result && (
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
                    Fichier compteurs genere avec succes
                  </p>

                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3 max-w-lg mx-auto">
                    <StatCard
                      label="Boucles generees"
                      value={result.geojson_feature_count.toLocaleString(
                        "fr-FR"
                      )}
                    />
                    <StatCard
                      label="Lignes source"
                      value={result.stats.total_rows.toLocaleString(
                        "fr-FR"
                      )}
                    />
                    <StatCard
                      label="Colonnes"
                      value={result.stats.columns.length}
                    />
                  </div>

                  {/* Type distribution */}
                  {result.stats.type_distribution && (
                    <div className="text-left max-w-md mx-auto">
                      <p className="text-[10px] text-muted uppercase tracking-wide mb-2">
                        Repartition par type
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(
                          result.stats.type_distribution
                        ).map(([type, count]) => (
                          <div
                            key={type}
                            className="glass-light px-2 py-1 rounded text-xs"
                          >
                            <span className="text-foreground font-medium">
                              {type}
                            </span>
                            <span className="text-muted ml-1">{count}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Year distribution */}
                  {result.stats.year_distribution && (
                    <div className="text-left max-w-md mx-auto">
                      <p className="text-[10px] text-muted uppercase tracking-wide mb-2">
                        Repartition par annee
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(
                          result.stats.year_distribution
                        ).map(([year, count]) => (
                          <div
                            key={year}
                            className="glass-light px-2 py-1 rounded text-xs"
                          >
                            <span className="text-foreground font-medium">
                              {year}
                            </span>
                            <span className="text-muted ml-1">{count}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="flex items-center justify-center gap-3 pt-2">
                    <NeonButton
                      variant="secondary"
                      icon={<Download size={16} />}
                      onClick={handleDownload}
                    >
                      Telecharger GeoJSON
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
