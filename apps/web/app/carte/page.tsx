"use client";

import { useState, useCallback, useRef, useMemo, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Map as MapIcon,
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
  FolderOpen,
  X,
  ChevronDown,
  ChevronUp,
  Table as TableIcon,
} from "lucide-react";
import { toast } from "sonner";
import type { FeatureCollection, LineString, GeoJsonProperties } from "geojson";

import { GradientText } from "@/components/ui/gradient-text";
import { NeonButton } from "@/components/ui/neon-button";
import { DropZone } from "@/components/upload/drop-zone";
import { useAppStore } from "@/lib/store";
import { fetchJSON, uploadFile } from "@/lib/api";
import { apiUrl } from "@/lib/api-url";

import { MapView, type MapViewFilters } from "@/components/map/MapView";
import {
  ControlPanel,
  type MapControlsState,
} from "@/components/map/ControlPanel";

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

import { samMood } from "@/lib/sam/store";

export default function CartePage() {
  const router = useRouter();
  const { reset } = useAppStore();

  // Sam ambient mood for this page
  useEffect(() => {
    samMood.set("based", "Charge tes modeles et tes donnees FCD.");
    return () => samMood.reset();
  }, []);

  // ----- Pipeline state (server-side) -----
  const [tvFolderName, setTvFolderName] = useState<string | null>(null);
  const [plFolderName, setPlFolderName] = useState<string | null>(null);
  const [tvUploading, setTvUploading] = useState(false);
  const [plUploading, setPlUploading] = useState(false);
  const [modelTvDir, setModelTvDir] = useState("");
  const [modelPlDir, setModelPlDir] = useState("");
  const [tvValid, setTvValid] = useState<boolean | null>(null);
  const [plValid, setPlValid] = useState<boolean | null>(null);
  const [tvMissing, setTvMissing] = useState<string[]>([]);
  const [plMissing, setPlMissing] = useState<string[]>([]);
  const tvFolderInputRef = useRef<HTMLInputElement>(null);
  const plFolderInputRef = useRef<HTMLInputElement>(null);

  const [fcdFile, setFcdFile] = useState<File | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sourceColumns, setSourceColumns] = useState<string[]>([]);
  const [rowCount, setRowCount] = useState<number>(0);
  const [columnMapping, setColumnMapping] = useState<Record<string, string | null>>({});
  const [uploading, setUploading] = useState(false);

  // Confidence intervals (server-side params)
  const [filterTvrEnabled, setFilterTvrEnabled] = useState(true);
  const [filterTvrValue, setFilterTvrValue] = useState(100);
  const [filterFcEnabled, setFilterFcEnabled] = useState(true);
  const [err01000, setErr01000] = useState(25);
  const [err10002000, setErr10002000] = useState(18);
  const [err20004000, setErr20004000] = useState(18);
  const [err4000plus, setErr4000plus] = useState(14);

  // Generation result
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressText, setProgressText] = useState("");
  const [done, setDone] = useState(false);
  const [stats, setStats] = useState<CarteStats | null>(null);
  const [geojson, setGeojson] = useState<FeatureCollection<LineString, GeoJsonProperties> | null>(null);

  // Map-local viewer filters
  const [mapControls, setMapControls] = useState<MapControlsState>({
    minTvrFilter: 0,
    excludeFc1: false,
  });

  // UI: collapsible config panel + alt table
  const [configOpen, setConfigOpen] = useState(true);
  const [tableOpen, setTableOpen] = useState(false);

  const mapFilters: MapViewFilters = useMemo(
    () => ({
      minTvr: mapControls.minTvrFilter,
      excludeFc1: mapControls.excludeFc1,
    }),
    [mapControls.minTvrFilter, mapControls.excludeFc1],
  );

  // Detect theme from html dataset / class
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  useEffect(() => {
    if (typeof document === "undefined") return;
    const apply = () => {
      const html = document.documentElement;
      const isDark =
        html.classList.contains("dark") || html.dataset.theme === "dark";
      setTheme(isDark ? "dark" : "light");
    };
    apply();
    const obs = new MutationObserver(apply);
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class", "data-theme"],
    });
    return () => obs.disconnect();
  }, []);

  // ----- Model folder upload -----
  const handleModelFolderSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>, type: "tv" | "pl") => {
      const fileList = e.target.files;
      if (!fileList || fileList.length === 0) return;

      let sid = sessionId;
      if (!sid) {
        sid = `carte_${Date.now().toString(36)}`;
        setSessionId(sid);
      }

      const firstPath =
        (fileList[0] as File & { webkitRelativePath?: string }).webkitRelativePath ??
        fileList[0].name;
      const rootFolder = firstPath.split("/")[0] || "dossier";

      if (type === "tv") {
        setTvFolderName(rootFolder);
        setTvUploading(true);
      } else {
        setPlFolderName(rootFolder);
        setPlUploading(true);
      }

      try {
        const form = new FormData();
        form.append("session_id", sid);
        form.append("model_type", type);

        for (let i = 0; i < fileList.length; i++) {
          const file = fileList[i] as File & { webkitRelativePath?: string };
          const relativePath = file.webkitRelativePath ?? file.name;
          const parts = relativePath.split("/");
          const strippedPath = parts.length > 1 ? parts.slice(1).join("/") : parts[0];
          form.append("files", file, strippedPath);
        }

        const res = await fetch(apiUrl("/api/carte/upload-model-folder"), {
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

        if (data.valid) toast.success(`Modele ${type.toUpperCase()} valide et pret`);
        else
          toast.warning(
            `Modele ${type.toUpperCase()} incomplet : ${data.missing_files.join(", ")}`,
          );
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Erreur inconnue";
        toast.error(`Erreur upload modele ${type.toUpperCase()} : ${message}`);
        if (type === "tv") {
          setTvValid(false);
          setTvMissing(["(erreur upload)"]);
        } else {
          setPlValid(false);
          setPlMissing(["(erreur upload)"]);
        }
      } finally {
        if (type === "tv") setTvUploading(false);
        else setPlUploading(false);
      }
    },
    [sessionId],
  );

  const clearModelFolder = useCallback((type: "tv" | "pl") => {
    if (type === "tv") {
      setTvFolderName(null);
      setTvValid(null);
      setTvMissing([]);
      setModelTvDir("");
      if (tvFolderInputRef.current) tvFolderInputRef.current.value = "";
    } else {
      setPlFolderName(null);
      setPlValid(null);
      setPlMissing([]);
      setModelPlDir("");
      if (plFolderInputRef.current) plFolderInputRef.current.value = "";
    }
  }, []);

  // ----- FCD file upload -----
  const handleFcdUpload = useCallback(async (file: File) => {
    setFcdFile(file);
    setUploading(true);
    try {
      const res = (await uploadFile("/api/upload", file, { mode: "TV" })) as UploadResponse;
      setSessionId(res.session_id);
      setSourceColumns(
        res.columns.filter((c) => c !== "geometry" && c !== "__geometry_json"),
      );
      setRowCount(res.rows);

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

  const updateMapping = useCallback((key: string, value: string | null) => {
    setColumnMapping((prev) => ({ ...prev, [key]: value }));
  }, []);

  const requiredMapped = REQUIRED_COLUMNS.filter((c) => c.required).every(
    (c) => columnMapping[c.key] && columnMapping[c.key] !== "",
  );
  const canGenerate =
    tvValid === true && plValid === true && sessionId !== null && requiredMapped;

  // ----- Generation -----
  const handleGenerate = useCallback(async () => {
    if (!canGenerate || !sessionId) return;
    setGenerating(true);
    setDone(false);
    setStats(null);
    setGeojson(null);
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

      setProgress(70);
      setProgressText("Telechargement du GeoJSON...");

      // Fetch the actual GeoJSON to render on the map
      const geoRes = await fetch(apiUrl(`/api/carte/download/${sessionId}`));
      if (!geoRes.ok) throw new Error("Impossible de recuperer le GeoJSON");
      const fc = (await geoRes.json()) as FeatureCollection<LineString, GeoJsonProperties>;

      setProgress(100);
      setProgressText("Generation terminee !");
      setStats(res.stats);
      setGeojson(fc);
      setDone(true);
      // Collapse the config panel once we have a result to maximize map area
      setConfigOpen(false);

      const tvrMoy =
        res.stats.mean_tvr != null
          ? `, TVr moyen: ${Math.round(res.stats.mean_tvr).toLocaleString("fr-FR")} veh/j`
          : "";
      toast.success(
        `Carte generee — ${res.geojson_feature_count.toLocaleString("fr-FR")} troncons${tvrMoy}`,
      );
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      toast.error(`Erreur generation : ${message}`);
      setProgress(0);
      setProgressText("");
    } finally {
      setGenerating(false);
    }
  }, [
    canGenerate,
    sessionId,
    modelTvDir,
    modelPlDir,
    columnMapping,
    filterTvrEnabled,
    filterTvrValue,
    filterFcEnabled,
    err01000,
    err10002000,
    err20004000,
    err4000plus,
  ]);

  const handleDownload = useCallback(() => {
    if (!sessionId) return;
    window.open(apiUrl(`/api/carte/download/${sessionId}`), "_blank");
  }, [sessionId]);

  // ----- Visible feature count (rough estimate, applies map filters) -----
  const visibleFeatureCount = useMemo(() => {
    if (!geojson) return null;
    return geojson.features.filter((f) => {
      const props = f.properties ?? {};
      const tvr = Number((props as { TVr?: number }).TVr ?? 0);
      const fc = Number((props as { FC?: number }).FC ?? 0);
      if (mapControls.minTvrFilter > 0 && tvr < mapControls.minTvrFilter) return false;
      if (mapControls.excludeFc1 && fc === 1) return false;
      return true;
    }).length;
  }, [geojson, mapControls.minTvrFilter, mapControls.excludeFc1]);

  // -----------------------------------------------------------------------
  // RENDER
  // -----------------------------------------------------------------------

  return (
    <div className="relative h-[calc(100vh-4rem)] flex flex-col bg-[var(--bg,#080812)]">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06] bg-[rgba(15,20,40,0.5)] backdrop-blur shrink-0">
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
            Carte de Debits
          </div>
          <GradientText as="h2" className="text-base">
            Generation & visualisation
          </GradientText>
        </div>

        <div className="flex items-center gap-2">
          {done && (
            <NeonButton
              variant="secondary"
              icon={<Download size={14} />}
              onClick={handleDownload}
              className="text-xs"
            >
              GeoJSON
            </NeonButton>
          )}
        </div>
      </div>

      {/* Main split layout */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* ============ LEFT — Control sidebar ============ */}
        <aside
          className={`shrink-0 border-r border-white/[0.06] bg-[rgba(15,20,40,0.6)] backdrop-blur overflow-y-auto transition-[width] duration-300 ${
            configOpen ? "w-[400px]" : "w-[280px]"
          }`}
          aria-label="Panneau de configuration"
        >
          <div className="p-4 space-y-5">
            {/* === Map viewer controls (always visible) === */}
            <ControlPanel
              state={mapControls}
              onChange={setMapControls}
              hasData={geojson !== null}
              featureCount={visibleFeatureCount}
              meanTvr={stats?.mean_tvr}
              meanDpl={stats?.mean_dpl}
            />

            {/* === Pipeline config (collapsible) === */}
            <div className="rounded-xl border border-white/[0.08] bg-[rgba(8,8,18,0.4)]">
              <button
                type="button"
                onClick={() => setConfigOpen((v) => !v)}
                className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-white/[0.03] rounded-t-xl"
                aria-expanded={configOpen}
              >
                <span className="text-xs font-semibold text-slate-100 uppercase tracking-wide">
                  Configuration & generation
                </span>
                {configOpen ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
              </button>

              {configOpen && (
                <div className="p-3 space-y-4 border-t border-white/[0.06]">
                  {/* --- Hidden folder inputs --- */}
                  <input
                    ref={tvFolderInputRef}
                    type="file"
                    webkitdirectory=""
                    directory=""
                    multiple
                    className="hidden"
                    onChange={(e) => handleModelFolderSelect(e, "tv")}
                  />
                  <input
                    ref={plFolderInputRef}
                    type="file"
                    webkitdirectory=""
                    directory=""
                    multiple
                    className="hidden"
                    onChange={(e) => handleModelFolderSelect(e, "pl")}
                  />

                  {/* --- Section 1: Models --- */}
                  <SectionHeader index={1} accent="indigo" title="Modeles TV & PL" />
                  <div className="grid grid-cols-1 gap-2">
                    <CompactFolderButton
                      icon={<Car size={14} className="text-indigo-400" />}
                      label="Modele TV"
                      folderName={tvFolderName}
                      uploading={tvUploading}
                      onClick={() => tvFolderInputRef.current?.click()}
                      onClear={() => clearModelFolder("tv")}
                    />
                    <ValidityBadge valid={tvValid} missing={tvMissing} />

                    <CompactFolderButton
                      icon={<Truck size={14} className="text-violet-400" />}
                      label="Modele PL"
                      folderName={plFolderName}
                      uploading={plUploading}
                      onClick={() => plFolderInputRef.current?.click()}
                      onClear={() => clearModelFolder("pl")}
                    />
                    <ValidityBadge valid={plValid} missing={plMissing} />
                  </div>

                  {/* --- Section 2: FCD --- */}
                  <SectionHeader index={2} accent="cyan" title="Donnees FCD" />
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
                      setGeojson(null);
                    }}
                    accept={{
                      "application/json": [".geojson", ".json"],
                      "application/geo+json": [".geojson"],
                    }}
                    label="Deposez le GeoJSON FCD"
                    description=".geojson"
                  />
                  {uploading && (
                    <div className="flex items-center gap-2 text-[11px] text-slate-400">
                      <Loader2 size={12} className="animate-spin" />
                      <span>Analyse...</span>
                    </div>
                  )}
                  {sessionId && rowCount > 0 && (
                    <p className="text-[11px] text-emerald-400">
                      {rowCount.toLocaleString("fr-FR")} tronçons chargés
                    </p>
                  )}

                  {/* --- Column mapping --- */}
                  {sourceColumns.length > 0 && (
                    <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Layers size={12} className="text-cyan-400" />
                          <span className="text-[11px] font-semibold text-slate-100">
                            Mapping
                          </span>
                          <span className="text-[10px] text-slate-500 ml-auto">
                            {REQUIRED_COLUMNS.filter(
                              (c) => c.required && columnMapping[c.key],
                            ).length}
                            /
                            {REQUIRED_COLUMNS.filter((c) => c.required).length}
                          </span>
                        </div>
                        <div className="space-y-1.5">
                          {REQUIRED_COLUMNS.map((col) => (
                            <div
                              key={col.key}
                              className="flex items-center gap-2 p-1.5 rounded-md bg-[rgba(15,20,40,0.5)] border border-white/[0.05]"
                            >
                              <span className="text-[10px] font-mono text-slate-300 flex-1 truncate">
                                {col.key}
                                {!col.required && (
                                  <span className="text-[9px] text-slate-500 ml-1">(opt)</span>
                                )}
                              </span>
                              <select
                                value={columnMapping[col.key] ?? ""}
                                onChange={(e) => updateMapping(col.key, e.target.value || null)}
                                className={`text-[10px] bg-[rgba(8,8,18,0.6)] border rounded px-1.5 py-0.5 text-slate-200 outline-none cursor-pointer w-32 truncate ${
                                  !columnMapping[col.key] && col.required
                                    ? "border-red-500/40"
                                    : "border-white/10"
                                }`}
                              >
                                <option value="">--</option>
                                {sourceColumns.map((sc) => (
                                  <option key={sc} value={sc}>
                                    {sc}
                                  </option>
                                ))}
                              </select>
                            </div>
                          ))}
                        </div>
                    </div>
                  )}

                  {/* --- Section 3: Server filters --- */}
                  <SectionHeader index={3} accent="violet" title="Filtres & confiance" />
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={filterTvrEnabled}
                      onChange={(e) => setFilterTvrEnabled(e.target.checked)}
                      className="mt-0.5 w-3.5 h-3.5 rounded accent-indigo-500"
                    />
                    <div className="flex-1">
                      <span className="text-[11px] text-slate-200">Seuil TVr serveur</span>
                      {filterTvrEnabled && (
                        <div className="mt-1 flex items-center gap-2">
                          <input
                            type="number"
                            value={filterTvrValue}
                            onChange={(e) => setFilterTvrValue(Number(e.target.value))}
                            min={0}
                            max={1000}
                            step={10}
                            className="w-16 h-6 rounded border border-white/10 bg-[rgba(8,8,18,0.6)] px-1.5 text-[11px] text-slate-200 outline-none"
                          />
                          <span className="text-[10px] text-slate-500">veh/j</span>
                        </div>
                      )}
                    </div>
                  </label>

                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={filterFcEnabled}
                      onChange={(e) => setFilterFcEnabled(e.target.checked)}
                      className="mt-0.5 w-3.5 h-3.5 rounded accent-indigo-500"
                    />
                    <span className="text-[11px] text-slate-200">Exclure FC = 1 (serveur)</span>
                  </label>

                  <div className="space-y-2">
                    <div className="flex items-center gap-1.5">
                      <SlidersHorizontal size={12} className="text-violet-400" />
                      <span className="text-[10px] font-semibold text-slate-200 uppercase tracking-wide">
                        Intervalles de confiance
                      </span>
                    </div>
                    {[
                      { label: "< 1 000", value: err01000, setter: setErr01000 },
                      { label: "1k – 2k", value: err10002000, setter: setErr10002000 },
                      { label: "2k – 4k", value: err20004000, setter: setErr20004000 },
                      { label: "> 4 000", value: err4000plus, setter: setErr4000plus },
                    ].map((item) => (
                      <div key={item.label} className="space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] text-slate-400">{item.label} veh/j</span>
                          <span
                            className="text-[10px] text-indigo-300 font-semibold tabular-nums"
                            style={{ fontFamily: 'ui-monospace, "JetBrains Mono", monospace' }}
                          >
                            {item.value}%
                          </span>
                        </div>
                        <input
                          type="range"
                          min={5}
                          max={50}
                          step={1}
                          value={item.value}
                          onChange={(e) => item.setter(Number(e.target.value))}
                          className="w-full h-1 rounded-full appearance-none bg-[rgba(255,255,255,0.08)] accent-indigo-500 cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-2.5 [&::-webkit-slider-thumb]:h-2.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-indigo-500"
                        />
                      </div>
                    ))}
                  </div>

                  {/* --- Generate button + progress --- */}
                  {(generating || done) && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] text-slate-400 truncate">{progressText}</span>
                        <span className="text-[10px] font-mono text-indigo-300">{progress}%</span>
                      </div>
                      <div className="h-1 rounded-full bg-white/[0.06] overflow-hidden">
                        <div
                          style={{ width: `${progress}%` }}
                          className={`h-full rounded-full transition-all duration-500 ${
                            done
                              ? "bg-gradient-to-r from-emerald-500 to-emerald-400"
                              : "bg-gradient-to-r from-indigo-500 to-cyan-400"
                          }`}
                        />
                      </div>
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={handleGenerate}
                    disabled={!canGenerate || generating}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-white/[0.05] disabled:text-slate-500 disabled:cursor-not-allowed text-white text-xs font-semibold transition-colors"
                  >
                    {generating ? (
                      <>
                        <Loader2 size={14} className="animate-spin" />
                        <span>Generation...</span>
                      </>
                    ) : (
                      <>
                        <Play size={14} />
                        <span>{done ? "Regenerer la carte" : "Generer la carte"}</span>
                      </>
                    )}
                  </button>

                  {!canGenerate && !generating && (
                    <p className="text-[10px] text-slate-500 leading-relaxed">
                      {tvValid !== true && "Modele TV manquant. "}
                      {plValid !== true && "Modele PL manquant. "}
                      {!sessionId && "Fichier FCD requis. "}
                      {!requiredMapped && sessionId && "Mapping incomplet."}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        </aside>

        {/* ============ RIGHT — Map ============ */}
        <div className="flex-1 relative min-w-0 flex flex-col">
          <div className={`relative ${tableOpen ? "h-[55%]" : "flex-1"} transition-[height] duration-300 p-3`}>
            <MapView
              geojson={geojson}
              filters={mapFilters}
              theme={theme}
              className="rounded-xl border border-white/[0.06] overflow-hidden shadow-xl"
            />
          </div>

          {/* A11y alternative — collapsible data table */}
          {geojson && geojson.features.length > 0 && (
            <div
              className={`shrink-0 border-t border-white/[0.08] bg-[rgba(8,8,18,0.6)] backdrop-blur ${
                tableOpen ? "h-[45%]" : "h-9"
              } transition-[height] duration-300 overflow-hidden`}
            >
              <button
                type="button"
                onClick={() => setTableOpen((v) => !v)}
                className="w-full flex items-center justify-between px-4 py-2 text-[11px] text-slate-300 hover:bg-white/[0.03]"
                aria-expanded={tableOpen}
              >
                <span className="flex items-center gap-2">
                  <TableIcon size={12} />
                  <span className="font-semibold uppercase tracking-wide">Alternative tabulaire</span>
                  <span className="text-slate-500">({geojson.features.length.toLocaleString("fr-FR")} tronçons)</span>
                </span>
                {tableOpen ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
              </button>
              {tableOpen && (
                <div className="overflow-auto h-[calc(100%-2.25rem)]">
                  <SegmentsTable
                    features={geojson.features}
                    mapControls={mapControls}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function SectionHeader({
  index,
  accent,
  title,
}: {
  index: number;
  accent: "indigo" | "cyan" | "violet";
  title: string;
}) {
  const color =
    accent === "indigo"
      ? "bg-indigo-500/15 text-indigo-300"
      : accent === "cyan"
        ? "bg-cyan/15 text-cyan"
        : "bg-violet-500/15 text-violet-300";
  return (
    <div className="flex items-center gap-2 pt-1">
      <div className={`w-5 h-5 rounded ${color} flex items-center justify-center text-[10px] font-bold`}>
        {index}
      </div>
      <h5 className="text-[11px] font-semibold text-slate-100 uppercase tracking-wide">
        {title}
      </h5>
    </div>
  );
}

function ValidityBadge({
  valid,
  missing,
}: {
  valid: boolean | null;
  missing: string[];
}) {
  if (valid === null) return null;
  return valid ? (
    <div className="flex items-center gap-1 text-[10px] text-emerald-400">
      <CheckCircle2 size={11} />
      <span>Structure valide</span>
    </div>
  ) : (
    <div className="flex items-start gap-1 text-[10px] text-red-400 leading-tight">
      <XCircle size={11} className="mt-0.5 shrink-0" />
      <span className="break-all">Manquant : {missing.join(", ")}</span>
    </div>
  );
}

function CompactFolderButton({
  icon,
  label,
  folderName,
  uploading,
  onClick,
  onClear,
}: {
  icon: React.ReactNode;
  label: string;
  folderName: string | null;
  uploading: boolean;
  onClick: () => void;
  onClear: () => void;
}) {
  if (folderName) {
    return (
      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md border border-indigo-500/20 bg-indigo-500/[0.05]">
        {icon}
        <span className="text-[11px] text-slate-200 truncate flex-1">{folderName}</span>
        <button
          type="button"
          onClick={onClear}
          className="p-0.5 rounded hover:bg-red-500/15 text-slate-500 hover:text-red-400"
          aria-label={`Retirer ${label}`}
        >
          <X size={11} />
        </button>
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={uploading}
      className="w-full flex items-center gap-2 px-2 py-2 rounded-md border border-dashed border-white/[0.1] hover:border-indigo-500/40 hover:bg-indigo-500/[0.04] text-[11px] text-slate-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
    >
      {uploading ? <Loader2 size={12} className="animate-spin" /> : <FolderOpen size={12} className="text-indigo-400" />}
      <span>{uploading ? "Upload..." : `Parcourir : ${label}`}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Alt table (a11y) — top-N rows, filtered same as the map
// ---------------------------------------------------------------------------

function SegmentsTable({
  features,
  mapControls,
}: {
  features: FeatureCollection<LineString, GeoJsonProperties>["features"];
  mapControls: MapControlsState;
}) {
  const filtered = useMemo(() => {
    return features
      .filter((f) => {
        const p = f.properties ?? {};
        const tvr = Number((p as { TVr?: number }).TVr ?? 0);
        const fc = Number((p as { FC?: number }).FC ?? 0);
        if (mapControls.minTvrFilter > 0 && tvr < mapControls.minTvrFilter) return false;
        if (mapControls.excludeFc1 && fc === 1) return false;
        return true;
      })
      .slice(0, 500); // Cap for perf; matches "alternative content" purpose
  }, [features, mapControls.minTvrFilter, mapControls.excludeFc1]);

  return (
    <table className="w-full text-[11px] font-mono tabular-nums" style={{ fontFamily: 'ui-monospace, "JetBrains Mono", monospace' }}>
      <thead className="sticky top-0 bg-[rgba(15,20,40,0.95)] z-10 text-slate-400">
        <tr className="border-b border-white/[0.08]">
          <th className="px-3 py-1.5 text-left">ID</th>
          <th className="px-3 py-1.5 text-right">TVr</th>
          <th className="px-3 py-1.5 text-right">DPL</th>
          <th className="px-3 py-1.5 text-right">PLr</th>
          <th className="px-3 py-1.5 text-right">TVr IC</th>
          <th className="px-3 py-1.5 text-right">FC</th>
        </tr>
      </thead>
      <tbody>
        {filtered.map((f, i) => {
          const p = (f.properties ?? {}) as Record<string, unknown>;
          return (
            <tr key={i} className="border-b border-white/[0.04] hover:bg-white/[0.03]">
              <td className="px-3 py-1 text-slate-300">{String(p.agregId ?? "—")}</td>
              <td className="px-3 py-1 text-right text-slate-100">
                {p.TVr != null ? Number(p.TVr).toLocaleString("fr-FR") : "—"}
              </td>
              <td className="px-3 py-1 text-right text-slate-100">
                {p.DPL != null ? Number(p.DPL).toLocaleString("fr-FR") : "—"}
              </td>
              <td className="px-3 py-1 text-right text-slate-100">
                {p.PLr != null ? `${Number(p.PLr).toFixed(1)}%` : "—"}
              </td>
              <td className="px-3 py-1 text-right text-slate-300">
                {p.TVrmin != null && p.TVrmax != null
                  ? `${Number(p.TVrmin).toLocaleString("fr-FR")}–${Number(p.TVrmax).toLocaleString("fr-FR")}`
                  : "—"}
              </td>
              <td className="px-3 py-1 text-right text-slate-400">
                {p.FC != null ? String(p.FC) : "—"}
              </td>
            </tr>
          );
        })}
        {filtered.length === 0 && (
          <tr>
            <td colSpan={6} className="px-3 py-3 text-center text-slate-500">
              Aucun tronçon ne correspond aux filtres.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
