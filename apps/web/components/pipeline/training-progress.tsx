"use client";

import { useEffect, useState, useRef } from "react";
import { motion } from "framer-motion";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Activity, Clock, Cpu } from "lucide-react";
import { StatCard } from "@/components/ui/stat-card";
import { streamSSE } from "@/lib/api";

interface TrainingEvent {
  type: string;
  epoch?: number;
  total_epochs?: number;
  loss?: number;
  val_loss?: number;
  model_index?: number;
  total_models?: number;
  model_name?: string;
  best_loss?: number;
  elapsed?: number;
  status?: string;
}

interface LossPoint {
  epoch: number;
  loss: number;
  val_loss: number;
}

interface TrainingProgressProps {
  taskId: string;
  onComplete?: () => void;
}

export function TrainingProgress({
  taskId,
  onComplete,
}: TrainingProgressProps) {
  const [, setEvents] = useState<TrainingEvent[]>([]);
  const [lossData, setLossData] = useState<LossPoint[]>([]);
  const [currentModel, setCurrentModel] = useState(0);
  const [totalModels, setTotalModels] = useState(1);
  const [currentEpoch, setCurrentEpoch] = useState(0);
  const [totalEpochs, setTotalEpochs] = useState(1);
  const [modelName, setModelName] = useState("");
  const [bestLoss, setBestLoss] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [status, setStatus] = useState<"idle" | "running" | "done">("idle");
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!taskId) return;

    setStatus("running");
    const es = streamSSE(
      `/api/training/stream/${taskId}`,
      (data) => {
        const event = data as unknown as TrainingEvent;
        setEvents((prev) => [...prev, event]);

        if (event.type === "epoch") {
          setCurrentEpoch(event.epoch ?? 0);
          setTotalEpochs(event.total_epochs ?? 1);
          if (event.loss !== undefined && event.val_loss !== undefined) {
            setLossData((prev) => [
              ...prev,
              {
                epoch: event.epoch ?? prev.length,
                loss: event.loss!,
                val_loss: event.val_loss!,
              },
            ]);
          }
        }

        if (event.type === "model_start") {
          setCurrentModel(event.model_index ?? 0);
          setTotalModels(event.total_models ?? 1);
          setModelName(event.model_name ?? "");
          setLossData([]);
          setCurrentEpoch(0);
        }

        if (event.type === "model_end") {
          if (event.best_loss !== undefined) setBestLoss(event.best_loss);
        }

        if (event.elapsed !== undefined) setElapsed(event.elapsed);

        if (event.type === "complete") {
          setStatus("done");
          onComplete?.();
        }
      },
      () => {
        setStatus("done");
      }
    );

    esRef.current = es;
    return () => es.close();
  }, [taskId, onComplete]);

  const overallProgress =
    totalModels > 0
      ? ((currentModel + currentEpoch / Math.max(totalEpochs, 1)) /
          totalModels) *
        100
      : 0;

  const modelProgress =
    totalEpochs > 0 ? (currentEpoch / totalEpochs) * 100 : 0;

  return (
    <div className="space-y-6">
      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatCard
          label="Modele en cours"
          value={`${currentModel + 1} / ${totalModels}`}
          icon={<Cpu size={18} />}
        />
        <StatCard
          label="Meilleure loss"
          value={bestLoss !== null ? bestLoss.toFixed(6) : "--"}
          icon={<Activity size={18} />}
          trend={bestLoss !== null ? "down" : undefined}
        />
        <StatCard
          label="Temps ecoule"
          value={`${Math.floor(elapsed / 60)}m ${Math.round(elapsed % 60)}s`}
          icon={<Clock size={18} />}
        />
      </div>

      {/* Overall progress */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted">Progression globale</span>
          <span className="text-accent font-medium">
            {Math.round(overallProgress)}%
          </span>
        </div>
        <div className="h-2 rounded-full bg-surface-light overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${overallProgress}%` }}
            transition={{ duration: 0.3 }}
            className="h-full rounded-full bg-gradient-to-r from-accent via-cyan to-violet"
          />
        </div>
      </div>

      {/* Current model progress */}
      {status === "running" && (
        <div className="glass-light p-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-foreground">
              {modelName || `Modele ${currentModel + 1}`}
            </p>
            <span className="text-xs text-muted">
              Epoch {currentEpoch} / {totalEpochs}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-surface overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${modelProgress}%` }}
              className="h-full rounded-full bg-accent"
            />
          </div>
        </div>
      )}

      {/* Loss curve */}
      {lossData.length > 1 && (
        <div className="glass-light p-4">
          <p className="text-xs text-muted mb-3">Courbe de loss</p>
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
        </div>
      )}

      {/* Status */}
      {status === "done" && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass p-4 text-center neon-glow"
        >
          <p className="text-sm font-medium text-emerald-400">
            Entrainement termine
          </p>
          <p className="text-xs text-muted mt-1">
            {totalModels} modeles entraines en{" "}
            {Math.floor(elapsed / 60)}m {Math.round(elapsed % 60)}s
          </p>
        </motion.div>
      )}
    </div>
  );
}
