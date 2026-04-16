"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
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
} from "lucide-react";
import { toast } from "sonner";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";
import { StatCard } from "@/components/ui/stat-card";
import { DropZone } from "@/components/upload/drop-zone";
import { useAppStore } from "@/lib/store";
import { fetchJSON } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

interface EvalRunResponse {
  session_id: string;
  model_name: string;
  metrics: EvalMetrics;
  report_url: string;
}

/* ---------- Page ---------- */

export default function EvaluationPage() {
  const { mode, sessionId, outputDir } = useAppStore();

  // --- State ---
  const [validationFile, setValidationFile] = useState<File | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [loadingModels, setLoadingModels] = useState(false);
  const [running, setRunning] = useState(false);
  const [metrics, setMetrics] = useState<EvalMetrics | null>(null);
  const [reportHtml, setReportHtml] = useState<string | null>(null);
  const [reportBlob, setReportBlob] = useState<Blob | null>(null);
  const [modelDir, setModelDir] = useState(outputDir ?? "");
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // --- Load models from output_dir ---
  const loadModels = useCallback(async (dir: string) => {
    if (!dir) return;
    setLoadingModels(true);
    try {
      const data = await fetchJSON<{ models: ModelInfo[] }>(
        `/api/models/list?dir=${encodeURIComponent(dir)}`
      );
      setModels(data.models);
      if (data.models.length > 0 && !selectedModel) {
        setSelectedModel(data.models[0].name);
      }
      if (data.models.length === 0) {
        toast.info("Aucun modele trouve dans ce dossier.");
      }
    } catch (err) {
      console.error(err);
      toast.error("Impossible de lister les modeles.");
    } finally {
      setLoadingModels(false);
    }
  }, [selectedModel]);

  // Auto-load on mount if outputDir is set
  useEffect(() => {
    if (outputDir) {
      setModelDir(outputDir);
      loadModels(outputDir);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outputDir]);

  // --- Run evaluation ---
  const handleRun = useCallback(async () => {
    if (!validationFile) {
      toast.error("Veuillez selectionner un fichier de validation.");
      return;
    }
    if (!selectedModel) {
      toast.error("Veuillez selectionner un modele.");
      return;
    }
    if (!sessionId) {
      toast.error("Aucune session active. Retournez a l'etape Donnees.");
      return;
    }

    setRunning(true);
    setMetrics(null);
    setReportHtml(null);
    setReportBlob(null);

    try {
      // 1. Upload validation file
      const form = new FormData();
      form.append("file", validationFile);
      form.append("session_id", sessionId);

      const uploadRes = await fetch(`${API_BASE}/api/evaluation/upload-validation`, {
        method: "POST",
        body: form,
      });
      if (!uploadRes.ok) {
        const errText = await uploadRes.text();
        throw new Error(`Upload echoue: ${errText}`);
      }

      // 2. Run evaluation
      const evalRes = await fetchJSON<EvalRunResponse>("/api/evaluation/run", {
        method: "POST",
        body: JSON.stringify({
          session_id: sessionId,
          model_name: selectedModel,
          model_dir: modelDir,
        }),
      });

      setMetrics(evalRes.metrics);

      // 3. Fetch report HTML
      const reportRes = await fetch(
        `${API_BASE}/api/evaluation/report/${sessionId}`
      );
      if (reportRes.ok) {
        const reportData = await reportRes.json();
        setReportHtml(reportData.report_html);
        setReportBlob(
          new Blob([reportData.report_html], { type: "text/html" })
        );
      }

      toast.success(`Evaluation terminee pour ${selectedModel}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Erreur: ${msg}`);
      console.error(err);
    } finally {
      setRunning(false);
    }
  }, [validationFile, selectedModel, sessionId, modelDir]);

  // --- Download helpers ---
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
    if (!sessionId || !selectedModel) return;
    try {
      const res = await fetch(
        `${API_BASE}/api/evaluation/download-model?session_id=${sessionId}&model_name=${encodeURIComponent(selectedModel)}&model_dir=${encodeURIComponent(modelDir)}`
      );
      if (!res.ok) throw new Error("Telechargement echoue");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${selectedModel}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error("Impossible de telecharger le modele.");
    }
  }, [sessionId, selectedModel, modelDir]);

  return (
    <div className="space-y-6">
      {/* --- Header --- */}
      <div className="space-y-2">
        <GradientText as="h2" className="text-2xl">
          Evaluation
        </GradientText>
        <p className="text-sm text-muted">
          Evaluez les modeles {mode === "pl" ? "PL" : "TV"} entraines sur un
          fichier de validation, generez un rapport HTML interactif et
          telechargez les resultats.
        </p>
      </div>

      {/* --- Section 1: Fichier de validation --- */}
      <GlowCard>
        <div className="flex items-center gap-2 mb-4">
          <Upload size={18} className="text-accent" />
          <h3 className="text-sm font-semibold text-foreground">
            Fichier de validation
          </h3>
        </div>
        <DropZone
          file={validationFile}
          onFile={setValidationFile}
          onClear={() => setValidationFile(null)}
          accept={{
            "application/json": [".geojson", ".json"],
            "text/csv": [".csv"],
          }}
          label="Deposez votre fichier de validation ici"
          description="GeoJSON ou CSV avec donnees de comptage"
        />
      </GlowCard>

      {/* --- Section 2: Selection du modele --- */}
      <GlowCard glowColor="cyan">
        <div className="flex items-center gap-2 mb-4">
          <FolderOpen size={18} className="text-cyan-400" />
          <h3 className="text-sm font-semibold text-foreground">
            Selection du modele
          </h3>
        </div>

        {/* Model directory input */}
        <div className="space-y-3">
          <div className="flex gap-2">
            <input
              type="text"
              value={modelDir}
              onChange={(e) => setModelDir(e.target.value)}
              placeholder="Dossier de sortie des modeles (output_dir)"
              className="flex-1 rounded-xl border border-border bg-surface px-4 py-2.5 text-sm text-foreground placeholder:text-muted focus:outline-none focus:border-accent/60 transition-colors"
            />
            <NeonButton
              variant="secondary"
              onClick={() => loadModels(modelDir)}
              disabled={!modelDir || loadingModels}
              className="text-xs whitespace-nowrap"
            >
              {loadingModels ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                "Charger"
              )}
            </NeonButton>
          </div>

          {/* Model dropdown */}
          {models.length > 0 && (
            <div className="relative">
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full appearance-none rounded-xl border border-border bg-surface px-4 py-2.5 pr-10 text-sm text-foreground focus:outline-none focus:border-accent/60 transition-colors cursor-pointer"
              >
                {models.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </select>
              <ChevronDown
                size={16}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted pointer-events-none"
              />
            </div>
          )}

          {models.length > 0 && (
            <p className="text-xs text-muted">
              {models.length} modele(s) disponible(s) dans le dossier
            </p>
          )}
        </div>
      </GlowCard>

      {/* --- Section 3: Lancer l'evaluation --- */}
      <div className="flex justify-center">
        <NeonButton
          variant="primary"
          icon={
            running ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <Play size={18} />
            )
          }
          onClick={handleRun}
          disabled={running || !validationFile || !selectedModel}
          className="px-10 py-4 text-base"
        >
          {running ? "Evaluation en cours..." : "Lancer l'evaluation"}
        </NeonButton>
      </div>

      {/* --- Section 4: Metriques --- */}
      <AnimatePresence>
        {metrics && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="space-y-4"
          >
            <div className="flex items-center gap-2">
              <BarChart3 size={18} className="text-accent" />
              <h3 className="text-sm font-semibold text-foreground">
                Metriques d'evaluation &mdash;{" "}
                <span className="text-accent">{selectedModel}</span>
              </h3>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
              <StatCard
                label="MAE"
                value={metrics.mae.toFixed(2)}
                icon={<Activity size={18} />}
              />
              <StatCard
                label="RMSE"
                value={metrics.rmse.toFixed(2)}
                icon={<Target size={18} />}
              />
              <StatCard
                label="R²"
                value={metrics.r_squared.toFixed(4)}
                icon={<BarChart3 size={18} />}
                trend={metrics.r_squared > 0.95 ? "up" : metrics.r_squared > 0.85 ? "neutral" : "down"}
              />
              <StatCard
                label="GEH < 5%"
                value={`${metrics.geh_pct_below_5.toFixed(1)}%`}
                icon={<FileCheck size={18} />}
                trend={metrics.geh_pct_below_5 > 85 ? "up" : metrics.geh_pct_below_5 > 70 ? "neutral" : "down"}
              />
              <StatCard
                label="Echantillons"
                value={metrics.n_samples.toString()}
              />
            </div>

            {(metrics.mape !== null || metrics.hd_rmse !== null) && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {metrics.mape !== null && (
                  <StatCard
                    label="MAPE"
                    value={`${metrics.mape.toFixed(1)}%`}
                  />
                )}
                <StatCard
                  label="GEH moyen"
                  value={metrics.geh_mean.toFixed(3)}
                />
                {metrics.hd_rmse !== null && (
                  <StatCard
                    label="RMSE fort trafic"
                    value={metrics.hd_rmse.toFixed(2)}
                  />
                )}
                {metrics.ld_rmse !== null && (
                  <StatCard
                    label="RMSE faible trafic"
                    value={metrics.ld_rmse.toFixed(2)}
                  />
                )}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* --- Section 5: Rapport HTML --- */}
      <AnimatePresence>
        {reportHtml && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="space-y-4"
          >
            <GlowCard glowColor="violet" className="p-0 overflow-hidden">
              <div className="flex items-center justify-between p-4 border-b border-border">
                <div className="flex items-center gap-2">
                  <FileCheck size={18} className="text-violet-400" />
                  <h3 className="text-sm font-semibold text-foreground">
                    Rapport d'evaluation
                  </h3>
                </div>
                <span className="text-xs text-muted">
                  Modele : {selectedModel}
                </span>
              </div>
              <iframe
                ref={iframeRef}
                srcDoc={reportHtml}
                className="w-full border-0 bg-white"
                style={{ height: "800px" }}
                title="Rapport d'evaluation"
                sandbox="allow-same-origin"
              />
            </GlowCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* --- Section 6: Telechargements --- */}
      <AnimatePresence>
        {(reportBlob || metrics) && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="flex flex-wrap gap-3 justify-center"
          >
            {reportBlob && (
              <NeonButton
                variant="secondary"
                icon={<Download size={16} />}
                onClick={downloadReport}
              >
                Telecharger le rapport HTML
              </NeonButton>
            )}
            <NeonButton
              variant="secondary"
              icon={<Download size={16} />}
              onClick={downloadModelZip}
            >
              Telecharger le modele (ZIP)
            </NeonButton>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
