"use client";

import { motion, AnimatePresence } from "framer-motion";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
} from "recharts";
import { X, Download, Trophy } from "lucide-react";
import { NeonButton } from "@/components/ui/neon-button";
import { StatCard } from "@/components/ui/stat-card";
import type { ModelResult } from "./model-comparison";

interface ModelDetailDrawerProps {
  model: ModelResult | null;
  open: boolean;
  onClose: () => void;
  scatterData?: Array<{ observed: number; predicted: number }>;
  gehDistribution?: Array<{ range: string; count: number }>;
}

export function ModelDetailDrawer({
  model,
  open,
  onClose,
  scatterData = [],
  gehDistribution = [],
}: ModelDetailDrawerProps) {
  if (!model) return null;

  // Demo scatter data if none provided
  const scatter =
    scatterData.length > 0
      ? scatterData
      : Array.from({ length: 50 }, (_, i) => {
          const obs = Math.random() * 10000;
          return {
            observed: obs,
            predicted: obs * (0.85 + Math.random() * 0.3),
          };
        });

  const gehDist =
    gehDistribution.length > 0
      ? gehDistribution
      : [
          { range: "0-1", count: 35 },
          { range: "1-2", count: 25 },
          { range: "2-3", count: 18 },
          { range: "3-5", count: 12 },
          { range: "5-10", count: 7 },
          { range: ">10", count: 3 },
        ];

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Overlay */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          />

          {/* Drawer */}
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 200 }}
            className="fixed right-0 top-0 bottom-0 z-50 w-full max-w-lg bg-background border-l border-border overflow-y-auto"
          >
            <div className="p-6 space-y-6">
              {/* Header */}
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    {model.isBest && (
                      <Trophy size={16} className="text-yellow-400" />
                    )}
                    <h2 className="text-lg font-bold text-foreground">
                      {model.name}
                    </h2>
                  </div>
                  <p className="text-xs text-muted mt-1 font-mono">
                    {model.architecture} | {model.activation} | lr=
                    {model.lr}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  className="p-2 rounded-lg hover:bg-surface-light text-muted hover:text-foreground transition-colors"
                >
                  <X size={18} />
                </button>
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-2 gap-3">
                <StatCard label="R2 Score" value={model.r2.toFixed(4)} />
                <StatCard label="MAPE" value={`${model.mape.toFixed(1)}%`} />
                <StatCard
                  label="Val Loss"
                  value={model.valLoss.toFixed(6)}
                  trend="down"
                />
                <StatCard
                  label="GEH < 5"
                  value={`${model.gehPct.toFixed(1)}%`}
                  trend={model.gehPct >= 85 ? "up" : "down"}
                />
              </div>

              {/* Scatter plot */}
              <div className="glass-light p-4">
                <p className="text-xs text-muted mb-3">
                  Observe vs Predit
                </p>
                <ResponsiveContainer width="100%" height={250}>
                  <ScatterChart>
                    <CartesianGrid stroke="rgba(99,102,241,0.08)" />
                    <XAxis
                      type="number"
                      dataKey="observed"
                      name="Observe"
                      tick={{ fontSize: 10, fill: "#94a3b8" }}
                      stroke="rgba(99,102,241,0.1)"
                    />
                    <YAxis
                      type="number"
                      dataKey="predicted"
                      name="Predit"
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
                    />
                    <Scatter data={scatter} fill="#6366f1" opacity={0.6} />
                  </ScatterChart>
                </ResponsiveContainer>
              </div>

              {/* GEH histogram */}
              <div className="glass-light p-4">
                <p className="text-xs text-muted mb-3">
                  Distribution GEH
                </p>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={gehDist}>
                    <CartesianGrid stroke="rgba(99,102,241,0.08)" />
                    <XAxis
                      dataKey="range"
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
                    />
                    <Bar dataKey="count" fill="#06b6d4" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Download */}
              <NeonButton
                variant="secondary"
                icon={<Download size={16} />}
                className="w-full"
              >
                Telecharger le rapport
              </NeonButton>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
