"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  Map,
  ArrowLeft,
  Play,
  Download,
  Layers,
  CheckCircle2,
  XCircle,
  SlidersHorizontal,
  Filter,
  Truck,
  Car,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { AuroraBg } from "@/components/backgrounds/aurora-bg";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";
import { StatCard } from "@/components/ui/stat-card";
import { DropZone } from "@/components/upload/drop-zone";
import { useAppStore } from "@/lib/store";
import { fetchJSON, uploadFile } from "@/lib/api";
import { apiUrl } from "@/lib/api-url";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface UploadResponse {
  session_id: string;
  filename: string;
  rows: number;
  columns: string[];
  preview: Record<string, unknown>[];
}

interface CarteModelUploadResponse {
  model_dir: string;
  valid: boolean;
  missing_files: string[];
  training_config: Record<string, unknown> | null;
}

interface CarteStats {
  total_segments: number;
  filtered_segments: number;
  mean_tvr: number | null;
  mean_dpl: number | null;
}

interface CarteGenerateResponse {
  session_id: string;
  stats: CarteStats;
  geojson_feature_count: number;
}

// ---------------------------------------------------------------------------
// Column mapping definitions
// ---------------------------------------------------------------------------

interface ColumnDef {
  key: string;
  label: string;
  description: string;
  required: boolean;
}

const REQUIRED_COLUMNS: ColumnDef[] = [
  { key: "TMJATV", label: "TMJA TV", description: "TMJA Tous Vehicules (pour modele TV)", required: true },
  { key: "TMJAPL", label: "TMJA PL", description: "TMJA Poids Lourds", required: true },
  { key: "car_average_distance_km", label: "Distance voitures", description: "Distance moyenne voitures (km)", required: true },
  { key: "car_average_speed_kmh", label: "Vitesse voitures", description: "Vitesse moyenne voitures (km/h)", required: true },
  { key: "truck_min_average_distance_km", label: "Distance camions", description: "Distance min moyenne camions (km)", required: true },
  { key: "truck_average_speed_kmh", label: "Vitesse camions", description: "Vitesse moyenne camions (km/h)", required: true },
  { key: "linkFC", label: "Functional Class", description: "Classification routiere (FC)", required: true },
  { key: "TMJAVL", label: "TMJA VL", description: "TMJA Vehicules Legers", required: true },
  { key: "agregId", label: "Identifiant troncon", description: "LINK_ID ou identifiant unique", required: false },
  { key: "DIR_TRAVEL", label: "Direction", description: "Direction de circulation (F/T/B)", required: false },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CartePage() {
  const router = useRouter();
  const { reset } = useAppStore();

  // Section 1 — Model uploads
  const [tvZipFile, setTvZipFile] = useState<File | null>(null);
  const [plZipFile, setPlZipFile] = useState<File | null>(null);
  const [tvUploading, setTvUploading] = useState(false);
  const [plUploading, setPlUploading] = useState(false);
  const [modelTvDir, setModelTvDir] = useState("");
  const [modelPlDir, setModelPlDir] = useState("");
  const [tvValid, setTvValid] = useState<boolean | null>(null);
  const [plValid, setPlValid] = useState<boolean | null>(null);
  const [tvMissing, setTvMissing] = useState<string[]>([]);
  const [plMissing, setPlMissing] = useState<string[]>([]);

  // Section 2 — FCD data
  const [fcdFile, setFcdFile] = useState<File | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sourceColumns, setSourceColumns] = useState<string[]>([]);
  const [rowCount, setRowCount] = useState<number>(0);
  const [columnMapping, setColumnMapping] = useState<Record<string, string | null>>({});
  const [uploading, setUploading] = useState(false);

  // Section 3 — Filters
  const [filterTvrEnabled, setFilterTvrEnabled] = useState(true);
  const [filterTvrValue, setFilterTvrValue] = useState(100);
  const [filterFcEnabled, setFilterFcEnabled] = useState(true);
  const [err01000, setErr01000] = useState(25);
  const [err10002000, setErr10002000] = useState(18);
  const [err20004000, setErr20004000] = useState(18);
  const [err4000plus, setErr4000plus] = useState(14);

  // Section 4 — Generation
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressText, setProgressText] = useState("");
  const [done, setDone] = useState(false);
  const [stats, setStats] = useState<CarteStats | null>(null);

  // ---- Model ZIP upload ----
  const handleModelUpload = useCallback(
    async (file: File, type: "tv" | "pl") => {
      // We need a session_id for the upload endpoint; create a temporary one if needed
      let sid = sessionId;
      if (!sid) {
        // Generate a simple session id for model storage
        sid = `carte_${Date.now().toString(36)}`;
        setSessionId(sid);
      }

      const setUpl = type === "tv" ? setTvUploading : setPlUploading;
      setUpl(true);

      try {
        const form = new FormData();
        form.append("file", file);
        form.append("session_id", sid);
        form.append("model_type", type);

        const res = await fetch(apiUrl("/api/carte/upload-model"), {
          method: "POST",
          body: form,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail ?? "Upload echoue");
        }
        const data: CarteModelUploadResponse = await res.json();

        if (type === "tv") {
          setModelTvDir(data.model_dir);
          setTvValid(data.valid);
          setTvMissing(data.missing_files);
        } else {
          setModelPlDir(data.model_dir);
          setPlValid(data.valid);
          setPlMissing(data.missing_files);
        }

        if (data.valid) {
          toast.success(`Modele ${type.toUpperCase()} valide et pret`);
        } else {
          toast.warning(`Modele ${type.toUpperCase()} incomplet : ${data.missing_files.join(", ")}`);
        }
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Erreur inconnue";
        toast.error(`Erreur upload modele ${type.toUpperCase()} : ${message}`);
        if (type === "tv") { setTvValid(false); setTvMissing(["(erreur upload)"]); }
        else { setPlValid(false); setPlMissing(["(erreur upload)"]); }
      } finally {
        setUpl(false);
      }
    },
    [sessionId]
  );

  // ---- FCD file upload ----
  const handleFcdUpload = useCallback(async (file: File) => {
    setFcdFile(file);
    setUploading(true);
    try {
      const res = await uploadFile("/api/upload", file, { mode: "TV" }) as UploadResponse;
      setSessionId(res.session_id);
      setSourceColumns(res.columns.filter((c) => c !== "geometry" && c !== "__geometry_json"));
      setRowCount(res.rows);

      // Auto-map columns where names match
      const autoMapping: Record<string, string | null> = {};
      for (const col of REQUIRED_COLUMNS) {
        const match = res.columns.find((c) => c === col.key);
        autoMapping[col.key] = match ?? null;
      }
      setColumnMapping(autoMapping);
      toast.success(`${res.rows} troncons charges depuis ${res.filename}`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      toast.error(`Erreur upload : ${message}`);
      setFcdFile(null);
    } finally {
      setUploading(false);
    }
  }, []);

  // ---- Mapping update ----
  const updateMapping = useCallback((key: string, value: string | null) => {
    setColumnMapping((prev) => ({ ...prev, [key]: value }));
  }, []);

  // ---- Can generate? ----
  const requiredMapped = REQUIRED_COLUMNS.filter((c) => c.required).every(
    (c) => columnMapping[c.key] && columnMapping[c.key] !== ""
  );
  const canGenerate = tvValid === true && plValid === true && sessionId !== null && requiredMapped;

  // ---- Generation ----
  const handleGenerate = useCallback(async () => {
    if (!canGenerate || !sessionId) return;
    setGenerating(true);
    setDone(false);
    setStats(null);
    setProgress(10);
    setProgressText("Chargement des modeles...");

    try {
      setProgress(30);
      setProgressText("Application des modeles TV et PL...");

      const res = await fetchJSON<CarteGenerateResponse>("/api/carte/generate", {
        method: "POST",
        body: JSON.stringify({
          session_id: sessionId,
          model_tv_dir: modelTvDir,
          model_pl_dir: modelPlDir,
          column_mapping: columnMapping,
          filter_tvr_enabled: filterTvrEnabled,
          filter_tvr_value: filterTvrValue,
          filter_fc_enabled: filterFcEnabled,
          error_thresholds: {
            err_0_1000: err01000 / 100,
            err_1000_2000: err10002000 / 100,
            err_2000_4000: err20004000 / 100,
            err_4000_plus: err4000plus / 100,
          },
        }),
      });

      setProgress(100);
      setProgressText("Generation terminee !");
      setStats(res.stats);
      setDone(true);
      const _tvrMoy = res.stats.mean_tvr != null ? `, TVr moyen: ${Math.round(res.stats.mean_tvr).toLocaleString("fr-FR")} veh/j` : "";
      toast.success(`Carte generee — ${res.geojson_feature_count.toLocaleString("fr-FR")} troncons${_tvrMoy}`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      toast.error(`Erreur generation : ${message}`);
      setProgress(0);
      setProgressText("");
    } finally {
      setGenerating(false);
    }
  }, [
    canGenerate, sessionId, modelTvDir, modelPlDir, columnMapping,
    filterTvrEnabled, filterTvrValue, filterFcEnabled,
    err01000, err10002000, err20004000, err4000plus,
  ]);

  // ---- Download ----
  const handleDownload = useCallback(() => {
    if (!sessionId) return;
    window.open(apiUrl(`/api/carte/download/${sessionId}`), "_blank");
  }, [sessionId]);

  // ---- Validity indicator ----
  function ValidityBadge({ valid, missing }: { valid: boolean | null; missing: string[] }) {
    if (valid === null) return null;
    return valid ? (
      <div className="flex items-center gap-1.5 text-emerald-400 text-xs mt-1.5">
        <CheckCircle2 size={14} />
        <span>Structure valide</span>
      </div>
    ) : (
      <div className="flex items-center gap-1.5 text-red-400 text-xs mt-1.5">
        <XCircle size={14} />
        <span>Manquant : {missing.join(", ")}</span>
      </div>
    );
  }

  // =========================================================================
  // RENDER
  // =========================================================================

  return (
    <div className="relative min-h-screen">
      <AuroraBg />
      <div className="relative z-10 max-w-5xl mx-auto px-4 py-8 space-y-8">
        {/* Header */}
        <div className="flex items-center gap-3">
          <NeonButton
            variant="ghost"
            onClick={() => { reset(); router.push("/"); }}
            icon={<ArrowLeft size={14} />}
            className="text-xs"
          >
            Accueil
          </NeonButton>
          <div className="px-3 py-1 rounded-lg bg-cyan/10 text-cyan text-xs font-bold uppercase tracking-wide">
            Carte de Debits
          </div>
        </div>

        <div className="space-y-2">
          <GradientText as="h2" className="text-2xl">
            Generation de la Carte des Debits
          </GradientText>
          <p className="text-sm text-slate-300">
            Appliquez les modeles TV et PL sur vos donnees FCD pour estimer les debits
            de trafic sur chaque troncon routier.
          </p>
        </div>

        {/* ============================================================= */}
        {/* SECTION 1 — Selection des modeles (upload ZIP) */}
        {/* ============================================================= */}
        <GlowCard glowColor="accent">
          <div className="flex items-center gap-2 mb-5">
            <div className="w-7 h-7 rounded-lg bg-accent/20 flex items-center justify-center text-accent text-xs font-bold">1</div>
            <h3 className="text-sm font-semibold text-white">Selection des modeles</h3>
          </div>
          <p className="text-xs text-slate-400 mb-5">
            Uploadez un fichier .zip pour chaque modele. Le ZIP doit contenir
            NNarchitecture.json, NNweights.weights.h5 (ou NNweights.h5) et NNnormCoefficients.json.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* TV */}
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Car size={16} className="text-accent" />
                <span className="text-xs font-medium text-slate-200">Modele TV (Trafic Vehicules)</span>
              </div>
              <DropZone
                file={tvZipFile}
                onFile={(f) => { setTvZipFile(f); handleModelUpload(f, "tv"); }}
                onClear={() => { setTvZipFile(null); setTvValid(null); setTvMissing([]); setModelTvDir(""); }}
                accept={{ "application/zip": [".zip"], "application/x-zip-compressed": [".zip"] }}
                label="Deposez le ZIP du modele TV"
                description=".zip contenant le dossier du modele"
              />
              {tvUploading && (
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <Loader2 size={14} className="animate-spin" />
                  <span>Extraction et validation...</span>
                </div>
              )}
              <ValidityBadge valid={tvValid} missing={tvMissing} />
            </div>

            {/* PL */}
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Truck size={16} className="text-violet" />
                <span className="text-xs font-medium text-slate-200">Modele PL (Poids Lourds)</span>
              </div>
              <DropZone
                file={plZipFile}
                onFile={(f) => { setPlZipFile(f); handleModelUpload(f, "pl"); }}
                onClear={() => { setPlZipFile(null); setPlValid(null); setPlMissing([]); setModelPlDir(""); }}
                accept={{ "application/zip": [".zip"], "application/x-zip-compressed": [".zip"] }}
                label="Deposez le ZIP du modele PL"
                description=".zip contenant le dossier du modele"
              />
              {plUploading && (
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <Loader2 size={14} className="animate-spin" />
                  <span>Extraction et validation...</span>
                </div>
              )}
              <ValidityBadge valid={plValid} missing={plMissing} />
            </div>
          </div>
        </GlowCard>

        {/* ============================================================= */}
        {/* SECTION 2 — Donnees FCD */}
        {/* ============================================================= */}
        <GlowCard glowColor="cyan">
          <div className="flex items-center gap-2 mb-5">
            <div className="w-7 h-7 rounded-lg bg-cyan/20 flex items-center justify-center text-cyan text-xs font-bold">2</div>
            <h3 className="text-sm font-semibold text-white">Donnees FCD</h3>
          </div>

          <DropZone
            file={fcdFile}
            onFile={handleFcdUpload}
            onClear={() => {
              setFcdFile(null);
              setSessionId(null);
              setSourceColumns([]);
              setRowCount(0);
              setColumnMapping({});
              setDone(false);
              setStats(null);
            }}
            accept={{
              "application/json": [".geojson", ".json"],
              "application/geo+json": [".geojson"],
            }}
            label="Deposez votre fichier GeoJSON FCD"
            description=".geojson"
          />

          {uploading && (
            <div className="flex items-center gap-2 mt-3 text-xs text-slate-400">
              <Loader2 size={14} className="animate-spin" />
              <span>Chargement et analyse du fichier...</span>
            </div>
          )}

          {sessionId && rowCount > 0 && (
            <div className="mt-3 text-xs text-emerald-400">
              {rowCount} troncons routiers charges
            </div>
          )}

          {/* Column Mapping */}
          <AnimatePresence>
            {sourceColumns.length > 0 && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="mt-6 space-y-4"
              >
                <div className="flex items-center gap-2">
                  <Layers size={16} className="text-cyan" />
                  <span className="text-xs font-semibold text-white">
                    Mapping des colonnes
                  </span>
                  <span className="text-[10px] text-slate-400 ml-2">
                    ({REQUIRED_COLUMNS.filter((c) => c.required && columnMapping[c.key]).length}/{REQUIRED_COLUMNS.filter((c) => c.required).length} obligatoires mappees)
                  </span>
                </div>

                {/* Progress bar */}
                <div className="h-1 rounded-full bg-surface-light overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{
                      width: `${(REQUIRED_COLUMNS.filter((c) => c.required && columnMapping[c.key]).length / REQUIRED_COLUMNS.filter((c) => c.required).length) * 100}%`,
                    }}
                    className="h-full rounded-full bg-gradient-to-r from-accent to-cyan"
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {REQUIRED_COLUMNS.map((col) => (
                    <div
                      key={col.key}
                      className={`flex items-center gap-3 p-2.5 rounded-lg transition-colors ${
                        columnMapping[col.key]
                          ? "bg-accent/5 border border-accent/10"
                          : col.required
                            ? "bg-red-500/5 border border-red-500/20"
                            : "bg-surface-light/50 border border-transparent"
                      }`}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-mono text-slate-200 truncate">
                            {col.key}
                          </span>
                          {!col.required && (
                            <span className="text-[9px] text-slate-400 bg-surface-light px-1.5 py-0.5 rounded">
                              optionnel
                            </span>
                          )}
                        </div>
                        <p className="text-[10px] text-slate-400 mt-0.5 truncate">
                          {col.description}
                        </p>
                      </div>
                      <span className="text-slate-500 text-xs flex-shrink-0">&larr;</span>
                      <select
                        value={columnMapping[col.key] ?? ""}
                        onChange={(e) =>
                          updateMapping(col.key, e.target.value || null)
                        }
                        className={`text-xs bg-surface border rounded-lg px-2 py-1.5 text-slate-200 outline-none focus:border-accent/40 cursor-pointer w-44 truncate ${
                          !columnMapping[col.key] && col.required
                            ? "border-red-500/40"
                            : "border-border"
                        }`}
                      >
                        <option value="">
                          {col.required ? "-- Selectionner --" : "-- Ignorer --"}
                        </option>
                        {sourceColumns.map((sc) => (
                          <option key={sc} value={sc}>
                            {sc}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>

                {requiredMapped && (
                  <div className="flex items-center gap-1.5 text-emerald-400 text-xs">
                    <CheckCircle2 size={14} />
                    <span>Toutes les colonnes obligatoires sont mappees</span>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </GlowCard>

        {/* ============================================================= */}
        {/* SECTION 3 — Filtres et parametres */}
        {/* ============================================================= */}
        <GlowCard glowColor="violet">
          <div className="flex items-center gap-2 mb-5">
            <div className="w-7 h-7 rounded-lg bg-violet/20 flex items-center justify-center text-violet text-xs font-bold">3</div>
            <h3 className="text-sm font-semibold text-white">Filtres et parametres</h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {/* Left — Filters */}
            <div className="space-y-5">
              <div className="flex items-center gap-2 mb-3">
                <Filter size={14} className="text-violet" />
                <span className="text-xs font-medium text-slate-200">Filtres sur les donnees</span>
              </div>

              {/* Filter TVr */}
              <label className="flex items-start gap-3 cursor-pointer group">
                <input
                  type="checkbox"
                  checked={filterTvrEnabled}
                  onChange={(e) => setFilterTvrEnabled(e.target.checked)}
                  className="mt-0.5 w-4 h-4 rounded border-border bg-surface accent-accent cursor-pointer"
                />
                <div className="flex-1">
                  <span className="text-xs font-medium text-slate-200 group-hover:text-accent transition-colors">
                    Filtrer les troncons par seuil TVr
                  </span>
                  <p className="text-[10px] text-slate-400 mt-0.5">
                    Exclure les troncons avec TVr en-dessous du seuil
                  </p>
                  {filterTvrEnabled && (
                    <div className="mt-2 flex items-center gap-2">
                      <span className="text-[10px] text-slate-400">Seuil :</span>
                      <input
                        type="number"
                        value={filterTvrValue}
                        onChange={(e) => setFilterTvrValue(Number(e.target.value))}
                        min={0}
                        max={1000}
                        step={10}
                        className="w-20 h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none focus:border-accent/50"
                      />
                      <span className="text-[10px] text-slate-400">veh/j</span>
                    </div>
                  )}
                </div>
              </label>

              {/* Filter FC */}
              <label className="flex items-start gap-3 cursor-pointer group">
                <input
                  type="checkbox"
                  checked={filterFcEnabled}
                  onChange={(e) => setFilterFcEnabled(e.target.checked)}
                  className="mt-0.5 w-4 h-4 rounded border-border bg-surface accent-accent cursor-pointer"
                />
                <div>
                  <span className="text-xs font-medium text-slate-200 group-hover:text-accent transition-colors">
                    Exclure les troncons FC = 1
                  </span>
                  <p className="text-[10px] text-slate-400 mt-0.5">
                    Les autoroutes principales (Functional Class 1) seront exclues
                  </p>
                </div>
              </label>
            </div>

            {/* Right — Error thresholds */}
            <div className="space-y-4">
              <div className="flex items-center gap-2 mb-3">
                <SlidersHorizontal size={14} className="text-violet" />
                <span className="text-xs font-medium text-slate-200">Intervalles de confiance</span>
              </div>
              <p className="text-[10px] text-slate-400 -mt-2 mb-3">
                Pourcentage d&apos;erreur selon les tranches de debit TVr
              </p>

              {[
                { label: "Debits < 1 000 veh/j", value: err01000, setter: setErr01000 },
                { label: "Debits 1 000 - 2 000 veh/j", value: err10002000, setter: setErr10002000 },
                { label: "Debits 2 000 - 4 000 veh/j", value: err20004000, setter: setErr20004000 },
                { label: "Debits > 4 000 veh/j", value: err4000plus, setter: setErr4000plus },
              ].map((item) => (
                <div key={item.label} className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-slate-200">{item.label}</span>
                    <span className="text-xs font-mono text-accent font-semibold">{item.value}%</span>
                  </div>
                  <input
                    type="range"
                    min={5}
                    max={50}
                    step={1}
                    value={item.value}
                    onChange={(e) => item.setter(Number(e.target.value))}
                    className="w-full h-1.5 rounded-full appearance-none bg-surface-light cursor-pointer accent-accent [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-accent/50 [&::-webkit-slider-thumb]:shadow-[0_0_6px_rgba(99,102,241,0.4)]"
                  />
                </div>
              ))}
            </div>
          </div>
        </GlowCard>

        {/* ============================================================= */}
        {/* SECTION 4 — Generation */}
        {/* ============================================================= */}
        <GlowCard>
          <div className="flex items-center gap-2 mb-5">
            <div className="w-7 h-7 rounded-lg bg-accent/20 flex items-center justify-center text-accent text-xs font-bold">4</div>
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
              onClick={handleGenerate}
              disabled={!canGenerate || generating}
              icon={generating ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
              className={generating ? "animate-pulse" : ""}
            >
              {generating ? "Generation en cours..." : "Generer la carte des debits"}
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

        {/* ============================================================= */}
        {/* RESULTS */}
        {/* ============================================================= */}
        <AnimatePresence>
          {done && stats && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <GlowCard glowColor="cyan">
                <div className="text-center py-4 space-y-5">
                  <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center mx-auto">
                    <Map size={28} />
                  </div>
                  <p className="text-sm font-medium text-white">
                    Carte des debits generee avec succes
                  </p>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 max-w-2xl mx-auto">
                    <StatCard
                      label="Troncons totaux"
                      value={stats.total_segments.toLocaleString("fr-FR")}
                      icon={<Layers size={16} />}
                    />
                    <StatCard
                      label="Troncons filtres"
                      value={stats.filtered_segments.toLocaleString("fr-FR")}
                      icon={<Filter size={16} />}
                    />
                    <StatCard
                      label="TVr moyen"
                      value={stats.mean_tvr != null ? `${Math.round(stats.mean_tvr).toLocaleString("fr-FR")} veh/j` : "-"}
                      icon={<Car size={16} />}
                    />
                    <StatCard
                      label="DPL moyen"
                      value={stats.mean_dpl != null ? `${Math.round(stats.mean_dpl).toLocaleString("fr-FR")} PL/j` : "-"}
                      icon={<Truck size={16} />}
                    />
                  </div>

                  <NeonButton
                    variant="secondary"
                    icon={<Download size={16} />}
                    onClick={handleDownload}
                  >
                    Telecharger le GeoJSON
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
