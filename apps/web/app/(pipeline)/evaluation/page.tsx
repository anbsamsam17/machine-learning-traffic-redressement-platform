"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { apiUrl } from "@/lib/api-url";
import { fetchWithAuth } from "@/lib/auth";
import Link from "next/link";
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
  Package,
  Server,
  Database,
} from "lucide-react";
import { toast } from "sonner";
import { samNotify, samMood } from "@/lib/sam-fallback";
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

type ModelSource = "session" | "upload";

/* ---------- Page ---------- */

export default function EvaluationPage() {
  const { mode, sessionId, setSessionId, outputDir } = useAppStore();

  // APP-EVAL-FIX: keep the training session_id (in store) decoupled from the
  // validation file's session_id. Uploading a validation file used to overwrite
  // the store's sessionId, which then made loadModelsFromSession() query an
  // empty (validation-only) session and lose the trained models. We now hold
  // the validation-file session_id locally and only fall back to the store
  // sessionId when no training session exists (upload-only flow).
  const [validationSessionId, setValidationSessionId] = useState<string | null>(null);
  const effectiveSessionId = validationSessionId ?? sessionId ?? null;

  const [validationFile, setValidationFile] = useState<File | null>(null);
  const [fileColumns, setFileColumns] = useState<string[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [requiredCols, setRequiredCols] = useState<string[]>([]);
  const [colMapping, setColMapping] = useState<Record<string, string>>({});
  // Dedicated year handling — separated from regular column mapping because
  // year_mapped is DERIVED from the source Annee column via a 2019→1…2025→7
  // (or similar) encoding stored in training_config.year_value_mapping.
  const [needsYearMapping, setNeedsYearMapping] = useState(false);
  const [yearSourceCol, setYearSourceCol] = useState<string>("");
  const [yearMapping, setYearMapping] = useState<Array<{ year: string; value: number }>>(
    [],
  );
  const [loadingModels, setLoadingModels] = useState(false);
  const [running, setRunning] = useState(false);
  const [metrics, setMetrics] = useState<EvalMetrics | null>(null);
  const [reportHtml, setReportHtml] = useState<string | null>(null);
  const [reportBlob, setReportBlob] = useState<Blob | null>(null);
  const [resolvedModelDir, setResolvedModelDir] = useState(outputDir ?? "");
  const [filterFlagPermanent, setFilterFlagPermanent] = useState(false);
  const [metricsFlash, setMetricsFlash] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const metricsContainerRef = useRef<HTMLDivElement>(null);

  // Model source tab
  const [modelSource, setModelSource] = useState<ModelSource>(
    outputDir || sessionId ? "session" : "upload"
  );
  const [uploading, setUploading] = useState(false);
  const [folderName, setFolderName] = useState<string | null>(null);
  const [folderFileCount, setFolderFileCount] = useState(0);

  // Hidden folder input ref — only mounted after the user explicitly clicks
  // the "Parcourir un dossier" button. Mounting it unconditionally has been
  // reported to make some Chromium builds auto-open a native file picker on
  // page load (APP-P1-9), so we delay the mount until intent is confirmed.
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [folderPickerArmed, setFolderPickerArmed] = useState(false);

  // Ambient mood on mount — invite user to load a model
  useEffect(() => {
  }, []);

  // --- Upload validation file and get columns ---
  const handleValidationFile = useCallback(async (f: File) => {
    setValidationFile(f);
    setMetrics(null);
    setReportHtml(null);

    const samToastId = "eval-validation-upload";
    samNotify.analysing("Je verifie les donnees de validation...", { id: samToastId });

    try {
      const form = new FormData();
      form.append("file", f);
      form.append("mode", mode === "pl" ? "PL" : mode === "hpm" ? "HPM" : mode === "hps" ? "HPS" : "TV");

      const uploadRes = await fetchWithAuth(apiUrl("/api/upload"), { method: "POST", body: form });
      if (!uploadRes.ok) {
        const e = await uploadRes.json().catch(() => ({}));
        throw new Error(e.detail ?? "Upload echoue");
      }
      const data = await uploadRes.json();
      const newSid: string = data.session_id;
      // APP-EVAL-FIX: only promote the validation session_id to the global
      // store when there is no training session yet (upload-only flow). Otherwise
      // keep it local so the trained models remain reachable via the store sid.
      setValidationSessionId(newSid);
      if (!sessionId) {
        setSessionId(newSid);
      }
      setFileColumns(data.columns ?? []);

      samNotify.success(`Fichier charge : ${f.name}`, { id: samToastId });
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      samNotify.error(message, { id: samToastId, title: "Validation file" });
    }
  }, [sessionId, setSessionId, mode]);

  // --- Load models from session ---
  const loadModelsFromSession = useCallback(async () => {
    const sid = sessionId;
    if (!sid) return;
    setLoadingModels(true);
    try {
      const res = await fetchWithAuth(apiUrl(`/api/models/list?session_id=${encodeURIComponent(sid)}`));
      if (!res.ok) throw new Error(`Erreur ${res.status}`);
      const data = await res.json();
      const modelList: ModelInfo[] = data.models ?? [];
      setModels(modelList);
      if (modelList.length > 0) {
        setSelectedModel(modelList[0].name);
        // Use the path of first model's parent as resolved dir
        const firstPath = modelList[0].path;
        const parentDir = firstPath.substring(0, firstPath.lastIndexOf("/")) || firstPath.substring(0, firstPath.lastIndexOf("\\"));
        setResolvedModelDir(parentDir);
        toast.success(`${modelList.length} modele(s) de la session`);
      } else {
        toast.warning("Aucun modele trouve dans cette session.");
      }
    } catch {
      toast.error("Impossible de lister les modeles de la session.");
    } finally {
      setLoadingModels(false);
    }
  }, [sessionId]);

  // --- Upload model folder (webkitdirectory) ---
  const handleFolderSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;

    // APP-EVAL-FIX: use effective session id (validation upload preferred, store
    // session id as fallback) so the folder upload works whether the user is in
    // upload-only mode or arrived from a training session.
    const sidForUpload = validationSessionId ?? sessionId;
    if (!sidForUpload) {
      toast.error("Pas de session active. Chargez d'abord un fichier de validation.");
      return;
    }

    // Extract folder name from first file's webkitRelativePath
    const firstPath = (fileList[0] as File & { webkitRelativePath?: string }).webkitRelativePath ?? fileList[0].name;
    const rootFolder = firstPath.split("/")[0] || "dossier";
    setFolderName(rootFolder);
    setFolderFileCount(fileList.length);
    setUploading(true);
    setModels([]);
    setSelectedModel("");

    try {
      const form = new FormData();
      form.append("session_id", sidForUpload);

      for (let i = 0; i < fileList.length; i++) {
        const file = fileList[i] as File & { webkitRelativePath?: string };
        const relativePath = file.webkitRelativePath ?? file.name;
        // Strip the root folder name so paths start at subfolder level
        const parts = relativePath.split("/");
        const strippedPath = parts.length > 1 ? parts.slice(1).join("/") : parts[0];
        // Append as blob with the relative path as filename
        form.append("files", file, strippedPath);
      }

      const res = await fetchWithAuth(apiUrl("/api/models/upload-folder"), { method: "POST", body: form });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail ?? "Upload echoue");
      }
      const data = await res.json();
      const modelList: ModelInfo[] = data.models ?? [];
      setModels(modelList);
      setResolvedModelDir(data.extract_dir ?? "");

      if (modelList.length > 0) {
        setSelectedModel(modelList[0].name);
        toast.success(`${modelList.length} modele(s) trouves dans "${rootFolder}"`);
      } else {
        toast.warning("Aucun modele valide trouve dans le dossier.");
      }
    } catch (err: unknown) {
      toast.error(`Erreur: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setUploading(false);
    }
  }, [sessionId, validationSessionId]);

  const clearFolder = useCallback(() => {
    setFolderName(null);
    setFolderFileCount(0);
    setModels([]);
    setSelectedModel("");
    if (folderInputRef.current) {
      folderInputRef.current.value = "";
    }
    // Disarm the picker so the input is unmounted again until the next click.
    setFolderPickerArmed(false);
  }, []);

  // APP-P1-9: explicit user gesture handler — arms the picker, then clicks
  // the freshly mounted input once. queueMicrotask waits for the ref to attach.
  const openFolderPicker = useCallback(() => {
    // APP-EVAL-FIX: allow opening the picker as long as either a training
    // session (store sid) or a validation upload sid is available.
    if (!effectiveSessionId || uploading) return;
    setFolderPickerArmed(true);
    queueMicrotask(() => {
      folderInputRef.current?.click();
    });
  }, [effectiveSessionId, uploading]);

  // Auto-load session models on mount
  useEffect(() => {
    if (sessionId && modelSource === "session") {
      loadModelsFromSession();
    }
  }, [sessionId, modelSource, loadModelsFromSession]);

  // --- When model selection changes, update required columns + auto-map ---
  useEffect(() => {
    const model = models.find((m) => m.name === selectedModel);
    if (!model?.training_config) {
      setRequiredCols([]);
      return;
    }
    const inputCols = (model.training_config.input_cols as string[]) ?? [];
    // Read both legacy `output_col` (singular) and current `output_cols`
    // (plural list — written by the training pipeline). Default TxPen
    // (the new FCD HERE schema) not TxPenTVRef (legacy Bordeaux).
    const tc = model.training_config as Record<string, unknown>;
    const outputColSingular = typeof tc.output_col === "string" ? tc.output_col : null;
    const outputColsList = Array.isArray(tc.output_cols) ? (tc.output_cols as string[]) : null;
    const outputCol = outputColSingular || outputColsList?.[0] || "TxPen";

    // Split year_mapped from the regular mapping list — it's handled by
    // a dedicated UI block (year source column + table 2019→1 etc.).
    const hasYearMapped = inputCols.includes("year_mapped");
    const regularInputs = inputCols.filter((c) => c !== "year_mapped");
    const needed = [...regularInputs, outputCol];
    setRequiredCols(needed);
    setNeedsYearMapping(hasYearMapped);

    // Initialise the dedicated year state
    const fileLower: Record<string, string> = {};
    fileColumns.forEach((c) => { fileLower[c.toLowerCase()] = c; });
    if (hasYearMapped) {
      const tcMapping = (tc.year_value_mapping as Record<string, number>) || null;
      const tcSrc = typeof tc.year_column_name === "string" ? tc.year_column_name : "";
      // Auto-detect source year col (Annee/annee/Year/year)
      const autoSrc =
        (tcSrc && fileLower[tcSrc.toLowerCase()]) ||
        fileLower["annee"] ||
        fileLower["year"] ||
        "";
      setYearSourceCol(autoSrc);
      if (tcMapping && Object.keys(tcMapping).length > 0) {
        setYearMapping(
          Object.entries(tcMapping)
            .map(([year, value]) => ({ year, value }))
            .sort((a, b) => a.year.localeCompare(b.year)),
        );
      } else {
        // Sensible default 2019→1 … 2025→7
        setYearMapping([
          { year: "2019", value: 1 }, { year: "2020", value: 2 },
          { year: "2021", value: 3 }, { year: "2022", value: 4 },
          { year: "2023", value: 5 }, { year: "2024", value: 6 },
          { year: "2025", value: 7 },
        ]);
      }
    } else {
      setYearSourceCol("");
      setYearMapping([]);
    }

    // Auto-map the regular columns (no special year case here anymore)
    const mapping: Record<string, string> = {};
    for (const col of needed) {
      if (fileColumns.includes(col)) {
        mapping[col] = col;
      } else if (fileLower[col.toLowerCase()]) {
        mapping[col] = fileLower[col.toLowerCase()];
      } else {
        mapping[col] = "";
      }
    }
    setColMapping(mapping);
  }, [selectedModel, models, fileColumns]);

  const unmappedCount = Object.values(colMapping).filter((v) => !v).length;
  const yearReady = !needsYearMapping || (
    yearSourceCol !== "" && yearMapping.length > 0 &&
    yearMapping.every((r) => r.year.trim() !== "" && Number.isFinite(r.value))
  );
  const allMapped = requiredCols.length > 0 && unmappedCount === 0 && yearReady;

  // --- Run evaluation ---
  const handleRun = useCallback(async () => {
    if (!validationFile) { toast.error("Selectionnez un fichier."); return; }
    if (!selectedModel) { toast.error("Selectionnez un modele."); return; }
    if (!allMapped) {
      const missingReg = unmappedCount > 0;
      const missingYear = needsYearMapping && !yearReady;
      if (missingReg && missingYear) {
        toast.error("Mappez toutes les colonnes ET configurez le mapping annee.");
      } else if (missingReg) {
        toast.error("Mappez toutes les colonnes requises.");
      } else {
        toast.error("Configurez le mapping de l'annee (colonne source + table).");
      }
      return;
    }

    setRunning(true);
    setMetrics(null);
    setReportHtml(null);
    setReportBlob(null);

    const samRunToastId = "eval-run";
    samNotify.thinking("J'evalue le modele...", { id: samRunToastId });

    try {
      // APP-EVAL-FIX: the session_id sent to the backend is the *validation*
      // session (= where validation_df lives). It is independent from the
      // training session_id, which is only used by the frontend to discover
      // trained models (resolvedModelDir is already pointing to disk).
      let sid: string = validationSessionId ?? sessionId ?? "";
      if (!sid) {
        const fd = new FormData();
        fd.append("file", validationFile);
        fd.append("mode", mode === "pl" ? "PL" : mode === "hpm" ? "HPM" : mode === "hps" ? "HPS" : "TV");
        const r = await fetchWithAuth(apiUrl("/api/upload"), { method: "POST", body: fd });
        if (!r.ok) throw new Error("Impossible de creer la session");
        sid = (await r.json()).session_id as string;
        setValidationSessionId(sid);
        if (!sessionId) {
          setSessionId(sid);
        }
      }

      // Upload validation file only if we need to (the file was already uploaded
      // at step 1 via /api/upload which stores it as raw_df. We re-upload via
      // /api/evaluation/upload-validation to apply column mapping and store as validation_df.
      // But only if the file isn't too large — skip re-upload for big files and rely on raw_df fallback.)
      try {
        const form = new FormData();
        form.append("file", validationFile);
        form.append("session_id", sid);
        form.append("column_mapping", JSON.stringify(colMapping));
        const uploadRes = await fetchWithAuth(apiUrl("/api/evaluation/upload-validation"), { method: "POST", body: form });
        if (!uploadRes.ok) {
          // If upload fails (413 too large, etc.), the backend will fallback to raw_df
          console.warn("Re-upload validation failed, will use raw_df fallback");
        }
      } catch {
        console.warn("Re-upload validation failed, will use raw_df fallback");
      }

      // Run evaluation. The year encoding is handled separately:
      // the backend receives year_column_name + year_value_mapping and
      // computes df["year_mapped"] = df[year_column_name].map(...) using
      // the table the user configured (defaults to 2019:1 … 2025:7).
      const yearMappingDict = needsYearMapping
        ? Object.fromEntries(yearMapping.map((r) => [r.year.trim(), r.value]))
        : null;
      const evalRes = await fetchWithAuth(apiUrl("/api/evaluation/run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sid,
          model_name: selectedModel,
          model_dir: resolvedModelDir.trim(),
          filter_flag_permanent: filterFlagPermanent,
          column_mapping: colMapping,
          year_column_name: needsYearMapping ? yearSourceCol : null,
          year_value_mapping: yearMappingDict,
        }),
      });
      if (!evalRes.ok) {
        const err = await evalRes.json().catch(() => ({}));
        throw new Error(err.detail ?? "Evaluation echouee");
      }
      const evalData = await evalRes.json();
      setMetrics(evalData.metrics);

      // Fetch report
      const reportRes = await fetchWithAuth(apiUrl(`/api/evaluation/report/${sid}`));
      if (reportRes.ok) {
        const reportData = await reportRes.json();
        setReportHtml(reportData.report_html);
        setReportBlob(new Blob([reportData.report_html], { type: "text/html" }));
      }

      const r2Str = evalData.metrics.r_squared.toFixed(4);
      const gehStr = evalData.metrics.geh_pct_below_5.toFixed(1);
      toast.success(
        `Evaluation terminee — R² = ${r2Str}, GEH<5% = ${gehStr}% (${selectedModel})`
      );
      samNotify.success(`Eval terminee. GEH<5: ${gehStr}%`, { id: samRunToastId });

      setMetricsFlash(true);
      setTimeout(() => setMetricsFlash(false), 2000);
      setTimeout(() => {
        spawnConfetti(metricsContainerRef.current, 20);
      }, 100);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`Erreur: ${message}`);
      samNotify.error(message, { id: samRunToastId, title: "Evaluation" });
    } finally {
      setRunning(false);
    }
  }, [validationFile, selectedModel, resolvedModelDir, sessionId, validationSessionId, filterFlagPermanent, colMapping, allMapped, mode, setSessionId, needsYearMapping, yearMapping, yearSourceCol, unmappedCount, yearReady]);

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
    if (!selectedModel || !resolvedModelDir) return;
    try {
      const res = await fetchWithAuth(apiUrl(`/api/evaluation/download-model?model_name=${encodeURIComponent(selectedModel)}&model_dir=${encodeURIComponent(resolvedModelDir.trim())}`));
      if (!res.ok) throw new Error("Telechargement echoue");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${selectedModel}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error("Impossible de telecharger le modele."); }
  }, [selectedModel, resolvedModelDir]);

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <GradientText as="h1" className="text-2xl">Evaluation</GradientText>
        <p className="text-sm text-slate-300">
          Evaluez un modele {
            mode === "pl"
              ? "PL"
              : mode === "hpm"
                ? "HPM (8h-9h, v/h)"
                : mode === "hps"
                  ? "HPS (17h-18h, v/h)"
                  : "TV"
          } sur un fichier de validation.
          Cette etape peut etre lancee independamment.
        </p>
      </div>

      {/* Empty-state non-bloquant (Tache 1) — l'evaluation peut s'amorcer
          sans session existante (upload validation + modeles externes), on
          se contente donc d'une simple invitation discrete. */}
      {!effectiveSessionId && !validationFile && (
        <GlowCard glowColor="cyan">
          <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-indigo-500/10 flex items-center justify-center text-indigo-300 shrink-0">
              <Database size={22} aria-hidden="true" />
            </div>
            <div className="flex-1 space-y-1">
              <h3 className="text-sm font-semibold text-white">
                Demarrer une evaluation
              </h3>
              <p className="text-xs text-slate-300">
                Tu peux evaluer un modele independamment : depose un fichier
                de validation ci-dessous, puis choisis un modele (session
                existante ou dossier local). Pour utiliser le pipeline
                complet, importe d&apos;abord un jeu via{" "}
                <strong>Etape 1 — Donnees</strong>.
              </p>
            </div>
            <Link href="/donnees" className="shrink-0">
              <NeonButton variant="ghost" icon={<ArrowRight size={14} />}>
                Etape Donnees
              </NeonButton>
            </Link>
          </div>
        </GlowCard>
      )}

      {/* 1. Fichier de validation */}
      <GlowCard>
        <div className="flex items-center gap-2 mb-4">
          <Upload size={18} className="text-accent" />
          <h3 className="text-sm font-semibold text-white">1. Fichier de validation</h3>
        </div>
        <DropZone
          file={validationFile}
          onFile={handleValidationFile}
          onClear={() => {
            setValidationFile(null);
            setFileColumns([]);
            setColMapping({});
            // APP-EVAL-FIX: clear the local validation session id so a fresh
            // upload creates a new one cleanly.
            setValidationSessionId(null);
          }}
          accept={{ "application/json": [".geojson", ".json"], "text/csv": [".csv"] }}
          label="Deposez votre fichier de validation"
          description="GeoJSON ou CSV avec donnees de comptage"
        />
        <label className="flex items-center gap-3 mt-4 cursor-pointer group">
          <div className="relative">
            <input type="checkbox" checked={filterFlagPermanent} onChange={(e) => setFilterFlagPermanent(e.target.checked)} className="sr-only peer" />
            <div className="w-10 h-5 rounded-full bg-slate-700 peer-checked:bg-indigo-500 transition-colors" />
            <div className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform peer-checked:translate-x-5" />
          </div>
          <span className="text-sm text-slate-300 group-hover:text-slate-100 transition-colors">
            Limiter aux capteurs permanents (type compteur = Permanent / Siredo)
          </span>
        </label>
      </GlowCard>

      {/* 2. Selection du modele — tabs */}
      <GlowCard glowColor="cyan">
        <div className="flex items-center gap-2 mb-4">
          <FolderOpen size={18} className="text-cyan-400" />
          <h3 className="text-sm font-semibold text-white">2. Selection du modele</h3>
        </div>

        {/* Tab buttons */}
        <div className="flex gap-1 p-1 rounded-xl bg-slate-900/60 border border-white/[0.06] mb-4">
          <button
            type="button"
            onClick={() => setModelSource("session")}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-xs font-medium transition-all ${
              modelSource === "session"
                ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 shadow-sm"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
            }`}
          >
            <Server size={14} />
            Modeles de la session
          </button>
          <button
            type="button"
            onClick={() => setModelSource("upload")}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-xs font-medium transition-all ${
              modelSource === "upload"
                ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 shadow-sm"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
            }`}
          >
            <Package size={14} />
            Parcourir un dossier de modeles
          </button>
        </div>

        {/* Tab content: Session models */}
        {modelSource === "session" && (
          <div className="space-y-3">
            <p className="text-xs text-slate-400">
              Les modeles entraines dans cette session sont charges automatiquement.
            </p>
            <NeonButton
              variant="secondary"
              onClick={loadModelsFromSession}
              disabled={!sessionId || loadingModels}
              className="text-xs"
            >
              {loadingModels ? <Loader2 size={14} className="animate-spin mr-1.5" /> : null}
              Rafraichir les modeles
            </NeonButton>
            <AnimatePresence>
              {models.length > 0 && (
                <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="space-y-2">
                  <div className="relative">
                    <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}
                      className="w-full appearance-none rounded-lg border border-white/[0.08] bg-slate-900/80 px-3 py-2.5 pr-10 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50 cursor-pointer">
                      {models.map((m) => (
                        <option key={m.name} value={m.name}>{m.name} {m.has_weights ? "" : "(poids manquants)"}</option>
                      ))}
                    </select>
                    <ChevronDown size={16} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
                  </div>
                  <p className="text-xs text-slate-400">{models.length} modele(s) disponible(s)</p>
                </motion.div>
              )}
            </AnimatePresence>
            {!sessionId && (
              <p className="text-xs text-amber-400">
                Aucune session active. Lancez d&apos;abord un entrainement ou chargez un fichier de validation.
              </p>
            )}
          </div>
        )}

        {/* Tab content: Upload folder */}
        {modelSource === "upload" && (
          <div className="space-y-3">
            <p className="text-xs text-slate-400">
              Selectionnez un dossier contenant un ou plusieurs sous-dossiers de modeles.
              Chaque sous-dossier doit contenir NNarchitecture.json, NNweights.weights.h5 et NNnormCoefficients.json.
            </p>

            {/* Hidden folder input — only mounted after the user clicks the
                button below. Some Chromium builds open the native picker on
                mount when an <input type="file" webkitdirectory> is present in
                the tree even with display:none, so we keep it unmounted by
                default. */}
            {folderPickerArmed && (
              <input
                ref={folderInputRef}
                type="file"
                // @ts-ignore webkitdirectory is non-standard but widely supported
                webkitdirectory=""
                directory=""
                multiple
                className="hidden"
                onChange={handleFolderSelect}
                data-testid="folder-picker-input"
              />
            )}

            {!folderName ? (
              <button
                type="button"
                onClick={openFolderPicker}
                disabled={!effectiveSessionId || uploading}
                data-testid="open-folder-picker"
                className="w-full relative flex flex-col items-center justify-center gap-4 p-10 rounded-2xl border-2 border-dashed border-white/[0.08] hover:border-indigo-500/40 bg-slate-900/30 hover:bg-indigo-500/5 transition-all duration-300 cursor-pointer group disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <div className="w-14 h-14 rounded-2xl bg-indigo-500/10 flex items-center justify-center text-indigo-400 group-hover:bg-indigo-500/20 transition-colors">
                  <FolderOpen size={26} />
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium text-slate-200">Parcourir un dossier de modeles</p>
                  <p className="text-xs text-slate-400 mt-1">Selectionnez le dossier contenant vos modeles entraines</p>
                </div>
              </button>
            ) : (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex items-center gap-4 p-4 rounded-xl border border-indigo-500/20 bg-indigo-500/5"
              >
                <div className="w-12 h-12 rounded-xl bg-indigo-500/10 flex items-center justify-center text-indigo-400 flex-shrink-0">
                  <FolderOpen size={22} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-200 truncate">{folderName}</p>
                  <p className="text-xs text-slate-400 mt-0.5">{folderFileCount} fichier(s) uploade(s)</p>
                </div>
                <button
                  type="button"
                  onClick={clearFolder}
                  className="p-2 rounded-lg hover:bg-red-500/10 text-slate-400 hover:text-red-400 transition-colors text-xs"
                >
                  Effacer
                </button>
              </motion.div>
            )}

            {!effectiveSessionId && (
              <p className="text-xs text-amber-400">
                Chargez d&apos;abord un fichier de validation pour activer l&apos;upload de modeles.
              </p>
            )}

            {uploading && (
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <Loader2 size={14} className="animate-spin" />
                <span>Upload et detection des modeles en cours...</span>
              </div>
            )}
            <AnimatePresence>
              {models.length > 0 && modelSource === "upload" && (
                <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="space-y-2">
                  <div className="relative">
                    <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}
                      className="w-full appearance-none rounded-lg border border-white/[0.08] bg-slate-900/80 px-3 py-2.5 pr-10 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50 cursor-pointer">
                      {models.map((m) => (
                        <option key={m.name} value={m.name}>{m.name} {m.has_weights ? "" : "(poids manquants)"}</option>
                      ))}
                    </select>
                    <ChevronDown size={16} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
                  </div>
                  <p className="text-xs text-emerald-400">{models.length} modele(s) detectes dans le dossier</p>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
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
                    <span className="text-slate-500 text-xs">&rarr;</span>
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

      {/* 3bis. Mapping dedie pour l'annee — applique l'encodage 2019→1 etc. */}
      <AnimatePresence>
        {needsYearMapping && fileColumns.length > 0 && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <GlowCard glowColor="cyan">
              <div className="flex items-center gap-2 mb-2">
                <ArrowRight size={18} className="text-cyan-400" />
                <h3 className="text-sm font-semibold text-white">
                  Mapping de l&apos;annee
                  <span className={`ml-2 text-xs ${yearReady ? "text-emerald-400" : "text-amber-400"}`}>
                    ({yearReady ? "OK" : "a configurer"})
                  </span>
                </h3>
              </div>
              <p className="text-xs text-slate-400 mb-3">
                Le modele a ete entraine avec la feature{" "}
                <code className="text-cyan-300">year_mapped</code>. Choisissez la
                colonne <strong>source</strong> qui contient l&apos;annee dans
                votre fichier, puis confirmez la table de correspondance
                <em> annee → valeur encodee</em> (auto-remplie depuis la config
                du modele).
              </p>

              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-mono w-[280px] shrink-0 text-slate-200">
                    Colonne source (annee)
                  </span>
                  <span className="text-slate-500 text-xs">&rarr;</span>
                  <select
                    value={yearSourceCol}
                    onChange={(e) => setYearSourceCol(e.target.value)}
                    className={`flex-1 rounded-lg border px-2 py-1.5 text-xs bg-slate-900/80 focus:outline-none focus:border-cyan-500/50 cursor-pointer ${
                      yearSourceCol ? "border-white/[0.08] text-slate-200" : "border-red-500/40 text-red-300"
                    }`}
                  >
                    <option value="">-- Non mappe --</option>
                    {fileColumns.map((fc) => (
                      <option key={fc} value={fc}>{fc}</option>
                    ))}
                  </select>
                </div>

                <div className="border-t border-white/[0.06] pt-3">
                  <p className="text-[11px] text-slate-400 mb-2 uppercase tracking-wide">
                    Table de correspondance
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-[260px] overflow-y-auto pr-1">
                    {yearMapping.map((row, idx) => (
                      <div key={idx} className="flex items-center gap-2">
                        <input
                          type="text"
                          value={row.year}
                          onChange={(e) => {
                            const v = e.target.value;
                            setYearMapping((arr) =>
                              arr.map((r, i) => (i === idx ? { ...r, year: v } : r)),
                            );
                          }}
                          placeholder="2019"
                          className="w-20 rounded border border-white/[0.08] bg-slate-900/80 px-2 py-1 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500/50"
                        />
                        <span className="text-slate-500 text-xs">&rarr;</span>
                        <input
                          type="number"
                          step="0.01"
                          value={row.value}
                          onChange={(e) => {
                            const v = parseFloat(e.target.value);
                            setYearMapping((arr) =>
                              arr.map((r, i) => (i === idx ? { ...r, value: v } : r)),
                            );
                          }}
                          className="w-24 rounded border border-white/[0.08] bg-slate-900/80 px-2 py-1 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500/50"
                        />
                        <button
                          type="button"
                          onClick={() => setYearMapping((arr) => arr.filter((_, i) => i !== idx))}
                          className="text-xs text-slate-500 hover:text-red-400 px-1"
                          title="Supprimer la ligne"
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      setYearMapping((arr) => [...arr, { year: "", value: arr.length + 1 }])
                    }
                    className="mt-2 text-xs text-cyan-400 hover:text-cyan-300"
                  >
                    + Ajouter une annee
                  </button>
                </div>
              </div>
              {!yearReady && (
                <p className="text-xs text-amber-400 mt-3">
                  Configurez la colonne source ET au moins une ligne du tableau.
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
