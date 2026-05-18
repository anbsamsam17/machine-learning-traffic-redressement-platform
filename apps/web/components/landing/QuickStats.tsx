"use client";

import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";
import type { QuickStat } from "./types";

interface QuickStatsProps {
  stats: QuickStat[];
}

export function QuickStats({ stats }: QuickStatsProps) {
  const reduce = useReducedMotion();

  return (
    <motion.section
      aria-labelledby="quickstats-heading"
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.15 }}
      className={cn(
        "rounded-2xl border border-white/[0.06] bg-zinc-950/60 backdrop-blur-md",
        "overflow-hidden"
      )}
    >
      <h2 id="quickstats-heading" className="sr-only">
        Indicateurs cles
      </h2>
      <ul className="grid grid-cols-2 md:grid-cols-4 divide-y md:divide-y-0 md:divide-x divide-white/[0.05]">
        {stats.map((stat) => (
          <li key={stat.label} className="px-5 py-4">
            <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
              {stat.label}
            </p>
            <p className="mt-1 font-mono tabular-nums text-2xl font-semibold text-zinc-50">
              {stat.value}
            </p>
            {stat.hint && (
              <p className="mt-0.5 text-[11px] text-zinc-500">{stat.hint}</p>
            )}
          </li>
        ))}
      </ul>
    </motion.section>
  );
}
