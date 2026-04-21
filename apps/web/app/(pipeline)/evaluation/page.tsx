"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { apiUrl } from "@/lib/api-url";
import {
  Download,
  Upload,
  Play,
  FileCheck,
  BarChart3,
  Activity,
  Target,
  Loader2,
  FolderOpen,
  ChevronDown,
  ArrowRight,
} from "lucide-react";
import { toast } from "sonner";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";
import { StatCard } from "@/components/ui/stat-card";
import { DropZone } from "@/components/upload/drop-zone";
import { useAppStore } from "@/lib/store";
import { spawnConfetti } from "@/lib/success-effects";

/* ---------- Types ---------- */

interface ModelInfo {
  name: string;
  path: string;
  has_weights: boolean;
  has_architecture: boolean;
  has_norm: boolean;
  training_config?: Record<string, unknown>;
}

interface EvalMetrics {
  rmse: number;
  mae: number;
  mape: number | null;
  r_squared: number;
  geh_mean: number;
  geh_pct_below_5: number;
  n_samples: number;
  hd_rmse: number | null;
  ld_rmse: number | null;
  median_relative_error?: number | null;
}

/* ---------- Page ---------- */

export default function EvaluationPage() {
  const { mode, sessionId, setSessionId, outputDir } = useAppStore();

  const [validationFile, setValidationFile] = useState<File | null>(null);
  const [fileColumns, setFileColumns] = useState<string[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [requiredCols, setRequiredCols] = useState<string[]>([]);
  const [colMapping, setColMapping] = useState<Record<string, string>>({});
  const [loadingModels, setLoadingModels] = useState(false);
  const [running, setRunning] = useState(false);
  const [metrics, setMetrics] = useState<EvalMetrics | null>(null);
  const [reportHtml, setReportHtml] = useState<string | null>(null);
  const [reportBlob, setReportBlob] = useState<Blob | null>(null);
  const [modelDir, setModelDir] = useState(outputDir ?? "");
  const [filterFlagComptage, setFilterFlagComptage] = useState(false);
  const [metricsFlash, setMetricsFlash] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const metricsContainerRef = useRef<HTMLDivElement>(null);

  // --- Upload validation file and get columns ---
  const handleValidationFile = useCallback(async (f: File) => {
    setValidationFile(f);
    setMetrics(null);
    setReportHtml(null);

    try {
      // Upload to get a session + columns list
      const form = new FormData();
      form.append("file", f);
      form.append("mode", mode === "pl" ? "PL" : "TV");

      // Always create a fresh session via upload to get columns
      const uploadRes = await fetch(apiUrl("/api/upload"), { method: "POST", body: form });
      if (!uploadRes.ok) throw new Error("Upload echoue");
      const data = await uploadRes.json();
      const newSid: string = data.session_id;
      setSessionId(newSid);
      setFileColumns(data.columns ?? []);

      toast.success(`Fichier charge : ${f.name}`);
    } catch (err) {
      console.error(err);
      toast.error("Erreur lors du chargement du fichier.");
    }
  }, [sessionId, setSessionId, mode]);

  // --- Load models ---
  const loadModels = useCallback(async (dir: string) => {
    if (!dir.trim()) return;
    setLoadingModels(true);
    try {
      const res = await fetch(apiUrl(`/api/models/list?dir=${encodeURIComponent(dir.trim())}`));
      if (!res.ok) throw new Error(`Erreur ${res.status}`);
      const data = await res.json();
      const modelList: ModelInfo[] = data.models ?? [];
      setModels(modelList);
      if (modelList.length > 0) {
        setSelectedModel(modelList[0].name);
        toast.success(`${modelList.length} modele(s) trouve(s)`);
      } else {
        toast.warning("Aucun modele trouve dans ce dossier.");
      }
    } catch {
      toast.error("Impossible de lister les modeles.");
    } finally {
      setLoadingModels(false);
    }
  }, []);

  // Auto-load on mount
  useEffect(() => {
    if (outputDir) {
      setModelDir(outputDir);
      loadModels(outputDir);
    }
  }, [outputDir, loadModels]);

  // --- When model selection changes, update required columns + auto-map ---
  useEffect(() => {
    const model = models.find((m) => m.name === selectedModel);
    if (!model?.training_config) {
      setRequiredCols([]);
      return;
    }
    const inputCols = (model.training_config.input_cols as string[]) ?? [];
    const outputCol = (model.training_config.output_col as string) ?? "TxPenTVRef";
    const needed = [...inputCols, outputCol];
    setRequiredCols(needed);

    // Auto-map: try exact match, then case-insensitive
    const mapping: Record<string, string> = {};
    const fileLower: Record<string, string> = {};
    fileColumns.forEach((c) => { fileLower[c.toLowerCase()] = c; });

    for (const col of needed) {
      if (fileColumns.includes(col)) {
        mapping[col] = col;
      } else if (fileLower[col.toLowerCase()]) {
        mapping[col] = fileLower[col.toLowerCase()];
      } else {
        mapping[col] = ""; // not found — user must map
      }
    }
    setColMapping(mapping);
  }, [selectedModel, models, fileColumns]);

  const unmappedCount = Object.values(colMapping).filter((v) => !v).length;
  const allMapped = requiredCols.length > 0 && unmappedCount === 0;

  // --- Run evaluation ---
  const handleRun = useCallback(async () => {
    if (!validationFile) { toast.error("Selectionnez un fichier."); return; }
    if (!selectedModel) { toast.error("Selectionnez un modele."); return; }
    if (!allMapped) { toast.error("Mappez toutes les colonnes requises."); return; }

    setRunning(true);
    setMetrics(null);
    setReportHtml(null);
    setReportBlob(null);

    try {
      let sid: string = sessionId ?? "";
      if (!sid) {
        const fd = new FormData();
        fd.append("file", validationFile);
        fd.append("mode", mode === "pl" ? "PL" : "TV");
        const r = await fetch(apiUrl("/api/upload"), { method: "POST", body: fd });
        if (!r.ok) throw new Error("Impossible de creer la session");
        sid = (await r.json()).session_id as string;
        setSessionId(sid);
      }

      // Upload validation with column mapping applied
      const form = new FormData();
      form.append("file", validationFile);
      form.append("session_id", sid);
      form.append("column_mapping", JSON.stringify(colMapping));
      const uploadRes = await fetch(apiUrl("/api/evaluation/upload-validation"), { method: "POST", body: form });
      if (!uploadRes.ok) {
        const err = await uploadRes.json().catch(() => ({}));
        throw new Error(err.detail ?? "Upload echoue");
      }

      // Run evaluation
      const evalRes = await fetch(apiUrl("/api/evaluation/run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sid,
          model_name: selectedModel,
          model_dir: modelDir.trim(),
          filter_flag_comptage: filterFlagComptage,
          column_mapping: colMapping,
        }),
      });
      if (!evalRes.ok) {
        const err = await evalRes.json().catch(() => ({}));
        throw new Error(err.detail ?? "Evaluation echouee");
      }
      const evalData = await evalRes.json();
      setMetrics(evalData.metrics);

      // Fetch report
      const reportRes = await fetch(apiUrl(`/api/evaluation/report/${sid}`));
      if (reportRes.ok) {
        const reportData = await reportRes.json();
        setReportHtml(reportData.report_html);
        setReportBlob(new Blob([reportData.report_html], { type: "text/html" }));
      }

      // Rich success toast with key metrics
      const r2Str = evalData.metrics.r_squared.toFixed(4);
      const gehStr = evalData.metrics.geh_pct_below_5.toFixed(1);
      toast.success(
        `Evaluation terminee — R² = ${r2Str}, GEH<5% = ${gehStr}% (${selectedModel})`
      );

      // Trigger count-up flash + confetti on metrics
      setMetricsFlash(true);
      setTimeout(() => setMetricsFlash(false), 2000);
      setTimeout(() => {
        spawnConfetti(metricsContainerRef.current, 20);
      }, 100);
    } catch (err: unknown) {
      toast.error(`Erreur: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setRunning(false);
    }
  }, [validationFile, selectedModel, modelDir, sessionId, filterFlagComptage, colMapping, allMapped, mode, setSessionId]);

  const downloadReport = useCallback(() => {
    if (!reportBlob) return;
    const url = URL.createObjectURL(reportBlob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Rapport_Evaluation_${selectedModel}.html`;
    a.click();
    URL.revokeObjectURL(url);
  }, [reportBlob, selectedModel]);

  const downloadModelZip = useCallback(async () => {
    if (!selectedModel || !modelDir) return;
    try {
      const res = await fetch(apiUrl(`/api/evaluation/download-model?model_name=${encodeURIComponent(selectedModel)}&model_dir=${encodeURIComponent(modelDir.trim())}`));
      if (!res.ok) throw new Error("Telechargement echoue");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${selectedModel}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error("Impossible de telecharger le modele."); }
  }, [selectedModel, modelDir]);

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <GradientText as="h2" className="text-2xl">Evaluation</GradientText>
        <p className="text-sm text-slate-300">
          Evaluez un modele {mode === "pl" ? "PL" : "TV"} sur un fichier de validation.
          Cette etape peut etre lancee independamment.
        </p>
      </div>

      {/* 1. Fichier de validation */}
      <GlowCard>
        <div className="flex items-center gap-2 mb-4">
          <Upload size={18} className="text-accent" />
          <h3 className="text-sm font-semibold text-white">1. Fichier de validation</h3>
        </div>
        <DropZone
          file={validationFile}
          onFile={handleValidationFile}
          onClear={() => { setValidationFile(null); setFileColumns([]); setColMapping({}); }}
          accept={{ "application/json": [".geojson", ".json"], "text/csv": [".csv"] }}
          label="Deposez votre fichier de validation"
          description="GeoJSON ou CSV avec donnees de comptage"
        />
        <label className="flex items-center gap-3 mt-4 cursor-pointer group">
          <div className="relative">
            <input type="checkbox" checked={filterFlagComptage} onChange={(e) => setFilterFlagComptage(e.target.checked)} className="sr-only peer" />
            <div className="w-10 h-5 rounded-full bg-slate-700 peer-checked:bg-indigo-500 transition-colors" />
            <div className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform peer-checked:translate-x-5" />
          </div>
          <span className="text-sm text-slate-300 group-hover:text-slate-100 transition-colors">
            Limiter aux capteurs permanents (flag_comptage = 1)
          </span>
        </label>
      </GlowCard>

      {/* 2. Selection du modele */}
      <GlowCard glowColor="cyan">
        <div className="flex items-center gap-2 mb-4">
          <FolderOpen size={18} className="text-cyan-400" />
          <h3 className="text-sm font-semibold text-white">2. Selection du modele</h3>
        </div>
        <div className="space-y-3">
          <div className="flex gap-2">
            <input type="text" value={modelDir} onChange={(e) => setModelDir(e.target.value)}
              placeholder="Ex: C:\xMDL\TV\MonTerritoire"
              className="flex-1 rounded-lg border border-white/[0.08] bg-slate-900/80 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-indigo-500/50 transition-colors"
            />
            <NeonButton variant="secondary" onClick={() => loadModels(modelDir)} disabled={!modelDir.trim() || loadingModels} className="text-xs whitespace-nowrap">
              {loadingModels ? <Loader2 size={14} className="animate-spin" /> : "Charger"}
            </NeonButton>
          </div>
          <AnimatePresence>
            {models.length > 0 && (
              <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="space-y-2">
                <div className="relative">
                  <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}
                    className="w-full appearance-none rounded-lg border border-white/[0.08] bg-slate-900/80 px-3 py-2.5 pr-10 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50 cursor-pointer">
                    {models.map((m) => (
                      <option key={m.name} value={m.name}>{m.name} {m.has_weights ? "✓" : "⚠"}</option>
                    ))}
                  </select>
                  <ChevronDown size={16} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
                </div>
                <p className="text-xs text-slate-400">{models.length} modele(s)</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </GlowCard>

      {/* 3. Mapping colonnes */}
      <AnimatePresence>
        {requiredCols.length > 0 && fileColumns.length > 0 && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <GlowCard glowColor="violet">
              <div className="flex items-center gap-2 mb-4">
                <ArrowRight size={18} className="text-violet-400" />
                <h3 className="text-sm font-semibold text-white">
                  3. Mapping des colonnes
                  <span className={`ml-2 text-xs ${allMapped ? "text-emerald-400" : "text-amber-400"}`}>
                    ({requiredCols.length - unmappedCount}/{requiredCols.length} mappees)
                  </span>
                </h3>
              </div>
              <p className="text-xs text-slate-400 mb-3">
                Le modele necessite ces colonnes. Associez chacune a une colonne de votre fichier.
              </p>
              <div className="space-y-2 max-h-[400px] overflow-y-auto pr-2">
                {requiredCols.map((col) => (
                  <div key={col} className="flex items-center gap-3">
                    <span className={`text-xs font-mono w-[280px] shrink-0 truncate ${colMapping[col] ? "text-slate-200" : "text-red-400"}`}>
                      {col}
                    </span>
                    <span className="text-slate-500 text-xs">→</span>
                    <select
                      value={colMapping[col] ?? ""}
                      onChange={(e) => setColMapping((prev) => ({ ...prev, [col]: e.target.value }))}
                      className={`flex-1 rounded-lg border px-2 py-1.5 text-xs bg-slate-900/80 focus:outline-none focus:border-indigo-500/50 cursor-pointer ${
                        colMapping[col] ? "border-white/[0.08] text-slate-200" : "border-red-500/40 text-red-300"
                      }`}
                    >
                      <option value="">-- Non mappe --</option>
                      {fileColumns.map((fc) => (
                        <option key={fc} value={fc}>{fc}</option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
              {unmappedCount > 0 && (
                <p className="text-xs text-amber-400 mt-3">
                  {unmappedCount} colonne(s) non mappee(s) — l&apos;evaluation ne pourra pas demarrer.
                </p>
              )}
            </GlowCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 4. Lancer */}
      <div className="flex justify-center">
        <NeonButton variant="primary"
          icon={running ? <Loader2 size={18} className="animate-spin" /> : <Play size={18} />}
          onClick={handleRun}
          disabled={running || !validationFile || !selectedModel || !allMapped}
          className="px-10 py-4 text-base">
          {running ? "Evaluation en cours..." : "4. Lancer l'evaluation"}
        </NeonButton>
      </div>

      {/* 5. Metriques */}
      <AnimatePresence>
        {metrics && (
          <motion.div ref={metricsContainerRef} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="relative space-y-4">
            <div className="flex items-center gap-2">
              <BarChart3 size={18} className="text-accent" />
              <h3 className="text-sm font-semibold text-white">
                Metriques — <span className="text-accent">{selectedModel}</span>
              </h3>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
              <StatCard label="MAE" value={metrics.mae.toFixed(2)} icon={<Activity size={18} />}
                className={metricsFlash ? "animate-success-pulse" : ""} />
              <StatCard label="RMSE" value={metrics.rmse.toFixed(2)} icon={<Target size={18} />}
                className={metricsFlash ? "animate-success-pulse" : ""} />
              <StatCard label="R²" value={metrics.r_squared.toFixed(4)} icon={<BarChart3 size={18} />}
                trend={metrics.r_squared > 0.95 ? "up" : metrics.r_squared > 0.85 ? "neutral" : "down"}
                className={metricsFlash ? "animate-success-pulse animate-count-flash" : ""} />
              <StatCard label="GEH < 5%" value={`${metrics.geh_pct_below_5.toFixed(1)}%`} icon={<FileCheck size={18} />}
                trend={metrics.geh_pct_below_5 > 85 ? "up" : "down"}
                className={metricsFlash ? "animate-success-pulse animate-count-flash" : ""} />
              <StatCard label="Echantillons" value={metrics.n_samples.toString()}
                className={metricsFlash ? "animate-success-pulse" : ""} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 6. Rapport HTML */}
      <AnimatePresence>
        {reportHtml && (
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="max-w-none -mx-6">
            <GlowCard glowColor="violet" className="!p-0 overflow-hidden max-w-none">
              <div className="flex items-center justify-between p-4 border-b border-white/[0.06]">
                <div className="flex items-center gap-2">
                  <FileCheck size={18} className="text-violet-400" />
                  <h3 className="text-sm font-semibold text-white">Rapport d&apos;evaluation</h3>
                </div>
                <span className="text-xs text-slate-400">{selectedModel}</span>
              </div>
              <iframe ref={iframeRef} srcDoc={reportHtml} className="w-full border-0 bg-white" style={{ height: "1200px" }} title="Rapport" sandbox="allow-scripts allow-same-origin" />
            </GlowCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 7. Telechargements */}
      <AnimatePresence>
        {(reportBlob || metrics) && (
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="flex flex-wrap gap-3 justify-center">
            {reportBlob && (
              <NeonButton variant="secondary" icon={<Download size={16} />} onClick={downloadReport}>
                Telecharger le rapport HTML
              </NeonButton>
            )}
            <NeonButton variant="secondary" icon={<Download size={16} />} onClick={downloadModelZip}>
              Telecharger le modele (ZIP)
            </NeonButton>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
