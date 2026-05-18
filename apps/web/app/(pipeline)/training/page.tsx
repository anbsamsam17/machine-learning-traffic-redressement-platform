"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { toast } from "sonner";
import {
  Play,
  Square,
  BarChart3,
  Activity,
  Clock,
  Cpu,
  ScrollText,
  ChevronRight,
} from "lucide-react";
import { GlowCard as Card } from "@/components/ui/glow-card";
import { Button } from "@/components/ui/button";
import { StatCard } from "@/components/ui/stat-card";
import { useAppStore } from "@/lib/store";
import { apiClient } from "@/lib/api";
import { apiUrl } from "@/lib/api-url";
import type { TrainingStartResponse, TrainingStatus } from "@/lib/types/api";

import { Skeleton } from "@/components/ui/skeleton";

const LossChart = dynamic(() => import("@/components/charts/loss-chart").then((m) => m.LossChart), {
  ssr: false,
  loading: () => <Skeleton className="h-[220px] w-full" aria-label="Chargement du graphique" />,
});

interface LossPoint {
  epoch: number;
  loss: number;
  val_loss: number;
}

interface LogEntry {
  time: string;
  message: string;
  type: "info" | "success" | "error" | "epoch";
}

export default function TrainingPage() {
  const router = useRouter();
  const { sessionId, taskId, setTaskId, nextStep, mode, outputDir, setOutputDir, trainingConfig } =
    useAppStore();
  const [localOutputDir, setLocalOutputDir] = useState(outputDir ?? "");

  const [status, setStatus] = useState<
    "idle" | "starting" | "running" | "completed" | "failed"
  >("idle");
  const [currentEpoch, setCurrentEpoch] = useState(0);
  const [totalEpochs, setTotalEpochs] = useState(0);
  const [currentModel, setCurrentModel] = useState(0);
  const [totalModels, setTotalModels] = useState(1);
  const [bestLoss, setBestLoss] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [lossData, setLossData] = useState<LossPoint[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [modelName, setModelName] = useState<string>("");

  const logsEndRef = useRef<HTMLDivElement>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const startTimeRef = useRef<number>(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const prevModelIndexRef = useRef<number>(-1);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [logs]);

  useEffect(() => {
    if (status === "running") {
      startTimeRef.current = Date.now();
      timerRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
      }, 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [status]);

  const addLog = useCallback(
    (message: string, type: LogEntry["type"] = "info") => {
      const now = new Date();
      const time = `${now.getHours().toString().padStart(2, "0")}:${now
        .getMinutes()
        .toString()
        .padStart(2, "0")}:${now.getSeconds().toString().padStart(2, "0")}`;
      setLogs((prev) => [...prev, { time, message, type }]);
    },
    []
  );

  const startPolling = useCallback(
    (tid: string) => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      let backoffMs = 1000;
      const tick = async () => {
        try {
          const data = await apiClient.get<TrainingStatus>(
            `/api/training/status/${tid}`,
            { signal: ctrl.signal, timeoutMs: 15_000 }
          );
          backoffMs = 1000; // reset backoff on success

          setCurrentEpoch(data.current_epoch);
          setTotalEpochs(data.total_epochs);
          if (data.current_model !== undefined) setCurrentModel(data.current_model);
          if (data.total_models !== undefined) setTotalModels(data.total_models);
          if (data.best_val_loss !== null && data.best_val_loss !== undefined) {
            setBestLoss(data.best_val_loss);
          }

          const incomingModelIndex = data.current_model ?? 0;
          const incomingModelName =
            data.current_model_name || `Modele ${incomingModelIndex + 1}`;
          setModelName(incomingModelName);

          if (
            prevModelIndexRef.current !== -1 &&
            incomingModelIndex !== prevModelIndexRef.current
          ) {
            addLog(`[Nouveau modele] ${incomingModelName}`, "info");
            setLossData([]);
          }
          prevModelIndexRef.current = incomingModelIndex;

          if (data.loss !== null && data.val_loss !== null && data.current_epoch > 0) {
            setLossData((prev) => {
              if (prev.length > 0 && prev[prev.length - 1].epoch === data.current_epoch) {
                return prev;
              }
              return [
                ...prev,
                {
                  epoch: data.current_epoch,
                  loss: data.loss as number,
                  val_loss: data.val_loss as number,
                },
              ];
            });
            if (data.current_epoch % 50 === 0 || data.current_epoch === data.total_epochs) {
              addLog(
                `[${incomingModelName}] Epoch ${data.current_epoch}/${data.total_epochs} — loss: ${(data.loss as number).toFixed(4)} | val_loss: ${(data.val_loss as number).toFixed(4)}`,
                "epoch"
              );
            }
          }

          if (data.status === "completed") {
            setStatus("completed");
            addLog("Entrainement termine avec succes !", "success");
            if (outputDir) addLog(`Modeles sauvegardes dans : ${outputDir}`, "success");
            const lossStr =
              data.best_val_loss != null ? data.best_val_loss.toFixed(6) : "N/A";
            toast.success(
              `Entrainement termine — ${data.total_models ?? totalModels} modele(s), meilleure loss: ${lossStr}`
            );
            return; // stop loop
          }

          if (data.status === "failed") {
            setStatus("failed");
            setErrorMsg(data.error || "Erreur inconnue");
            addLog(`ERREUR : ${data.error}`, "error");
            toast.error("Entrainement echoue");
            return;
          }
        } catch (err) {
          if (ctrl.signal.aborted) return;
          // Exponential backoff up to 30 s on network blips
          backoffMs = Math.min(backoffMs * 2, 30_000);
        }
        if (!ctrl.signal.aborted) {
          pollingRef.current = setTimeout(tick, backoffMs);
        }
      };
      tick();
    },
    [addLog, outputDir, totalModels]
  );

  // Resume polling if we have a taskId on mount
  useEffect(() => {
    if (!taskId || status !== "idle") return;
    apiClient
      .get<TrainingStatus>(`/api/training/status/${taskId}`)
      .then((data) => {
        if (data.status === "running" || data.status === "pending") {
          setStatus("running");
          setTotalEpochs(data.total_epochs);
          startPolling(taskId);
        } else if (data.status === "completed") {
          setStatus("completed");
          setCurrentEpoch(data.total_epochs);
          setTotalEpochs(data.total_epochs);
        }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearTimeout(pollingRef.current);
      abortRef.current?.abort();
    };
  }, []);

  async function handleStartTraining() {
    if (!sessionId) {
      toast.error("Pas de session active. Retournez aux etapes precedentes.");
      return;
    }
    const dir = localOutputDir.trim();
    if (dir) setOutputDir(dir);

    setStatus("starting");
    setLossData([]);
    setLogs([]);
    setBestLoss(null);
    setCurrentEpoch(0);
    setErrorMsg(null);
    addLog("Lancement de l'entrainement...", "info");

    try {
      if (taskId) {
        addLog(`Reprise de la tache ${taskId}`, "info");
        setStatus("running");
        startPolling(taskId);
        return;
      }

      const storedConfig = trainingConfig ?? useAppStore.getState().trainingConfig;
      if (!storedConfig) {
        addLog(
          "ATTENTION : Aucune configuration trouvee. Retournez a l'etape Configuration.",
          "error"
        );
        toast.error("Configuration manquante. Retournez a l'etape precedente.");
        setStatus("idle");
        return;
      }

      addLog(
        `Dossier de sortie : ${dir || "(workspace serveur — automatique)"}`,
        "info"
      );
      addLog(
        `Max epochs (config) : ${storedConfig.max_epochs ?? "defaut backend"}`,
        "info"
      );
      addLog("Import de TensorFlow et preparation des donnees...", "info");

      const payload: Record<string, unknown> = {
        ...storedConfig,
        session_id: sessionId,
        output_dir: dir || null,
      };

      const arr = (k: string) =>
        Array.isArray(payload[k]) ? (payload[k] as unknown[]).length : 1;
      const hyperCombos =
        arr("activations") *
        arr("learning_rates") *
        arr("min_nb_epochs_list") *
        arr("losses") *
        arr("dropouts") *
        arr("neurons_factors_list") *
        arr("batch_sizes");
      addLog(`Hyperparametres : ${hyperCombos} combinaisons`, "info");

      const data = await apiClient.post<TrainingStartResponse>(
        "/api/training/start",
        payload,
        { timeoutMs: 60_000 }
      );
      const newTaskId = data.task_id;
      setTaskId(newTaskId);
      if (data.total_combinations) setTotalModels(data.total_combinations);
      if (data.output_dir) setOutputDir(data.output_dir);

      addLog(
        `Tache creee : ${newTaskId} — ${data.total_combinations ?? "?"} combinaisons totales`,
        "success"
      );
      addLog("Entrainement en cours...", "info");
      setStatus("running");
      startPolling(newTaskId);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Erreur inconnue";
      setStatus("failed");
      setErrorMsg(message);
      addLog(`ERREUR : ${message}`, "error");
      toast.error(`Echec : ${message}`);
    }
  }

  async function handleCancel() {
    if (!taskId) return;
    try {
      await apiClient.post(`/api/training/cancel/${taskId}`, undefined);
      addLog("Annulation demandee...", "info");
      toast.info("Annulation en cours");
    } catch {
      toast.error("Impossible d'annuler");
    }
  }

  function goToEvaluation() {
    nextStep();
    router.push("/evaluation");
  }

  const overallProgress =
    totalEpochs > 0 ? (currentEpoch / totalEpochs) * 100 : 0;

  const logTypeColors: Record<string, string> = {
    info: "text-text-muted",
    success: "text-success",
    error: "text-danger",
    epoch: "text-info",
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1.5">
          <h2 className="text-2xl font-semibold text-text">
            Entrainement {mode === "pl" ? "PL" : "TV"}
          </h2>
          <p className="text-sm text-text-muted">
            Entrainement grid search des modeles{" "}
            {mode === "pl" ? "Poids Lourds" : "Tous Vehicules"}. Suivez la progression en temps reel.
          </p>
        </div>

        <div className="flex gap-2 shrink-0">
          {status === "idle" && (
            <Button onClick={handleStartTraining} icon={<Play size={14} />} variant="primary" size="sm">
              Lancer l&apos;entrainement
            </Button>
          )}
          {status === "starting" && (
            <Button disabled variant="primary" size="sm">
              Demarrage...
            </Button>
          )}
          {status === "running" && (
            <Button variant="secondary" size="sm" onClick={handleCancel} icon={<Square size={14} />}>
              Annuler
            </Button>
          )}
          {status === "completed" && (
            <Button onClick={goToEvaluation} icon={<ChevronRight size={14} />} variant="primary" size="sm">
              Evaluation
            </Button>
          )}
        </div>
      </div>

      {/* Output dir */}
      {status === "idle" && (
        <Card>
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-md bg-accent-subtle flex items-center justify-center text-accent shrink-0">
              <BarChart3 size={16} aria-hidden="true" />
            </div>
            <div className="flex-1 space-y-2">
              <label className="text-sm font-medium text-text">
                Nom de la serie de modeles
                <span className="text-xs text-text-muted font-normal ml-2">(optionnel)</span>
              </label>
              <p className="text-xs text-text-muted">
                Etiquette affichee et utilisee pour nommer le fichier zip de telechargement.
              </p>
              <input
                type="text"
                value={localOutputDir}
                onChange={(e) => setLocalOutputDir(e.target.value)}
                placeholder="ex. MDL_Bordeaux"
                className="w-full px-3 h-9 rounded text-sm bg-bg-elevated border border-border text-text placeholder:text-text-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </div>
          </div>
        </Card>
      )}
      {status !== "idle" && outputDir && (
        <div className="text-xs text-text-muted px-1">
          Dossier de sortie : <span className="text-accent font-mono">{outputDir}</span>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatCard
          label="Modele en cours"
          value={`${currentModel + 1} / ${totalModels}`}
          icon={<Cpu size={16} />}
        />
        <StatCard
          label="Meilleure val_loss"
          value={bestLoss !== null ? bestLoss.toFixed(6) : "--"}
          icon={<Activity size={16} />}
          trend={bestLoss !== null ? "down" : undefined}
        />
        <StatCard
          label="Temps ecoule"
          value={`${Math.floor(elapsed / 60)}m ${elapsed % 60}s`}
          icon={<Clock size={16} />}
        />
      </div>

      {/* Progress */}
      <Card>
        <div className="space-y-3" aria-live="polite" aria-atomic="true">
          <div className="flex items-center justify-between text-xs">
            <span className="text-text-muted font-mono tabular-nums">
              Epoch {currentEpoch} / {totalEpochs || "?"}
              {modelName ? <span className="ml-2 text-text-subtle">{modelName}</span> : null}
            </span>
            <span className="text-accent font-medium font-mono tabular-nums">
              {Math.round(overallProgress)}%
            </span>
          </div>
          <div
            className="h-1.5 rounded-full bg-bg-subtle overflow-hidden"
            role="progressbar"
            aria-valuenow={Math.round(overallProgress)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              style={{ width: `${overallProgress}%`, transition: "width .3s ease-out" }}
              className={status === "completed" ? "h-full bg-success" : "h-full bg-accent"}
            />
          </div>

          {status === "completed" && (
            <div className="text-center py-3 rounded-md bg-success/10 border border-success/30 space-y-2">
              <p className="text-sm font-medium text-success">Entrainement termine</p>
              <p className="text-xs text-text-muted font-mono tabular-nums">
                {currentEpoch} epochs en {Math.floor(elapsed / 60)}m {elapsed % 60}s
              </p>
              {sessionId && (
                <a
                  href={apiUrl(`/api/export/models-all/${sessionId}`)}
                  download
                  className="inline-flex items-center gap-2 px-3 h-7 rounded bg-success text-white text-xs font-medium hover:bg-success/90 transition-colors"
                >
                  Telecharger tous les modeles (.zip)
                </a>
              )}
            </div>
          )}
          {status === "failed" && (
            <div className="text-center py-3 rounded-md bg-danger/10 border border-danger/30">
              <p className="text-sm font-medium text-danger">Entrainement echoue</p>
              <p className="text-xs text-danger/80 mt-1">{errorMsg}</p>
            </div>
          )}
        </div>
      </Card>

      {/* Loss chart */}
      {lossData.length > 1 && (
        <Card>
          <p className="text-xs text-text-muted mb-3 flex items-center gap-2">
            <BarChart3 size={14} aria-hidden="true" /> Courbe de loss
          </p>
          <LossChart data={lossData} />
        </Card>
      )}

      {/* Logs */}
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <ScrollText size={14} className="text-text-muted" aria-hidden="true" />
          <p className="text-xs text-text-muted font-medium">Journal d&apos;entrainement</p>
          <span className="text-[10px] text-text-subtle ml-auto font-mono tabular-nums">
            {logs.length} entrees
          </span>
        </div>
        <div
          className="bg-bg rounded-md border border-border p-3 max-h-[300px] overflow-y-auto font-mono text-[11px] space-y-0.5"
          role="log"
          aria-live="polite"
        >
          {logs.length === 0 ? (
            <p className="text-text-subtle text-center py-4">
              Les logs apparaitront ici une fois l&apos;entrainement lance.
            </p>
          ) : (
            logs.map((log, i) => (
              <div key={i} className="flex gap-2">
                <span className="text-text-subtle shrink-0">[{log.time}]</span>
                <span className={logTypeColors[log.type] ?? "text-text-muted"}>
                  {log.message}
                </span>
              </div>
            ))
          )}
          <div ref={logsEndRef} />
        </div>
      </Card>
    </div>
  );
}
