"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
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
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";
import { StatCard } from "@/components/ui/stat-card";
import { useAppStore } from "@/lib/store";

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

  const logsEndRef = useRef<HTMLDivElement>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const startTimeRef = useRef<number>(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  // Auto-scroll logs
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // Timer for elapsed time
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

  // Resume polling if we have a taskId from a previous navigation
  useEffect(() => {
    if (taskId && status === "idle") {
      // Check if task is still running
      fetch(`/api/training/status/${taskId}`)
        .then((r) => r.json())
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
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  const addLog = useCallback(
    (message: string, type: LogEntry["type"] = "info") => {
      const now = new Date();
      const time = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}:${now.getSeconds().toString().padStart(2, "0")}`;
      setLogs((prev) => [...prev, { time, message, type }]);
    },
    []
  );

  function startPolling(tid: string) {
    if (pollingRef.current) clearInterval(pollingRef.current);

    pollingRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/training/status/${tid}`);
        if (!res.ok) return;
        const data = await res.json();

        setCurrentEpoch(data.current_epoch);
        setTotalEpochs(data.total_epochs);
        if (data.current_model !== undefined) setCurrentModel(data.current_model);
        if (data.total_models !== undefined) setTotalModels(data.total_models);
        if (data.best_val_loss !== null && data.best_val_loss !== undefined) setBestLoss(data.best_val_loss);

        if (data.loss !== null && data.val_loss !== null && data.current_epoch > 0) {
          setLossData((prev) => {
            // Avoid duplicates
            if (prev.length > 0 && prev[prev.length - 1].epoch === data.current_epoch)
              return prev;
            return [
              ...prev,
              {
                epoch: data.current_epoch,
                loss: data.loss,
                val_loss: data.val_loss,
              },
            ];
          });

          if (bestLoss === null || data.val_loss < bestLoss) {
            setBestLoss(data.val_loss);
          }

          if (data.current_epoch % 50 === 0 || data.current_epoch === data.total_epochs) {
            const modelLabel = data.current_model_name || `Modele ${(data.current_model ?? 0) + 1}`;
            addLog(
              `[${modelLabel}] Epoch ${data.current_epoch}/${data.total_epochs} — loss: ${data.loss.toFixed(4)} | val_loss: ${data.val_loss.toFixed(4)}`,
              "epoch"
            );
          }
        }

        if (data.status === "completed") {
          setStatus("completed");
          addLog("Entrainement termine avec succes !", "success");
          if (outputDir) {
            addLog(`Modeles sauvegardes dans : ${outputDir}`, "success");
          }
          toast.success("Entrainement termine !");
          if (pollingRef.current) clearInterval(pollingRef.current);
        }

        if (data.status === "failed") {
          setStatus("failed");
          setErrorMsg(data.error || "Erreur inconnue");
          addLog(`ERREUR : ${data.error}`, "error");
          toast.error("Entrainement echoue");
          if (pollingRef.current) clearInterval(pollingRef.current);
        }
      } catch {
        // Network error, keep polling
      }
    }, 1000);
  }

  async function handleStartTraining() {
    if (!sessionId) {
      toast.error("Pas de session active. Retournez aux etapes precedentes.");
      return;
    }
    if (!localOutputDir.trim()) {
      toast.error("Veuillez indiquer un dossier de sortie pour les modeles.");
      return;
    }
    // Save output dir to store
    setOutputDir(localOutputDir.trim());

    setStatus("starting");
    setLossData([]);
    setLogs([]);
    setBestLoss(null);
    setCurrentEpoch(0);
    setErrorMsg(null);
    addLog("Lancement de l'entrainement...", "info");

    try {
      // The config was already sent to the backend in the config page.
      // But we need to start the training with the config from the session.
      // The config page already started the training via POST /api/training/start
      // and stored the task_id. Let's check if we have a task_id.
      if (taskId) {
        addLog(`Reprise de la tache ${taskId}`, "info");
        setStatus("running");
        startPolling(taskId);
        return;
      }

      // If no taskId, start a new training with the config from the config page
      addLog("Import de TensorFlow et preparation des donnees...", "info");

      const payload = {
        session_id: sessionId,
        output_dir: localOutputDir.trim(),
        ...(trainingConfig ?? {}),
      };

      const res = await fetch("/api/training/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Erreur ${res.status}`);
      }

      const data = await res.json();
      const newTaskId = data.task_id;
      setTaskId(newTaskId);

      addLog(`Tache creee : ${newTaskId}`, "info");
      addLog("Entrainement en cours...", "info");
      setStatus("running");
      startPolling(newTaskId);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Erreur inconnue";
      setStatus("failed");
      setErrorMsg(message);
      addLog(`ERREUR : ${message}`, "error");
      toast.error(`Echec : ${message}`);
    }
  }

  async function handleCancel() {
    if (!taskId) return;
    try {
      await fetch(`/api/training/cancel/${taskId}`, { method: "POST" });
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
    info: "text-slate-400",
    success: "text-emerald-400",
    error: "text-red-400",
    epoch: "text-cyan-300",
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <GradientText as="h2" className="text-2xl">
            Entrainement {mode === "pl" ? "PL" : "TV"}
          </GradientText>
          <p className="text-sm text-muted">
            Entrainement grid search des modeles{" "}
            {mode === "pl" ? "Poids Lourds" : "Tous Vehicules"}. Suivez la
            progression en temps reel.
          </p>
        </div>

        {/* Action buttons */}
        <div className="flex gap-3">
          {status === "idle" && (
            <NeonButton onClick={handleStartTraining} icon={<Play size={16} />}>
              Lancer l&apos;entrainement
            </NeonButton>
          )}
          {status === "starting" && (
            <NeonButton disabled>Demarrage...</NeonButton>
          )}
          {status === "running" && (
            <NeonButton
              variant="secondary"
              onClick={handleCancel}
              icon={<Square size={16} />}
            >
              Annuler
            </NeonButton>
          )}
          {status === "completed" && (
            <NeonButton
              onClick={goToEvaluation}
              icon={<ChevronRight size={16} />}
            >
              Evaluation
            </NeonButton>
          )}
        </div>
      </div>

      {/* Output dir - required before launching */}
      {status === "idle" && (
        <GlowCard>
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center text-indigo-400 shrink-0">
              <BarChart3 size={20} />
            </div>
            <div className="flex-1 space-y-2">
              <label className="text-sm font-medium text-slate-200">
                Dossier de sortie des modeles *
              </label>
              <p className="text-xs text-slate-400">
                Tous les modeles du grid search seront sauvegardes dans ce
                dossier (un sous-dossier par combinaison).
              </p>
              <input
                type="text"
                value={localOutputDir}
                onChange={(e) => setLocalOutputDir(e.target.value)}
                placeholder={`Ex: C:\\xMDL\\${mode === "pl" ? "PL" : "TV"}\\MonTerritoire`}
                className="w-full px-3 py-2 rounded-lg text-sm bg-slate-900/80 border border-white/[0.08] text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30 transition-colors"
              />
              {!localOutputDir && (
                <p className="text-xs text-amber-400">
                  Veuillez indiquer un dossier avant de lancer l&apos;entrainement.
                </p>
              )}
            </div>
          </div>
        </GlowCard>
      )}
      {status !== "idle" && outputDir && (
        <div className="text-xs text-slate-400 px-1">
          Dossier de sortie : <span className="text-cyan-300">{outputDir}</span>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatCard
          label="Modele en cours"
          value={`${currentModel + 1} / ${totalModels}`}
          icon={<Cpu size={18} />}
        />
        <StatCard
          label="Meilleure val_loss"
          value={bestLoss !== null ? bestLoss.toFixed(6) : "--"}
          icon={<Activity size={18} />}
          trend={bestLoss !== null ? "down" : undefined}
        />
        <StatCard
          label="Temps ecoule"
          value={`${Math.floor(elapsed / 60)}m ${elapsed % 60}s`}
          icon={<Clock size={18} />}
        />
      </div>

      {/* Progress bar */}
      <GlowCard>
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-400">
              Epoch {currentEpoch} / {totalEpochs || "?"}
            </span>
            <span className="text-indigo-400 font-medium">
              {Math.round(overallProgress)}%
            </span>
          </div>
          <div className="h-3 rounded-full bg-slate-800/80 overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${overallProgress}%` }}
              transition={{ duration: 0.5, ease: "easeOut" }}
              className="h-full rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-violet-500"
            />
          </div>

          {/* Status message */}
          <AnimatePresence mode="wait">
            {status === "completed" && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-center py-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20"
              >
                <p className="text-sm font-medium text-emerald-400">
                  Entrainement termine
                </p>
                <p className="text-xs text-slate-400 mt-1">
                  {currentEpoch} epochs en {Math.floor(elapsed / 60)}m{" "}
                  {elapsed % 60}s
                  {outputDir && ` — modeles sauvegardes dans ${outputDir}`}
                </p>
              </motion.div>
            )}
            {status === "failed" && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-center py-3 rounded-lg bg-red-500/10 border border-red-500/20"
              >
                <p className="text-sm font-medium text-red-400">
                  Entrainement echoue
                </p>
                <p className="text-xs text-red-300/70 mt-1">{errorMsg}</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </GlowCard>

      {/* Loss curve */}
      {lossData.length > 1 && (
        <GlowCard>
          <p className="text-xs text-slate-400 mb-3 flex items-center gap-2">
            <BarChart3 size={14} /> Courbe de loss
          </p>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={lossData}>
              <CartesianGrid stroke="rgba(99,102,241,0.08)" />
              <XAxis
                dataKey="epoch"
                tick={{ fontSize: 10, fill: "#94a3b8" }}
                stroke="rgba(99,102,241,0.1)"
              />
              <YAxis
                tick={{ fontSize: 10, fill: "#94a3b8" }}
                stroke="rgba(99,102,241,0.1)"
              />
              <Tooltip
                contentStyle={{
                  background: "#0a0a1a",
                  border: "1px solid rgba(99,102,241,0.2)",
                  borderRadius: 8,
                  fontSize: 11,
                }}
                labelStyle={{ color: "#94a3b8" }}
              />
              <Line
                type="monotone"
                dataKey="loss"
                stroke="#6366f1"
                strokeWidth={2}
                dot={false}
                name="Train Loss"
              />
              <Line
                type="monotone"
                dataKey="val_loss"
                stroke="#06b6d4"
                strokeWidth={2}
                dot={false}
                name="Val Loss"
              />
            </LineChart>
          </ResponsiveContainer>
        </GlowCard>
      )}

      {/* Logs panel */}
      <GlowCard>
        <div className="flex items-center gap-2 mb-3">
          <ScrollText size={14} className="text-slate-400" />
          <p className="text-xs text-slate-400 font-medium">
            Journal d&apos;entrainement
          </p>
          <span className="text-[10px] text-slate-600 ml-auto">
            {logs.length} entrees
          </span>
        </div>
        <div className="bg-slate-950/80 rounded-lg border border-white/[0.04] p-3 max-h-[300px] overflow-y-auto font-mono text-[11px] space-y-0.5">
          {logs.length === 0 ? (
            <p className="text-slate-600 text-center py-4">
              Les logs apparaitront ici une fois l&apos;entrainement lance.
            </p>
          ) : (
            logs.map((log, i) => (
              <div key={i} className="flex gap-2">
                <span className="text-slate-600 shrink-0">[{log.time}]</span>
                <span className={logTypeColors[log.type] ?? "text-slate-400"}>
                  {log.message}
                </span>
              </div>
            ))
          )}
          <div ref={logsEndRef} />
        </div>
      </GlowCard>
    </div>
  );
}
