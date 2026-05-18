"use client";

import { motion, useReducedMotion } from "framer-motion";
import { Brain, Map, Activity, FileText, CheckCircle2, Clock, AlertCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ActivityItem, ActivityKind, ActivityStatus } from "./types";

interface RecentActivityProps {
  items: ActivityItem[];
}

const KIND_ICON: Record<ActivityKind, LucideIcon> = {
  training: Brain,
  map: Map,
  compteurs: Activity,
  report: FileText,
};

const STATUS_META: Record<
  ActivityStatus,
  { icon: LucideIcon; label: string; classes: string }
> = {
  success: {
    icon: CheckCircle2,
    label: "Termine",
    classes: "text-emerald-300 bg-emerald-500/10 border-emerald-400/20",
  },
  pending: {
    icon: Clock,
    label: "En cours",
    classes: "text-amber-300 bg-amber-500/10 border-amber-400/20",
  },
  error: {
    icon: AlertCircle,
    label: "Erreur",
    classes: "text-rose-300 bg-rose-500/10 border-rose-400/20",
  },
};

export function RecentActivity({ items }: RecentActivityProps) {
  const reduce = useReducedMotion();

  return (
    <motion.section
      aria-labelledby="activity-heading"
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.2 }}
      className="rounded-2xl border border-white/[0.06] bg-zinc-950/60 backdrop-blur-md p-5"
    >
      <header className="flex items-center justify-between mb-4">
        <h2
          id="activity-heading"
          className="text-sm font-semibold text-zinc-100 tracking-tight"
        >
          Activite recente
        </h2>
        <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">
          {items.length}
        </span>
      </header>

      {items.length === 0 ? (
        <p className="text-xs text-zinc-500 py-4 text-center">
          Aucune activite recente.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => {
            const Icon = KIND_ICON[item.kind];
            const status = STATUS_META[item.status];
            const StatusIcon = status.icon;
            return (
              <li
                key={item.id}
                className={cn(
                  "flex items-center gap-3 p-2.5 rounded-lg",
                  "border border-transparent hover:border-white/[0.06] hover:bg-white/[0.02]",
                  "transition-colors"
                )}
              >
                <div className="h-8 w-8 rounded-lg bg-white/[0.04] flex items-center justify-center shrink-0">
                  <Icon
                    className="h-4 w-4 text-zinc-400"
                    strokeWidth={1.75}
                    aria-hidden
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-zinc-200 truncate">
                    {item.title}
                  </p>
                  <p className="font-mono tabular-nums text-[10px] text-zinc-500 mt-0.5">
                    {item.time}
                  </p>
                </div>
                <span
                  className={cn(
                    "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border text-[10px] font-medium",
                    status.classes
                  )}
                >
                  <StatusIcon className="h-3 w-3" strokeWidth={2} aria-hidden />
                  {status.label}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </motion.section>
  );
}
