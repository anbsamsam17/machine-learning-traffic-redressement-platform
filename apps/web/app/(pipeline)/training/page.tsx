"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { apiUrl } from "@/lib/api-url";
import { fetchWithAuth } from "@/lib/auth";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import Link from "next/link";
import {
  Play,
  Square,
  BarChart3,
  Activity,
  Clock,
  Cpu,
  ScrollText,
  ChevronRight,
  Database,
  Settings2,
  ArrowRight,
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
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";
import { StatCard } from "@/components/ui/stat-card";
import { SuccessBanner } from "@/components/ui/success-banner";
import {
  GlowCardPremium,
  MagneticButton,
  NeonBorder,
  RevealOnScroll,
  ShimmerText,
  StatBadge,
} from "@/components/ui";
import { useAppStore } from "@/lib/store";
import { playSuccessDing, spawnConfetti } from "@/lib/success-effects";
import { samNotify, samMood } from "@/lib/sam-fallback";
import { useTrainingCancel } from "@/lib/hooks/use-training-cancel";

interface LossPoint {
  epoch: number;
  loss: number;
  val_loss: number;
}

/** Wrapper visuel autour du panneau "progress + status".
 *  En mode actif (training en cours) : NeonBorder cyan qui pulse.
 *  Sinon : GlowCard premium standard. */
function ProgressBarShell({
  active,
  children,
}: {
  active: boolean;
  children: React.ReactNode;
}) {
  if (active) {
    return (
      <NeonBorder tone="cyan" speed={2.4} thickness={1}>
        <div className="p-5">{children}</div>
      </NeonBorder>
    );
  }
  return <GlowCard>{children}</GlowCard>;
}

interface LogEntry {
  time: string;
  message: string;
  type: "info" | "success" | "error" | "epoch";
}

export default function TrainingPage() {
  const router = useRouter();
  const {
    sessionId,
    taskId,
    setTaskId,
    nextStep,
    mode,
    outputDir,
    setOutputDir,
    trainingConfig,
    mappingValidated,
  } = useAppStore();
  const [localOutputDir, setLocalOutputDir] = useState(outputDir ?? "");

  const [status, setStatus] = useState<
    "idle" | "starting" | "running" | "completed" | "failed" | "cancelling" | "cancelled"
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
  const [showSuccessBanner, setShowSuccessBanner] = useState(false);
  const [successCardPulse, setSuccessCardPulse] = useState(false);

  const logsEndRef = useRef<HTMLDivElement>(null);
  const statsContainerRef = useRef<HTMLDivElement>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const startTimeRef = useRef<number>(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const prevModelIndexRef = useRef<number>(-1);
  // Last logged epoch line per model — prevents duplicate "Epoch X/Y" prints
  // when the status endpoint keeps returning the same final epoch while the
  // backend cleans up between two consecutive runs.
  const lastLoggedEpochRef = useRef<string>("");

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
      fetchWithAuth(apiUrl(`/api/training/status/${taskId}`))
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
        const res = await fetchWithAuth(apiUrl(`/api/training/status/${tid}`));
        if (!res.ok) return;
        const data = await res.json();

        setCurrentEpoch(data.current_epoch);
        setTotalEpochs(data.total_epochs);
        if (data.current_model !== undefined) setCurrentModel(data.current_model);
        if (data.total_models !== undefined) setTotalModels(data.total_models);
        if (data.best_val_loss !== null && data.best_val_loss !== undefined) setBestLoss(data.best_val_loss);

        // Live mood widget (no toast — just background widget)
        const pct =
          data.total_epochs > 0
            ? Math.round((data.current_epoch / data.total_epochs) * 100)
            : 0;
        samMood.set("thinking", `Training: ${pct}% (epoch ${data.current_epoch})`);

        // Track model name and detect model changes
        const incomingModelIndex = data.current_model ?? 0;
        const incomingModelName = data.current_model_name || `Modele ${incomingModelIndex + 1}`;
        setModelName(incomingModelName);

        if (prevModelIndexRef.current !== -1 && incomingModelIndex !== prevModelIndexRef.current) {
          // Model changed — log it and reset loss curve
          addLog(`[Nouveau modele] ${incomingModelName}`, "info");
          setLossData([]);
        }
        prevModelIndexRef.current = incomingModelIndex;

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
            // Dedup: same (model_name, epoch) line never re-emitted. Status endpoint
            // keeps returning final epoch during the inter-model cleanup, which used
            // to spam "Epoch X/X" once per poll for several seconds.
            const epochKey = `${incomingModelName}@${data.current_epoch}`;
            if (lastLoggedEpochRef.current !== epochKey) {
              lastLoggedEpochRef.current = epochKey;
              addLog(
                `[${incomingModelName}] Epoch ${data.current_epoch}/${data.total_epochs} — loss: ${data.loss.toFixed(4)} | val_loss: ${data.val_loss.toFixed(4)}`,
                "epoch"
              );
            }
          }
        }

        if (data.status === "completed") {
          setStatus("completed");
          addLog("Entrainement termine avec succes !", "success");
          if (outputDir) {
            addLog(`Modeles sauvegardes dans : ${outputDir}`, "success");
          }

          // Rich success toast with summary
          const lossStr = data.best_val_loss != null ? data.best_val_loss.toFixed(6) : (bestLoss?.toFixed(6) ?? "N/A");
          toast.success(
            `Entrainement termine — ${data.total_models ?? totalModels} modele(s), meilleure loss: ${lossStr}${outputDir ? ` — ${outputDir}` : ""}`
          );
          samNotify.success("Beau modele ! GEH dans les clous, t'es bon pour livrer.");

          // Success effects: ding + card pulse + banner + confetti
          playSuccessDing();
          setShowSuccessBanner(true);
          setSuccessCardPulse(true);
          setTimeout(() => setSuccessCardPulse(false), 2500);
          spawnConfetti(statsContainerRef.current, 32);

          if (pollingRef.current) clearInterval(pollingRef.current);
        }

        if (data.status === "failed") {
          setStatus("failed");
          const failMsg = data.error || "Erreur inconnue";
          setErrorMsg(failMsg);
          addLog(`ERREUR : ${data.error}`, "error");
          toast.error("Entrainement echoue");
          samNotify.error("Training echoue. Console pour les details.", { title: "Erreur" });
          if (pollingRef.current) clearInterval(pollingRef.current);
        }

        if (data.status === "cancelled") {
          // Backend a confirme l'annulation — bascule l'UI en etat final
          // "Annule" et stoppe le polling principal.
          setStatus("cancelled");
          addLog("Entrainement annule par l'utilisateur.", "info");
          if (pollingRef.current) clearInterval(pollingRef.current);
        }
      } catch {
        // Network error, keep polling
      }
    }, 1000);
  }

  async function handleStartTraining() {
    // Tache 1 : on n'auto-redirige plus l'utilisateur. On informe via toast
    // mais on le laisse sur la page — il peut naviguer via le stepper en
    // haut s'il le souhaite. L'empty-state inline sur la page fournit deja
    // un bouton direct vers l'etape manquante.
    if (!sessionId) {
      toast.error("Pas de session active. Importe un fichier via l'etape Donnees.");
      return;
    }
    if (!mappingValidated) {
      toast.error("Valide d'abord le mapping des colonnes sur l'etape Donnees.");
      return;
    }
    if (!trainingConfig) {
      toast.error("Aucune configuration trouvee. Passe par l'etape Configuration.");
      return;
    }
    const dir = localOutputDir.trim();
    // If dir is provided, save it; otherwise models will be saved on the server workspace
    if (dir) {
      setOutputDir(dir);
    }

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
      const storedConfig = trainingConfig ?? useAppStore.getState().trainingConfig;
      if (!storedConfig) {
        addLog("ATTENTION : Aucune configuration trouvee. Retournez a l'etape Configuration.", "error");
        toast.error("Configuration manquante. Retournez a l'etape precedente.");
        setStatus("idle");
        return;
      }

      const dirValue = localOutputDir.trim();
      addLog(`Dossier de sortie : ${dirValue || "(workspace serveur — automatique)"}`, "info");
      addLog(`Max epochs (config) : ${storedConfig.max_epochs ?? "defaut backend"}`, "info");
      addLog("Import de TensorFlow et preparation des donnees...", "info");

      // Build final payload — spread config then override session_id and output_dir
      // If output_dir is empty, the backend will use WORKSPACE_ROOT/{session_id}/models/
      const payload: Record<string, unknown> = {
        ...storedConfig,
        session_id: sessionId,
        output_dir: dirValue || null,
      };

      // Debug: log payload only in dev. Bug 3 (T3, P0) — evite de fuiter la
      // config training en clair dans la console en production.
      if (process.env.NODE_ENV === "development") {
        console.log("[Training] Payload being sent:", JSON.stringify(payload, null, 2));
      }

      // Log config summary
      const arr = (k: string) => Array.isArray(payload[k]) ? (payload[k] as unknown[]).length : 1;
      const hyperCombos = arr("activations") * arr("learning_rates") * arr("min_nb_epochs_list") * arr("losses") * arr("dropouts") * arr("neurons_factors_list") * arr("batch_sizes");
      const hasGrid = payload.feature_subset_grid === true;
      addLog(`Hyperparametres : ${hyperCombos} combinaisons (${arr("activations")} act × ${arr("learning_rates")} lr × ${arr("min_nb_epochs_list")} ep × ${arr("losses")} loss × ${arr("dropouts")} drop × ${arr("neurons_factors_list")} arch × ${arr("batch_sizes")} bs)`, "info");
      if (hasGrid) {
        addLog(`Feature subset grid : ACTIVE (mandatory=${JSON.stringify(payload.mandatory_input_cols)}, min_input=${payload.min_input_count})`, "info");
        addLog("Le total sera hyperparametres × feature_sets (calcule par le backend)", "info");
      } else {
        addLog("Feature subset grid : DESACTIVE (un seul feature set)", "info");
      }

      const res = await fetchWithAuth(apiUrl("/api/training/start"), {
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
      if (data.total_combinations) {
        setTotalModels(data.total_combinations);
      }
      // Capture the resolved output_dir from the backend (may differ from user input)
      if (data.output_dir) {
        setOutputDir(data.output_dir);
      }

      addLog(`Tache creee : ${newTaskId} — ${data.total_combinations ?? "?"} combinaisons totales (feature_sets × hyperparametres)`, "success");
      addLog("Entrainement en cours...", "info");
      setStatus("running");
      samNotify.thinking("On itere sur le grid search. Patience, c'est bientot fini.");
      startPolling(newTaskId);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Erreur inconnue";
      setStatus("failed");
      setErrorMsg(message);
      addLog(`ERREUR : ${message}`, "error");
      toast.error(`Echec : ${message}`);
      samNotify.error(`Echec: ${message}`, { title: "Training" });
    }
  }

  // Bug 2 (T1) — handleCancel doit pousser le frontend jusqu'a l'etat
  // final "cancelled" en pollant le backend apres l'envoi de la demande.
  // Sans ce polling dedie, l'utilisateur restait bloque sur "Annulation
  // demandee..." avec barre figee meme apres confirmation backend.
  const trainingCancel = useTrainingCancel({
    onRequested: () => {
      addLog("Annulation demandee...", "info");
      toast.info("Annulation en cours");
    },
    onConfirmed: () => {
      // Backend a confirme. Le polling principal a deja pu basculer le
      // status; on force ici au cas ou la confirmation arrive plus tot.
      setStatus("cancelled");
      if (pollingRef.current) clearInterval(pollingRef.current);
      toast.info("Training annule");
      samNotify.info("Training annule.");
    },
    onTimeout: () => {
      // Le backend n'a jamais confirme dans la fenetre de 10s — on
      // bascule quand meme l'UI cote frontend pour debloquer l'utilisateur.
      setStatus("cancelled");
      if (pollingRef.current) clearInterval(pollingRef.current);
      toast.error("Backend n'a pas confirme l'annulation (timeout)");
    },
    onError: (msg) => {
      toast.error(`Impossible d'annuler : ${msg}`);
      samNotify.error("Impossible d'annuler le training.");
    },
  });

  async function handleCancel() {
    if (!taskId) return;
    setStatus("cancelling");
    await trainingCancel.cancel(taskId);
  }

  // Stop le polling cancel quand le composant unmount.
  useEffect(() => {
    return () => trainingCancel.stop();
  }, [trainingCancel]);

  function handleResetAfterCancel() {
    // Remet l'UI a l'etat initial pour permettre un nouveau lancement.
    setStatus("idle");
    setTaskId(null);
    setLogs([]);
    setLossData([]);
    setBestLoss(null);
    setCurrentEpoch(0);
    setTotalEpochs(0);
    setElapsed(0);
    setErrorMsg(null);
  }

  function goToEvaluation() {
    nextStep();
    router.push("/evaluation");
  }

  const overallProgress =
    totalEpochs > 0 ? (currentEpoch / totalEpochs) * 100 : 0;

  // Bonus — ETA simple "reste ~X min". Estimation lineaire :
  // temps total estime = elapsed * (totalEpochs / currentEpoch)
  // ETA = total estime - elapsed. Affiche uniquement en cours d'entrainement
  // et apres quelques epochs pour eviter les estimations folles initiales.
  const etaSeconds =
    status === "running" && currentEpoch >= 2 && totalEpochs > 0 && elapsed > 0
      ? Math.max(0, Math.round((elapsed * totalEpochs) / currentEpoch - elapsed))
      : null;
  const etaLabel =
    etaSeconds === null
      ? null
      : etaSeconds < 60
        ? `~${etaSeconds}s`
        : etaSeconds < 3600
          ? `~${Math.round(etaSeconds / 60)} min`
          : `~${Math.floor(etaSeconds / 3600)}h ${Math.round((etaSeconds % 3600) / 60)}min`;

  const logTypeColors: Record<string, string> = {
    info: "text-slate-400",
    success: "text-emerald-400",
    error: "text-red-400",
    epoch: "text-cyan-300",
  };

  return (
    <div className="space-y-6">
      {/* Success banner */}
      <SuccessBanner
        message={`Entrainement termine — ${totalModels} modele(s)${bestLoss != null ? `, meilleure loss: ${bestLoss.toFixed(6)}` : ""}${outputDir ? ` — ${outputDir}` : ""}`}
        visible={showSuccessBanner}
        onClose={() => setShowSuccessBanner(false)}
      />

      {/* Empty-state — prerequis manquants (Tache 1).
          On rend la page mais on guide l'utilisateur vers les etapes
          manquantes sans le forcer a y aller. */}
      {(!sessionId || !mappingValidated || !trainingConfig) && status === "idle" && (
        <GlowCard glowColor="cyan">
          <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-indigo-500/10 flex items-center justify-center text-indigo-300 shrink-0">
              {!sessionId || !mappingValidated ? (
                <Database size={22} aria-hidden="true" />
              ) : (
                <Settings2 size={22} aria-hidden="true" />
              )}
            </div>
            <div className="flex-1 space-y-1">
              <h3 className="text-sm font-semibold text-white">
                {!sessionId
                  ? "Aucun jeu de donnees charge"
                  : !mappingValidated
                    ? "Mapping de colonnes a valider"
                    : "Configuration manquante"}
              </h3>
              <p className="text-xs text-slate-300">
                {!sessionId
                  ? "Pour entrainer un modele, importe d'abord un jeu de donnees via Etape 1 — Donnees."
                  : !mappingValidated
                    ? "Valide le mapping des colonnes sur l'etape Donnees pour continuer."
                    : "Definis une configuration d'entrainement sur l'etape Configuration."}
              </p>
            </div>
            <Link
              href={!sessionId || !mappingValidated ? "/donnees" : "/config"}
              className="shrink-0"
            >
              <NeonButton icon={<ArrowRight size={14} />}>
                {!sessionId || !mappingValidated
                  ? "Aller a Donnees"
                  : "Aller a Configuration"}
              </NeonButton>
            </Link>
          </div>
        </GlowCard>
      )}

      {/* Header — ShimmerText H1, status pulse-aware, premium CTAs */}
      <RevealOnScroll variant="fade" stagger={0.05}>
        <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
          <div className="space-y-2">
            {status === "completed" ? (
              <ShimmerText as="h1" variant="neon-white" className="text-2xl sm:text-3xl">
                Modele entraine -{" "}
                {mode === "pl"
                  ? "PL"
                  : mode === "hpm"
                    ? "HPM (8h-9h)"
                    : mode === "hps"
                      ? "HPS (17h-18h)"
                      : "TV"}
              </ShimmerText>
            ) : (
              <ShimmerText
                as="h1"
                variant="neon-white"
                className="text-2xl sm:text-3xl"
              >
                Entrainement{" "}
                {mode === "pl"
                  ? "PL"
                  : mode === "hpm"
                    ? "HPM (8h-9h)"
                    : mode === "hps"
                      ? "HPS (17h-18h)"
                      : "TV"}
              </ShimmerText>
            )}
            <p className="text-sm text-text-muted">
              Entrainement grid search des modeles{" "}
              {mode === "pl"
                ? "Poids Lourds"
                : mode === "hpm"
                  ? "Heure de Pointe Matin (v/h)"
                  : mode === "hps"
                    ? "Heure de Pointe Soir (v/h)"
                    : "Tous Vehicules"}
              . Suivez la progression en temps reel.
            </p>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <StatBadge
                label="Status"
                value={
                  status === "idle"
                    ? "Pret"
                    : status === "starting"
                      ? "Demarrage"
                      : status === "running"
                        ? "En cours"
                        : status === "completed"
                          ? "Termine"
                          : status === "failed"
                            ? "Echec"
                            : status === "cancelling"
                              ? "Annulation"
                              : "Annule"
                }
                tone={
                  status === "completed"
                    ? "success"
                    : status === "running"
                      ? "cyan"
                      : status === "failed"
                        ? "danger"
                        : status === "cancelled" || status === "cancelling"
                          ? "amber"
                          : "neutral"
                }
                size="sm"
              />
              {totalModels > 1 && (
                <StatBadge
                  label="Modeles"
                  value={`${currentModel + 1}/${totalModels}`}
                  tone="accent"
                  size="sm"
                />
              )}
              {trainingConfig?.seed !== undefined && (
                <StatBadge
                  label="Seed"
                  value={String(trainingConfig.seed)}
                  tone="violet"
                  size="sm"
                />
              )}
            </div>
          </div>

          {/* Action buttons — MagneticButton premium */}
          <div className="flex gap-3 shrink-0">
            {status === "idle" && (
              <MagneticButton
                variant="primary"
                size="lg"
                onClick={handleStartTraining}
              >
                <Play size={16} />
                Lancer l&apos;entrainement
              </MagneticButton>
            )}
            {status === "starting" && (
              <MagneticButton variant="primary" size="lg" disabled>
                Demarrage...
              </MagneticButton>
            )}
            {status === "running" && (
              <MagneticButton
                variant="secondary"
                size="md"
                onClick={handleCancel}
              >
                <Square size={16} />
                Annuler
              </MagneticButton>
            )}
            {status === "cancelling" && (
              <MagneticButton variant="secondary" size="md" disabled>
                Annulation...
              </MagneticButton>
            )}
            {status === "cancelled" && (
              <div className="flex gap-2">
                <MagneticButton
                  variant="ghost"
                  size="md"
                  onClick={() => router.push("/config")}
                >
                  Retour configuration
                </MagneticButton>
                <MagneticButton
                  variant="primary"
                  size="md"
                  onClick={handleResetAfterCancel}
                >
                  <Play size={16} />
                  Relancer
                </MagneticButton>
              </div>
            )}
            {status === "completed" && (
              <MagneticButton
                variant="primary"
                size="lg"
                onClick={goToEvaluation}
              >
                Voir evaluation
                <ChevronRight size={16} />
              </MagneticButton>
            )}
          </div>
        </div>
      </RevealOnScroll>

      {/* Output dir - optional (server workspace used by default) */}
      {status === "idle" && (
        <GlowCard>
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center text-indigo-400 shrink-0">
              <BarChart3 size={20} />
            </div>
            <div className="flex-1 space-y-2">
              <label className="text-sm font-medium text-slate-200">
                Nom de la serie de modeles
                <span className="text-xs text-slate-400 font-normal ml-2">(optionnel)</span>
              </label>
              <p className="text-xs text-slate-400">
                Etiquette affichee et utilisee pour nommer le fichier zip de
                telechargement. Les modeles sont entraines et conserves sur le
                serveur ; un bouton de telechargement apparait a la fin.
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={localOutputDir}
                  onChange={(e) => setLocalOutputDir(e.target.value)}
                  placeholder="ex. MDL_Bordeaux"
                  className="flex-1 px-3 py-2 rounded-lg text-sm bg-slate-900/80 border border-white/[0.08] text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30 transition-colors"
                />
              </div>
            </div>
          </div>
        </GlowCard>
      )}
      {status !== "idle" && outputDir && (
        <div className="text-xs text-slate-400 px-1">
          Dossier de sortie : <span className="text-cyan-300">{outputDir}</span>
        </div>
      )}

      {/* Stats — StatBadge horizontal row, KPI live, ref pour confetti */}
      <div ref={statsContainerRef} className="relative">
        <div className="flex flex-wrap gap-2">
          <StatCard
            label="Modele en cours"
            value={`${currentModel + 1} / ${totalModels}`}
            icon={<Cpu size={18} />}
            className={successCardPulse ? "animate-success-pulse" : ""}
          />
          <StatCard
            label="Meilleure val_loss"
            value={bestLoss !== null ? bestLoss.toFixed(6) : "--"}
            icon={<Activity size={18} />}
            trend={bestLoss !== null ? "down" : undefined}
            className={successCardPulse ? "animate-success-pulse" : ""}
          />
          <StatCard
            label="Temps ecoule"
            value={`${Math.floor(elapsed / 60)}m ${elapsed % 60}s`}
            icon={<Clock size={18} />}
            className={successCardPulse ? "animate-success-pulse" : ""}
          />
        </div>
      </div>

      {/* Progress bar — NeonBorder cyan pulse quand running, GlowCard standard sinon. */}
      <ProgressBarShell active={status === "running" || status === "starting"}>
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <StatBadge
                label="Epoch"
                value={`${currentEpoch} / ${totalEpochs || "?"}`}
                tone={status === "running" ? "cyan" : "neutral"}
                size="sm"
              />
              {etaLabel && (
                <StatBadge
                  label="Reste"
                  value={etaLabel}
                  tone="amber"
                  size="sm"
                />
              )}
              {modelName && status === "running" && (
                <StatBadge
                  label="Run"
                  value={modelName.length > 24 ? `${modelName.slice(0, 22)}...` : modelName}
                  tone="violet"
                  size="sm"
                />
              )}
            </div>
            <span className={status === "running" ? "text-[#22d3ee] font-semibold tabular-nums" : "text-accent font-medium"}>
              {Math.round(overallProgress)}%
            </span>
          </div>
          <div className="h-3 rounded-full bg-bg-subtle overflow-hidden ring-1 ring-border/60">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${overallProgress}%` }}
              transition={{ duration: 0.5, ease: "easeOut" }}
              className={
                status === "completed"
                  ? "h-full rounded-full success-bar-shine"
                  : status === "running" || status === "starting"
                    ? "h-full rounded-full bg-gradient-to-r from-[#22d3ee] via-[#6366f1] to-[#f59e0b] shadow-[0_0_18px_-2px_rgba(34,211,238,0.6)]"
                    : "h-full rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-violet-500"
              }
            />
          </div>

          {/* Status message */}
          <AnimatePresence mode="wait">
            {status === "completed" && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-center py-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 space-y-2"
              >
                <p className="text-sm font-medium text-emerald-400">
                  Entrainement termine
                </p>
                <p className="text-xs text-slate-400">
                  {currentEpoch} epochs en {Math.floor(elapsed / 60)}m{" "}
                  {elapsed % 60}s
                </p>
                {sessionId && (
                  <a
                    href={apiUrl(`/api/export/models-all/${sessionId}`)}
                    download
                    className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-medium transition-colors"
                  >
                    Telecharger tous les modeles (.zip)
                  </a>
                )}
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
            {status === "cancelling" && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-center py-3 rounded-lg bg-amber-500/10 border border-amber-500/20"
              >
                <p className="text-sm font-medium text-amber-300">
                  Annulation en cours...
                </p>
                <p className="text-xs text-amber-300/70 mt-1">
                  Attente de la confirmation du serveur.
                </p>
              </motion.div>
            )}
            {status === "cancelled" && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-center py-3 rounded-lg bg-slate-500/10 border border-slate-500/20"
              >
                <p className="text-sm font-medium text-slate-200">
                  Entrainement annule
                </p>
                <p className="text-xs text-slate-400 mt-1">
                  Vous pouvez relancer une session ou ajuster la configuration.
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </ProgressBarShell>

      {/* Loss curve */}
      {lossData.length > 1 && (
        <GlowCardPremium tone="violet" intensity={0.4}>
          <p className="text-xs text-text-muted mb-3 flex items-center gap-2">
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
        </GlowCardPremium>
      )}

      {/* Logs panel */}
      <GlowCard>
        <div className="flex items-center gap-2 mb-3">
          <ScrollText size={14} className="text-text-muted" />
          <p className="text-xs text-text-muted font-medium">
            Journal d&apos;entrainement
          </p>
          <span className="text-[10px] text-text-subtle ml-auto tabular-nums">
            {logs.length} entrees
          </span>
        </div>
        <div className="bg-bg/80 rounded-lg border border-border p-3 max-h-[300px] overflow-y-auto font-mono text-[11px] space-y-0.5">
          {logs.length === 0 ? (
            <p className="text-text-subtle text-center py-4">
              Les logs apparaitront ici une fois l&apos;entrainement lance.
            </p>
          ) : (
            logs.map((log, i) => (
              <div key={i} className="flex gap-2 animate-[fadeIn_.25s_ease]">
                <span className="text-text-subtle shrink-0 tabular-nums">[{log.time}]</span>
                <span className={logTypeColors[log.type] ?? "text-text-muted"}>
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
