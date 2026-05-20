"use client";

import { useState, useCallback, useEffect, useRef } from "react";
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
} from "lucide-react";
import { toast } from "sonner";
import { GlowCard as Card } from "@/components/ui/glow-card";
import { Button } from "@/components/ui/button";
import { StatCard } from "@/components/ui/stat-card";
import { DropZone } from "@/components/upload/drop-zone";
import { useAppStore } from "@/lib/store";
import { apiClient, ApiError } from "@/lib/api";
import { staggerIn } from "@/lib/animations/gsap";
import {
  useEvalRun,
  useModelsList,
  useUploadFile,
} from "@/lib/hooks";
import type {
  EvalMetrics,
  EvalReportResponse,
  ModelInfo,
  ModelsListResponse,
  UploadResponse,
} from "@/lib/types/api";

type ModelSource = "session" | "upload";

interface EvaluationFlowProps {
  mode: "evaluation";
}

const COPY = {
  evaluation: {
    title: "Evaluation",
    intro: (m: string) =>
      `Evaluez un modele ${m} sur un fichier de validation. Cette etape peut etre lancee independamment.`,
    fileSectionTitle: "1. Fichier de validation",
    dropLabel: "Deposez votre fichier de validation",
    dropDesc: "GeoJSON ou CSV avec donnees de comptage",
    noSessionFile: "fichier de validation",
    runBtnIdle: "4. Lancer l'evaluation",
    runBtnBusy: "Evaluation en cours...",
    reportTitle: "Rapport d'evaluation",
    reportDownloadPrefix: "Rapport_Evaluation_",
    toastDone: "Evaluation terminee",
  },
} as const;

export function EvaluationFlow({ mode: flowMode }: EvaluationFlowProps) {
  const copy = COPY[flowMode];
  const { mode, sessionId, setSessionId, outputDir, trainingConfig } = useAppStore();

  const [validationFile, setValidationFile] = useState<File | null>(null);
  const [fileColumns, setFileColumns] = useState<string[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [requiredCols, setRequiredCols] = useState<string[]>([]);
  const [colMapping, setColMapping] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const [metrics, setMetrics] = useState<EvalMetrics | null>(null);
  const [reportHtml, setReportHtml] = useState<string | null>(null);
  const [reportBlob, setReportBlob] = useState<Blob | null>(null);
  const [resolvedModelDir, setResolvedModelDir] = useState(outputDir ?? "");
  const [filterFlagComptage, setFilterFlagComptage] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const metricsGridRef = useRef<HTMLDivElement>(null);

  // M7 — stagger-in metric cards when metrics arrive.
  useEffect(() => {
    if (!metrics || !metricsGridRef.current) return;
    const cards = metricsGridRef.current.querySelectorAll<HTMLElement>(
      ".stat-card"
    );
    if (cards.length === 0) return;
    return staggerIn(Array.from(cards), metricsGridRef.current);
  }, [metrics]);

  const [modelSource, setModelSource] = useState<ModelSource>(
    outputDir || sessionId ? "session" : "upload"
  );
  const [uploading, setUploading] = useState(false);
  const [folderName, setFolderName] = useState<string | null>(null);
  const [folderFileCount, setFolderFileCount] = useState(0);

  const folderInputRef = useRef<HTMLInputElement>(null);

  // TanStack mutations
  const uploadFileMut = useUploadFile<UploadResponse>();
  const evalRunMut = useEvalRun();

  // TanStack Query: models for the current session (only used when
  // modelSource === "session" to avoid wasted fetches when the user is
  // uploading a folder).
  const modelsQuery = useModelsList(
    modelSource === "session" ? sessionId : null
  );
  // Toast / select-first sync from the query data.
  const lastModelsToastSidRef = useRef<string | null>(null);
  useEffect(() => {
    if (modelSource !== "session") return;
    if (modelsQuery.isError) {
      toast.error("Impossible de lister les modeles de la session.");
      return;
    }
    const data = modelsQuery.data;
    if (!data) return;
    const list = data.models ?? [];
    setModels(list);
    if (list.length > 0 && !selectedModel) {
      setSelectedModel(list[0].name);
      const firstPath = list[0].path;
      const parentDir =
        firstPath.substring(0, firstPath.lastIndexOf("/")) ||
        firstPath.substring(0, firstPath.lastIndexOf("\\"));
      setResolvedModelDir(parentDir);
    }
    // Avoid toast spam on every refetch — toast once per sessionId.
    const sid = sessionId ?? "";
    if (sid && lastModelsToastSidRef.current !== sid) {
      lastModelsToastSidRef.current = sid;
      if (list.length > 0) {
        toast.success(`${list.length} modele(s) de la session`);
      } else {
        toast.warning("Aucun modele trouve dans cette session.");
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelsQuery.data, modelsQuery.isError, modelSource, sessionId]);

  /* Upload validation file -> session_id + columns (TanStack mutation) */
  const handleValidationFile = useCallback(
    async (f: File) => {
      setValidationFile(f);
      setMetrics(null);
      setReportHtml(null);

      try {
        const data = await uploadFileMut.mutateAsync({
          file: f,
          path: "/api/upload",
          extra: { mode: mode === "pl" ? "PL" : "TV" },
        });
        setSessionId(data.session_id);
        setFileColumns(data.columns ?? []);
        toast.success(`Fichier charge : ${f.name}`);
      } catch (err) {
        const detail = err instanceof ApiError ? err.detail : String(err);
        toast.error(`Erreur lors du chargement : ${detail}`);
      }
    },
    [mode, setSessionId, uploadFileMut]
  );

  const loadModelsFromSession = useCallback(() => {
    // Manual refresh — invalidate to refetch.
    modelsQuery.refetch();
  }, [modelsQuery]);

  /* Upload model folder (webkitdirectory) */
  const handleFolderSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const fileList = e.target.files;
      if (!fileList || fileList.length === 0) return;

      if (!sessionId) {
        toast.error(`Pas de session active. Chargez d'abord un ${copy.noSessionFile}.`);
        return;
      }

      const firstPath =
        (fileList[0] as File & { webkitRelativePath?: string }).webkitRelativePath ??
        fileList[0].name;
      const rootFolder = firstPath.split("/")[0] || "dossier";
      setFolderName(rootFolder);
      setFolderFileCount(fileList.length);
      setUploading(true);
      setModels([]);
      setSelectedModel("");

      try {
        const form = new FormData();
        form.append("session_id", sessionId);
        for (let i = 0; i < fileList.length; i++) {
          const file = fileList[i] as File & { webkitRelativePath?: string };
          const relativePath = file.webkitRelativePath ?? file.name;
          const parts = relativePath.split("/");
          const strippedPath = parts.length > 1 ? parts.slice(1).join("/") : parts[0];
          form.append("files", file, strippedPath);
        }
        const data = await apiClient.postForm<ModelsListResponse>(
          "/api/models/upload-folder",
          form
        );
        const modelList = data.models ?? [];
        setModels(modelList);
        setResolvedModelDir(data.extract_dir ?? "");
        if (modelList.length > 0) {
          setSelectedModel(modelList[0].name);
          toast.success(`${modelList.length} modele(s) trouves dans "${rootFolder}"`);
        } else {
          toast.warning("Aucun modele valide trouve dans le dossier.");
        }
      } catch (err) {
        const detail = err instanceof ApiError ? err.detail : String(err);
        toast.error(`Erreur: ${detail}`);
      } finally {
        setUploading(false);
      }
    },
    [sessionId, copy.noSessionFile]
  );

  const clearFolder = useCallback(() => {
    setFolderName(null);
    setFolderFileCount(0);
    setModels([]);
    setSelectedModel("");
    if (folderInputRef.current) folderInputRef.current.value = "";
  }, []);

  /* Selected model -> derive required columns + auto-map */
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

    const mapping: Record<string, string> = {};
    const fileLower: Record<string, string> = {};
    fileColumns.forEach((c) => {
      fileLower[c.toLowerCase()] = c;
    });
    for (const col of needed) {
      if (fileColumns.includes(col)) mapping[col] = col;
      else if (fileLower[col.toLowerCase()]) mapping[col] = fileLower[col.toLowerCase()];
      else mapping[col] = "";
    }
    setColMapping(mapping);
  }, [selectedModel, models, fileColumns]);

  const unmappedCount = Object.values(colMapping).filter((v) => !v).length;
  const allMapped = requiredCols.length > 0 && unmappedCount === 0;

  /* Run evaluation */
  const handleRun = useCallback(async () => {
    if (!validationFile) {
      toast.error("Selectionnez un fichier.");
      return;
    }
    if (!selectedModel) {
      toast.error("Selectionnez un modele.");
      return;
    }
    if (!allMapped) {
      toast.error("Mappez toutes les colonnes requises.");
      return;
    }

    setRunning(true);
    setMetrics(null);
    setReportHtml(null);
    setReportBlob(null);

    try {
      let sid = sessionId ?? "";
      if (!sid) {
        const r = await uploadFileMut.mutateAsync({
          file: validationFile,
          path: "/api/upload",
          extra: { mode: mode === "pl" ? "PL" : "TV" },
        });
        sid = r.session_id;
        setSessionId(sid);
      }

      // Re-upload with column mapping for validation_df (best-effort —
      // backend falls back to raw_df on 413/network failure).
      try {
        const form = new FormData();
        form.append("file", validationFile);
        form.append("session_id", sid);
        form.append("column_mapping", JSON.stringify(colMapping));
        await apiClient.postForm("/api/evaluation/upload-validation", form);
      } catch {
        // eslint-disable-next-line no-console
        console.warn("Re-upload validation failed, will use raw_df fallback");
      }

      // Replay the training-time year encoding so models with year_mapped
      // receive the correct small integers (instead of raw 2019/2020).
      const cfg = (trainingConfig ?? {}) as {
        year_column_name?: string | null;
        year_value_mapping?: Record<string, number> | null;
      };
      const evalData = await evalRunMut.mutateAsync({
        session_id: sid,
        model_name: selectedModel,
        model_dir: resolvedModelDir.trim(),
        filter_flag_comptage: filterFlagComptage,
        column_mapping: colMapping,
        year_column_name: cfg.year_column_name ?? null,
        year_value_mapping: cfg.year_value_mapping ?? null,
      });
      setMetrics(evalData.metrics);

      try {
        const reportData = await apiClient.get<EvalReportResponse>(
          `/api/evaluation/report/${sid}`
        );
        setReportHtml(reportData.report_html);
        setReportBlob(new Blob([reportData.report_html], { type: "text/html" }));
      } catch {
        /* report optional */
      }

      const r2 = evalData.metrics.r_squared.toFixed(4);
      const geh = evalData.metrics.geh_pct_below_5.toFixed(1);
      toast.success(
        `${copy.toastDone} — R² = ${r2}, GEH<5% = ${geh}% (${selectedModel})`
      );
    } catch (err) {
      const detail = err instanceof ApiError ? err.detail : String(err);
      toast.error(`Erreur: ${detail}`);
    } finally {
      setRunning(false);
    }
  }, [
    validationFile,
    selectedModel,
    resolvedModelDir,
    sessionId,
    filterFlagComptage,
    colMapping,
    allMapped,
    mode,
    setSessionId,
    copy.toastDone,
    uploadFileMut,
    evalRunMut,
  ]);

  const downloadReport = useCallback(() => {
    if (!reportBlob) return;
    const url = URL.createObjectURL(reportBlob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${copy.reportDownloadPrefix}${selectedModel}.html`;
    a.click();
    URL.revokeObjectURL(url);
  }, [reportBlob, selectedModel, copy.reportDownloadPrefix]);

  const downloadModelZip = useCallback(async () => {
    if (!selectedModel || !resolvedModelDir) return;
    try {
      await apiClient.download(
        `/api/evaluation/download-model?model_name=${encodeURIComponent(
          selectedModel
        )}&model_dir=${encodeURIComponent(resolvedModelDir.trim())}`,
        `${selectedModel}.zip`
      );
    } catch {
      toast.error("Impossible de telecharger le modele.");
    }
  }, [selectedModel, resolvedModelDir]);

  return (
    <div className="space-y-6">
      <div className="space-y-1.5">
        <h2 className="text-2xl font-semibold text-text">{copy.title}</h2>
        <p className="text-sm text-text-muted">
          {copy.intro(mode === "pl" ? "PL" : "TV")}
        </p>
      </div>

      {/* 1. File */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Upload size={16} className="text-accent" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-text">{copy.fileSectionTitle}</h3>
        </div>
        <DropZone
          file={validationFile}
          onFile={handleValidationFile}
          onClear={() => {
            setValidationFile(null);
            setFileColumns([]);
            setColMapping({});
          }}
          accept={{ "application/json": [".geojson", ".json"], "text/csv": [".csv"] }}
          label={copy.dropLabel}
          description={copy.dropDesc}
        />
        <label className="flex items-center gap-3 mt-4 cursor-pointer group">
          <div className="relative">
            <input
              type="checkbox"
              checked={filterFlagComptage}
              onChange={(e) => setFilterFlagComptage(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-9 h-5 rounded-full bg-bg-subtle peer-checked:bg-accent transition-colors" />
            <div className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform peer-checked:translate-x-4" />
          </div>
          <span className="text-sm text-text-muted group-hover:text-text transition-colors">
            Limiter aux capteurs permanents (flag_comptage = 1)
          </span>
        </label>
      </Card>

      {/* 2. Model selection */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <FolderOpen size={16} className="text-accent" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-text">2. Selection du modele</h3>
        </div>

        {/* Tab buttons */}
        <div
          role="tablist"
          aria-label="Source des modeles"
          className="flex gap-1 p-1 rounded-md bg-bg-subtle border border-border mb-4"
        >
          <button
            type="button"
            role="tab"
            aria-selected={modelSource === "session"}
            onClick={() => setModelSource("session")}
            className={`flex-1 flex items-center justify-center gap-2 px-3 h-8 rounded text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
              modelSource === "session"
                ? "bg-bg-elevated text-text border border-border"
                : "text-text-muted hover:text-text"
            }`}
          >
            <Server size={12} aria-hidden="true" />
            Modeles de la session
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={modelSource === "upload"}
            onClick={() => setModelSource("upload")}
            className={`flex-1 flex items-center justify-center gap-2 px-3 h-8 rounded text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
              modelSource === "upload"
                ? "bg-bg-elevated text-text border border-border"
                : "text-text-muted hover:text-text"
            }`}
          >
            <Package size={12} aria-hidden="true" />
            Parcourir un dossier
          </button>
        </div>

        {modelSource === "session" && (
          <div className="space-y-3">
            <p className="text-xs text-text-muted">
              Les modeles entraines dans cette session sont charges automatiquement.
            </p>
            <Button
              variant="secondary"
              size="sm"
              onClick={loadModelsFromSession}
              disabled={!sessionId || modelsQuery.isFetching}
              icon={modelsQuery.isFetching ? <Loader2 size={12} className="animate-spin" /> : undefined}
            >
              Rafraichir les modeles
            </Button>
            {models.length > 0 && (
              <div className="space-y-1.5">
                <div className="relative">
                  <select
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                    className="w-full appearance-none rounded border border-border bg-bg-elevated px-3 h-9 pr-9 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent cursor-pointer font-mono"
                    aria-label="Modele selectionne"
                  >
                    {models.map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.name} {m.has_weights ? "" : "(poids manquants)"}
                      </option>
                    ))}
                  </select>
                  <ChevronDown
                    size={14}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-text-subtle pointer-events-none"
                    aria-hidden="true"
                  />
                </div>
                <p className="text-xs text-text-muted">{models.length} modele(s) disponible(s)</p>
              </div>
            )}
            {!sessionId && (
              <p className="text-xs text-warning">
                Aucune session active. Lancez d&apos;abord un entrainement ou chargez un fichier.
              </p>
            )}
          </div>
        )}

        {modelSource === "upload" && (
          <div className="space-y-3">
            <p className="text-xs text-text-muted">
              Selectionnez un dossier contenant un ou plusieurs sous-dossiers de modeles.
              Chaque sous-dossier doit contenir NNarchitecture.json, NNweights.weights.h5 et NNnormCoefficients.json.
            </p>
            <input
              ref={folderInputRef}
              type="file"
              webkitdirectory=""
              directory=""
              multiple
              className="hidden"
              onChange={handleFolderSelect}
            />
            {!folderName ? (
              <button
                type="button"
                onClick={() => folderInputRef.current?.click()}
                disabled={!sessionId || uploading}
                className="w-full flex flex-col items-center justify-center gap-2 px-6 py-8 rounded-md border border-dashed border-border hover:border-border-strong bg-bg-elevated transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <div className="w-10 h-10 rounded-md bg-accent-subtle flex items-center justify-center text-accent">
                  <FolderOpen size={20} aria-hidden="true" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium text-text">Parcourir un dossier</p>
                  <p className="text-xs text-text-muted mt-1">
                    Selectionnez le dossier contenant vos modeles entraines
                  </p>
                </div>
              </button>
            ) : (
              <div className="flex items-center gap-3 p-3 rounded border border-border bg-bg-elevated">
                <div className="w-9 h-9 rounded bg-accent-subtle flex items-center justify-center text-accent shrink-0">
                  <FolderOpen size={16} aria-hidden="true" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-text truncate">{folderName}</p>
                  <p className="text-xs text-text-muted mt-0.5 font-mono tabular-nums">
                    {folderFileCount} fichier(s) uploade(s)
                  </p>
                </div>
                <Button variant="ghost" size="sm" onClick={clearFolder}>
                  Effacer
                </Button>
              </div>
            )}
            {!sessionId && (
              <p className="text-xs text-warning">
                Chargez d&apos;abord un fichier pour activer l&apos;upload de modeles.
              </p>
            )}
            {uploading && (
              <div className="flex items-center gap-2 text-xs text-text-muted">
                <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                <span>Upload et detection des modeles en cours...</span>
              </div>
            )}
            {models.length > 0 && modelSource === "upload" && (
              <div className="space-y-1.5">
                <div className="relative">
                  <select
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                    className="w-full appearance-none rounded border border-border bg-bg-elevated px-3 h-9 pr-9 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent cursor-pointer font-mono"
                  >
                    {models.map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.name} {m.has_weights ? "" : "(poids manquants)"}
                      </option>
                    ))}
                  </select>
                  <ChevronDown
                    size={14}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-text-subtle pointer-events-none"
                    aria-hidden="true"
                  />
                </div>
                <p className="text-xs text-success">
                  {models.length} modele(s) detectes dans le dossier
                </p>
              </div>
            )}
          </div>
        )}
      </Card>

      {/* 3. Column mapping */}
      {requiredCols.length > 0 && fileColumns.length > 0 && (
        <Card>
          <div className="flex items-center gap-2 mb-4">
            <ArrowRight size={16} className="text-accent" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-text">
              3. Mapping des colonnes
              <span className={`ml-2 text-xs font-normal ${allMapped ? "text-success" : "text-warning"}`}>
                ({requiredCols.length - unmappedCount}/{requiredCols.length} mappees)
              </span>
            </h3>
          </div>
          <p className="text-xs text-text-muted mb-3">
            Le modele necessite ces colonnes. Associez chacune a une colonne de votre fichier.
          </p>
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto pr-1">
            {requiredCols.map((col) => (
              <div key={col} className="flex items-center gap-3">
                <span
                  className={`text-xs font-mono w-[280px] shrink-0 truncate ${
                    colMapping[col] ? "text-text" : "text-danger"
                  }`}
                >
                  {col}
                </span>
                <span className="text-text-subtle text-xs">&rarr;</span>
                <select
                  value={colMapping[col] ?? ""}
                  onChange={(e) =>
                    setColMapping((prev) => ({ ...prev, [col]: e.target.value }))
                  }
                  className={`flex-1 rounded border px-2 h-8 text-xs bg-bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent cursor-pointer ${
                    colMapping[col]
                      ? "border-border text-text"
                      : "border-danger/40 text-danger"
                  }`}
                >
                  <option value="">-- Non mappe --</option>
                  {fileColumns.map((fc) => (
                    <option key={fc} value={fc}>
                      {fc}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          {unmappedCount > 0 && (
            <p className="text-xs text-warning mt-3">
              {unmappedCount} colonne(s) non mappee(s) — l&apos;evaluation ne pourra pas demarrer.
            </p>
          )}
        </Card>
      )}

      {/* 4. Run */}
      <div className="flex justify-center">
        <Button
          variant="primary"
          size="lg"
          icon={running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
          onClick={handleRun}
          disabled={running || !validationFile || !selectedModel || !allMapped}
        >
          {running ? copy.runBtnBusy : copy.runBtnIdle}
        </Button>
      </div>

      {/* 5. Metrics */}
      {metrics && (
        <section aria-live="polite" aria-atomic="true" className="space-y-3">
          <div className="flex items-center gap-2">
            <BarChart3 size={16} className="text-accent" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-text">
              Metriques — <span className="text-accent font-mono">{selectedModel}</span>
            </h3>
          </div>
          <div
            ref={metricsGridRef}
            className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3"
          >
            <StatCard
              label="MAE"
              value={metrics.mae.toFixed(2)}
              icon={<Activity size={16} />}
              tween={{
                to: metrics.mae,
                format: (n) => n.toFixed(2),
                key: `mae-${selectedModel}`,
              }}
            />
            <StatCard
              label="RMSE"
              value={metrics.rmse.toFixed(2)}
              icon={<Target size={16} />}
              tween={{
                to: metrics.rmse,
                format: (n) => n.toFixed(2),
                key: `rmse-${selectedModel}`,
              }}
            />
            <StatCard
              label="R²"
              value={metrics.r_squared.toFixed(4)}
              icon={<BarChart3 size={16} />}
              trend={metrics.r_squared > 0.95 ? "up" : metrics.r_squared > 0.85 ? "neutral" : "down"}
              tween={{
                to: metrics.r_squared,
                format: (n) => n.toFixed(4),
                key: `r2-${selectedModel}`,
              }}
            />
            <StatCard
              label="GEH < 5%"
              value={`${metrics.geh_pct_below_5.toFixed(1)}%`}
              icon={<FileCheck size={16} />}
              trend={metrics.geh_pct_below_5 > 85 ? "up" : "down"}
              tween={{
                to: metrics.geh_pct_below_5,
                format: (n) => `${n.toFixed(1)}%`,
                key: `geh-${selectedModel}`,
              }}
            />
            <StatCard
              label="Echantillons"
              value={metrics.n_samples.toString()}
              tween={{
                to: metrics.n_samples,
                format: (n) => Math.round(n).toString(),
                key: `n-${selectedModel}`,
              }}
            />
          </div>
        </section>
      )}

      {/* 6. HTML report */}
      {reportHtml && (
        <Card className="!p-0 overflow-hidden">
          <div className="flex items-center justify-between p-4 border-b border-border">
            <div className="flex items-center gap-2">
              <FileCheck size={16} className="text-accent" aria-hidden="true" />
              <h3 className="text-sm font-semibold text-text">{copy.reportTitle}</h3>
            </div>
            <span className="text-xs text-text-muted font-mono">{selectedModel}</span>
          </div>
          <iframe
            ref={iframeRef}
            srcDoc={reportHtml}
            className="w-full border-0 bg-white"
            style={{ height: "1200px" }}
            title={copy.reportTitle}
            sandbox="allow-scripts allow-same-origin"
          />
        </Card>
      )}

      {/* 7. Downloads */}
      {(reportBlob || metrics) && (
        <div className="flex flex-wrap gap-2 justify-center">
          {reportBlob && (
            <Button variant="secondary" size="sm" icon={<Download size={14} />} onClick={downloadReport}>
              Telecharger le rapport HTML
            </Button>
          )}
          <Button variant="secondary" size="sm" icon={<Download size={14} />} onClick={downloadModelZip}>
            Telecharger le modele (ZIP)
          </Button>
        </div>
      )}
    </div>
  );
}
