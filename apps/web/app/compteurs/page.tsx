"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
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
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { StatCard } from "@/components/ui/stat-card";
import { DropZone } from "@/components/upload/drop-zone";
import { useAppStore } from "@/lib/store";
import { uploadFile, fetchJSON } from "@/lib/api";
import { apiUrl } from "@/lib/api-url";
import { cn } from "@/lib/utils";

// ─── Target schema for counting-loops.geojson ───────────────────────────────
const TARGET_COLUMNS = [
  { key: "Identifiant du Poste / Section", label: "Identifiant du Poste / Section", description: "Identifiant unique du capteur (ex: 071.0001.03.3)", type: "text" as const },
  { key: "Annee", label: "Annee", description: "Annee du comptage (ex: 2023)", type: "numeric" as const },
  { key: "Nom de la Commune", label: "Nom de la Commune", description: "Nom de la commune ou se situe le capteur", type: "text" as const },
  { key: "RD", label: "RD", description: "Route departementale (ex: D1, N7)", type: "text" as const },
  { key: "PRD", label: "PRD", description: "Point de Reference Departemental (nombre)", type: "numeric" as const },
  { key: "Type de capteur", label: "Type de capteur", description: "Type : Permanent, Tournant ou Temporaire", type: "text" as const },
  { key: "TMJA Tous Vehicules (veh/jour)", label: "TMJA Tous Vehicules (veh/jour)", description: "TMJA tous vehicules (nombre entier)", type: "integer" as const },
  { key: "TMJA Poids Lourds (veh/jour)", label: "TMJA Poids Lourds (veh/jour)", description: "TMJA poids lourds (nombre entier)", type: "integer" as const },
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

// ─── Fuzzy auto-mapping for the source columns ──────────────────────────────
function autoMap(targetKey: string, sourceColumns: string[]): string | null {
  const lower = targetKey.toLowerCase();
  const words = lower.split(/[\s/()]+/).filter((w) => w.length > 2);

  for (const col of sourceColumns) {
    if (col.toLowerCase() === lower) return col;
  }

  for (const col of sourceColumns) {
    const colLower = col.toLowerCase();
    const matchCount = words.filter((w) => colLower.includes(w)).length;
    if (matchCount >= 2 || (words.length === 1 && colLower.includes(words[0]))) {
      return col;
    }
  }

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

// ═══════════════════════════════════════════════════════════════════════════
// Page
// ═══════════════════════════════════════════════════════════════════════════
export default function CompteursPage() {
  const router = useRouter();
  const { reset, setSessionId } = useAppStore();

  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [filterFlag, setFilterFlag] = useState(true);

  const [mappings, setMappings] = useState<Record<string, string | null>>({});
  const [sensComptage, setSensComptage] = useState(SENS_OPTIONS[0]);
  const [missingActions, setMissingActions] = useState<Record<string, MissingAction>>({});
  const [missingDefaults, setMissingDefaults] = useState<Record<string, string>>({});
  const [longitudeCol, setLongitudeCol] = useState<string | null>(null);
  const [latitudeCol, setLatitudeCol] = useState<string | null>(null);

  const [outputFilename, setOutputFilename] = useState("counting-loops");
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<GenerateResult | null>(null);

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

    if (!hasGeometry) {
      for (const col of sourceColumns) {
        const l = col.toLowerCase();
        if (l.includes("longitude") || l === "lon" || l === "x" || l === "lng") {
          setLongitudeCol(col);
        }
        if (l.includes("latitude") || l === "lat" || l === "y") {
          setLatitudeCol(col);
        }
      }
    }
  }, [uploadResult, sourceColumns, hasGeometry]);

  const unmappedColumns = useMemo(
    () => TARGET_COLUMNS.filter((col) => !mappings[col.key]).map((col) => col.key),
    [mappings]
  );

  const mappedCount = useMemo(
    () => TARGET_COLUMNS.filter((c) => mappings[c.key]).length,
    [mappings]
  );

  const isComplete = useMemo(() => {
    for (const col of TARGET_COLUMNS) {
      if (mappings[col.key]) continue;
      const action = missingActions[col.key];
      if (action === "remove") continue;
      if (action === "default" && missingDefaults[col.key]) continue;
      return false;
    }
    if (!hasGeometry && (!longitudeCol || !latitudeCol)) return false;
    return true;
  }, [mappings, missingActions, missingDefaults, hasGeometry, longitudeCol, latitudeCol]);

  const handleUpload = useCallback(
    async (f: File) => {
      setFile(f);
      setUploading(true);
      setResult(null);
      try {
        const res = (await uploadFile("/api/upload", f, { mode: "TV" })) as UploadResult;
        setUploadResult(res);
        setSessionId(res.session_id);
        toast.success(`${res.rows} lignes chargees depuis ${res.filename}`);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Erreur inconnue";
        toast.error(msg);
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
    try {
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
      toast.success(
        `Fichier genere : ${res.geojson_feature_count} boucles de comptage`
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erreur inconnue";
      toast.error(msg);
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
    window.open(
      apiUrl(`/api/compteurs/download/${uploadResult.session_id}`),
      "_blank"
    );
  }, [uploadResult]);

  const progressPct =
    TARGET_COLUMNS.length > 0
      ? Math.round((mappedCount / TARGET_COLUMNS.length) * 100)
      : 0;

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            reset();
            router.push("/");
          }}
          icon={<ArrowLeft size={14} />}
        >
          Accueil
        </Button>
        <span className="inline-flex items-center px-2 h-6 rounded text-[11px] font-medium bg-accent-subtle text-accent border border-accent/20 uppercase tracking-wide">
          Fichier Compteurs
        </span>
      </div>

      <div className="space-y-1.5">
        <h2 className="text-2xl font-semibold text-text">
          Generation du Fichier Compteurs
        </h2>
        <p className="text-sm text-text-muted">
          Importez vos donnees de comptage, mappez les colonnes au format
          standard counting-loops.geojson, puis generez le fichier.
        </p>
      </div>

      {/* 1. Upload */}
      <section className="surface-elevated p-5">
        <div className="flex items-center gap-2 mb-4">
          <Upload size={16} className="text-accent" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-text">
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
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
            "application/vnd.ms-excel": [".xls"],
          }}
          label="Deposez le fichier de comptage"
          description="CSV, Excel (.xlsx), ou GeoJSON"
        />

        {uploading && (
          <div className="mt-3 flex items-center gap-2 text-xs text-text-muted">
            <Loader2 size={12} className="animate-spin" aria-hidden="true" />
            Lecture du fichier en cours...
          </div>
        )}

        {uploadResult && !uploading && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="px-2.5 h-7 rounded bg-bg-subtle border border-border flex items-center gap-1 text-xs">
                <span className="text-accent font-mono tabular-nums font-semibold">
                  {uploadResult.rows.toLocaleString("fr-FR")}
                </span>
                <span className="text-text-muted">lignes</span>
              </div>
              <div className="px-2.5 h-7 rounded bg-bg-subtle border border-border flex items-center gap-1 text-xs">
                <span className="text-accent font-mono tabular-nums font-semibold">
                  {sourceColumns.length}
                </span>
                <span className="text-text-muted">colonnes</span>
              </div>
              {hasGeometry && (
                <div className="px-2.5 h-7 rounded bg-success/10 border border-success/30 flex items-center gap-1 text-xs text-success">
                  <MapPin size={11} aria-hidden="true" />
                  Geometrie detectee
                </div>
              )}
            </div>

            {hasFlagComptage && (
              <label className="flex items-center gap-2 cursor-pointer group">
                <span className="relative inline-flex">
                  <input
                    type="checkbox"
                    checked={filterFlag}
                    onChange={(e) => setFilterFlag(e.target.checked)}
                    className="sr-only peer"
                  />
                  <span className="w-9 h-5 rounded-full bg-bg-subtle peer-checked:bg-accent transition-colors" />
                  <span
                    className={cn(
                      "absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform",
                      filterFlag && "translate-x-4"
                    )}
                  />
                </span>
                <span className="text-xs text-text-muted group-hover:text-text">
                  Conserver uniquement les capteurs avec{" "}
                  <code className="text-accent font-mono">flag_comptage = 1</code>
                </span>
              </label>
            )}
          </div>
        )}
      </section>

      {/* 2. Mapping */}
      {uploadResult && (
        <section className="surface-elevated p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Layers size={16} className="text-accent" aria-hidden="true" />
              <h3 className="text-sm font-semibold text-text">
                2. Mapping des colonnes
              </h3>
            </div>
            <span className="px-2.5 h-7 rounded bg-bg-subtle border border-border flex items-center text-xs font-medium">
              <span className="text-accent font-mono tabular-nums">{mappedCount}</span>
              <span className="text-text-muted">
                {" "}
                / {TARGET_COLUMNS.length} mappees
              </span>
            </span>
          </div>

          <div
            className="h-1 rounded-full bg-bg-subtle overflow-hidden"
            role="progressbar"
            aria-valuenow={progressPct}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-full bg-accent transition-[width] duration-300"
              style={{ width: `${progressPct}%` }}
            />
          </div>

          <p className="text-xs text-text-muted">
            Associez chaque colonne requise du format counting-loops a une
            colonne de votre fichier source.
          </p>

          <div className="space-y-1.5">
            {TARGET_COLUMNS.map((col) => {
              const mapped = mappings[col.key];
              return (
                <div
                  key={col.key}
                  className={cn(
                    "grid grid-cols-[1fr_auto_1fr] items-center gap-3 p-2.5 rounded border transition-colors",
                    mapped
                      ? "bg-bg-elevated border-border"
                      : "bg-warning/5 border-warning/20"
                  )}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <div
                      className={cn(
                        "w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0",
                        mapped
                          ? "bg-success/15 text-success"
                          : "bg-warning/15 text-warning"
                      )}
                    >
                      {mapped ? (
                        <Check size={10} aria-hidden="true" />
                      ) : (
                        <AlertCircle size={10} aria-hidden="true" />
                      )}
                    </div>
                    <div className="min-w-0">
                      <span className="text-xs font-medium text-text block truncate">
                        {col.label}
                      </span>
                      <span className="text-[10px] text-text-subtle block truncate">
                        {col.description}
                      </span>
                    </div>
                  </div>

                  <span className="text-text-subtle text-xs">&larr;</span>

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
                        "w-full text-xs h-8 bg-bg-elevated border rounded px-2 pr-7 text-text font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent cursor-pointer truncate appearance-none",
                        !mapped ? "border-warning/40" : "border-border"
                      )}
                      aria-label={`Source pour ${col.label}`}
                    >
                      <option value="">-- Non mappe --</option>
                      {sourceColumns.map((sc) => (
                        <option key={sc} value={sc}>
                          {sc}
                        </option>
                      ))}
                    </select>
                    <ChevronDown
                      size={12}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-text-subtle pointer-events-none"
                      aria-hidden="true"
                    />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Sens de comptage */}
          <div className="p-3 rounded border border-border bg-bg-subtle/40 space-y-2">
            <div className="flex items-center gap-2">
              <Settings2 size={12} className="text-accent" aria-hidden="true" />
              <span className="text-xs font-semibold text-text">
                Sens de comptage
              </span>
              <span className="text-[10px] text-text-subtle">
                (valeur par defaut appliquee a toutes les lignes)
              </span>
            </div>
            <div className="flex gap-1.5 flex-wrap">
              {SENS_OPTIONS.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  onClick={() => setSensComptage(opt)}
                  className={cn(
                    "px-2.5 h-7 rounded text-xs font-medium border transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    sensComptage === opt
                      ? "bg-accent-subtle border-accent/40 text-accent"
                      : "bg-bg-elevated border-border text-text-muted hover:border-border-strong hover:text-text"
                  )}
                >
                  {opt}
                </button>
              ))}
            </div>
          </div>

          {/* Lon / Lat (if no geometry) */}
          {!hasGeometry && (
            <div className="p-3 rounded border border-warning/30 bg-warning/5 space-y-2">
              <div className="flex items-center gap-2">
                <MapPin size={12} className="text-warning" aria-hidden="true" />
                <span className="text-xs font-semibold text-warning">
                  Coordonnees geographiques requises
                </span>
              </div>
              <p className="text-[11px] text-text-muted">
                Votre fichier ne contient pas de geometrie. Selectionnez les
                colonnes longitude et latitude (WGS84).
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[10px] text-text-subtle block mb-1">
                    Longitude
                  </label>
                  <select
                    value={longitudeCol ?? ""}
                    onChange={(e) => setLongitudeCol(e.target.value || null)}
                    className="w-full text-xs h-8 bg-bg-elevated border border-border rounded px-2 text-text font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
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
                  <label className="text-[10px] text-text-subtle block mb-1">
                    Latitude
                  </label>
                  <select
                    value={latitudeCol ?? ""}
                    onChange={(e) => setLatitudeCol(e.target.value || null)}
                    className="w-full text-xs h-8 bg-bg-elevated border border-border rounded px-2 text-text font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
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
        </section>
      )}

      {/* Unmapped column actions */}
      {uploadResult && unmappedColumns.length > 0 && (
        <section className="surface-elevated p-5 space-y-3">
          <div className="flex items-center gap-2">
            <Settings2 size={16} className="text-accent" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-text">
              Colonnes supplementaires
            </h3>
            <span className="px-2 h-6 rounded text-[11px] bg-bg-subtle border border-border text-text-muted">
              {unmappedColumns.length} non mappee(s)
            </span>
          </div>
          <p className="text-xs text-text-muted">
            Pour chaque colonne non mappee, choisissez une valeur par defaut
            ou supprimez-la du fichier de sortie.
          </p>

          <div className="space-y-2">
            {unmappedColumns.map((colKey) => {
              const colDef = TARGET_COLUMNS.find((c) => c.key === colKey);
              const action = missingActions[colKey] || "default";
              const defaultVal = missingDefaults[colKey] || "";

              let suggestedDefault = "";
              if (colKey.includes("Type de capteur")) suggestedDefault = "Permanent";
              if (colKey === "Annee") suggestedDefault = "2023";

              return (
                <div
                  key={colKey}
                  className="p-2.5 rounded border border-border bg-bg-elevated space-y-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium text-text truncate">
                      {colKey}
                    </span>
                    <span className="text-[10px] text-text-subtle truncate">
                      {colDef?.description}
                    </span>
                  </div>

                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        setMissingActions((prev) => ({ ...prev, [colKey]: "default" }))
                      }
                      className={cn(
                        "flex-1 px-2.5 h-7 rounded text-xs font-medium border transition-colors",
                        action === "default"
                          ? "bg-accent-subtle border-accent/40 text-accent"
                          : "bg-bg-elevated border-border text-text-muted hover:text-text hover:border-border-strong"
                      )}
                    >
                      Valeur par defaut
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setMissingActions((prev) => ({ ...prev, [colKey]: "remove" }))
                      }
                      className={cn(
                        "flex-1 px-2.5 h-7 rounded text-xs font-medium border transition-colors",
                        action === "remove"
                          ? "bg-danger/10 border-danger/40 text-danger"
                          : "bg-bg-elevated border-border text-text-muted hover:text-text hover:border-border-strong"
                      )}
                    >
                      Supprimer
                    </button>
                  </div>

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
                      className="w-full text-xs h-8 bg-bg-elevated border border-border rounded px-2 text-text placeholder:text-text-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    />
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* 3. Generate */}
      {uploadResult && (
        <section className="surface-elevated p-5 space-y-4">
          <div className="flex items-center gap-2">
            <FileText size={16} className="text-accent" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-text">3. Generation</h3>
          </div>

          <div>
            <label className="text-[11px] text-text-muted block mb-1">
              Nom du fichier de sortie
            </label>
            <div className="flex items-stretch">
              <input
                type="text"
                value={outputFilename}
                onChange={(e) => setOutputFilename(e.target.value)}
                className="flex-1 text-xs h-9 bg-bg-elevated border border-border rounded-l px-3 text-text font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
              <span className="inline-flex items-center text-xs bg-bg-subtle border border-l-0 border-border rounded-r px-3 text-text-muted font-mono">
                .geojson
              </span>
            </div>
          </div>

          {!isComplete && (
            <div className="flex items-start gap-2 p-3 rounded border border-warning/30 bg-warning/5 text-xs text-warning">
              <AlertCircle size={12} className="mt-0.5" aria-hidden="true" />
              <span>
                Configuration incomplete. Completez le mapping ou configurez les
                colonnes manquantes.
              </span>
            </div>
          )}

          <div className="flex justify-center">
            <Button
              variant="primary"
              size="lg"
              onClick={handleGenerate}
              disabled={!isComplete || generating}
              icon={
                generating ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Play size={14} />
                )
              }
            >
              {generating ? "Generation en cours..." : "Generer le fichier"}
            </Button>
          </div>
        </section>
      )}

      {/* Result */}
      {result && (
        <section className="surface-elevated p-5 space-y-4">
          <div className="text-center space-y-1">
            <div className="w-12 h-12 rounded-md bg-success/10 text-success flex items-center justify-center mx-auto">
              <CircleDot size={22} aria-hidden="true" />
            </div>
            <p className="text-sm font-medium text-text">
              Fichier compteurs genere avec succes
            </p>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <StatCard
              label="Boucles generees"
              value={result.geojson_feature_count.toLocaleString("fr-FR")}
              trend="up"
            />
            <StatCard
              label="Lignes source"
              value={result.stats.total_rows.toLocaleString("fr-FR")}
            />
            <StatCard
              label="Colonnes"
              value={result.stats.columns.length}
            />
          </div>

          {result.stats.type_distribution && (
            <div>
              <p className="text-[10px] text-text-subtle uppercase tracking-wide mb-2">
                Repartition par type
              </p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(result.stats.type_distribution).map(([type, count]) => (
                  <div
                    key={type}
                    className="px-2 h-7 rounded bg-bg-elevated border border-border flex items-center gap-1 text-xs"
                  >
                    <span className="text-text font-medium">{type}</span>
                    <span className="text-text-muted font-mono tabular-nums">
                      {count}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.stats.year_distribution && (
            <div>
              <p className="text-[10px] text-text-subtle uppercase tracking-wide mb-2">
                Repartition par annee
              </p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(result.stats.year_distribution).map(([year, count]) => (
                  <div
                    key={year}
                    className="px-2 h-7 rounded bg-bg-elevated border border-border flex items-center gap-1 text-xs"
                  >
                    <span className="text-text font-medium font-mono">{year}</span>
                    <span className="text-text-muted font-mono tabular-nums">
                      {count}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex justify-center pt-1">
            <Button
              variant="secondary"
              size="md"
              icon={<Download size={14} />}
              onClick={handleDownload}
            >
              Telecharger GeoJSON
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}
