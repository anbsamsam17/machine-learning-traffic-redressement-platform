"use client";

import { motion, useReducedMotion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { LandingModeContent } from "./types";

interface ModeCardProps {
  mode: LandingModeContent;
  onSelect: (key: LandingModeContent["key"]) => void;
  index?: number;
}

const ACCENT: Record<
  LandingModeContent["accent"],
  {
    iconBg: string;
    iconText: string;
    border: string;
    chip: string;
    badge: string;
    cta: string;
    glow: string;
  }
> = {
  indigo: {
    iconBg: "bg-indigo-500/10",
    iconText: "text-indigo-300",
    border: "hover:border-indigo-400/40",
    chip: "border-indigo-400/15 text-indigo-200/90",
    badge: "bg-indigo-500/15 text-indigo-200 border-indigo-400/25",
    cta: "text-indigo-300 group-hover:text-indigo-200",
    glow: "group-hover:shadow-[0_8px_30px_-12px_rgba(99,102,241,0.5)]",
  },
  amber: {
    iconBg: "bg-amber-500/10",
    iconText: "text-amber-300",
    border: "hover:border-amber-400/40",
    chip: "border-amber-400/15 text-amber-200/90",
    badge: "bg-amber-500/15 text-amber-200 border-amber-400/25",
    cta: "text-amber-300 group-hover:text-amber-200",
    glow: "group-hover:shadow-[0_8px_30px_-12px_rgba(245,158,11,0.5)]",
  },
  cyan: {
    iconBg: "bg-cyan-500/10",
    iconText: "text-cyan-300",
    border: "hover:border-cyan-400/40",
    chip: "border-cyan-400/15 text-cyan-200/90",
    badge: "bg-cyan-500/15 text-cyan-200 border-cyan-400/25",
    cta: "text-cyan-300 group-hover:text-cyan-200",
    glow: "group-hover:shadow-[0_8px_30px_-12px_rgba(6,182,212,0.5)]",
  },
  emerald: {
    iconBg: "bg-emerald-500/10",
    iconText: "text-emerald-300",
    border: "hover:border-emerald-400/40",
    chip: "border-emerald-400/15 text-emerald-200/90",
    badge: "bg-emerald-500/15 text-emerald-200 border-emerald-400/25",
    cta: "text-emerald-300 group-hover:text-emerald-200",
    glow: "group-hover:shadow-[0_8px_30px_-12px_rgba(16,185,129,0.5)]",
  },
  // HPM — Heure de Pointe Matin (lever du soleil, orange chaud).
  rose: {
    iconBg: "bg-rose-500/10",
    iconText: "text-rose-300",
    border: "hover:border-rose-400/40",
    chip: "border-rose-400/15 text-rose-200/90",
    badge: "bg-rose-500/15 text-rose-200 border-rose-400/25",
    cta: "text-rose-300 group-hover:text-rose-200",
    glow: "group-hover:shadow-[0_8px_30px_-12px_rgba(244,63,94,0.5)]",
  },
  // HPS — Heure de Pointe Soir (coucher du soleil, violet/magenta).
  violet: {
    iconBg: "bg-violet-500/10",
    iconText: "text-violet-300",
    border: "hover:border-violet-400/40",
    chip: "border-violet-400/15 text-violet-200/90",
    badge: "bg-violet-500/15 text-violet-200 border-violet-400/25",
    cta: "text-violet-300 group-hover:text-violet-200",
    glow: "group-hover:shadow-[0_8px_30px_-12px_rgba(139,92,246,0.5)]",
  },
};

export function ModeCard({ mode, onSelect, index = 0 }: ModeCardProps) {
  const reduce = useReducedMotion();
  const accent = ACCENT[mode.accent];
  const Icon = mode.icon;

  return (
    <motion.button
      type="button"
      onClick={() => onSelect(mode.key)}
      initial={reduce ? false : { opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.05 * index, ease: [0.16, 1, 0.3, 1] }}
      whileHover={reduce ? undefined : { y: -2 }}
      whileTap={reduce ? undefined : { scale: 0.99 }}
      aria-label={`${mode.title} — ${mode.tagline}`}
      data-mode-card={mode.key}
      className={cn(
        // Flex column + h-full forces children to stack from the top of the cell
        // (overrides default <button> UA vertical-centering) and lets `mt-auto`
        // on the CTA pin it to the bottom. Result: all cards in the row share
        // the same icon baseline, title baseline, and CTA baseline regardless
        // of description length.
        "group relative w-full text-left flex flex-col h-full",
        "rounded-2xl border border-white/[0.06] bg-zinc-950/60 backdrop-blur-md",
        "p-6 md:p-7",
        "transition-all duration-300",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950",
        accent.border,
        accent.glow
      )}
    >
      {/* Top row: icon + short title badge */}
      <div className="flex items-start justify-between gap-3 mb-5 shrink-0">
        <div
          className={cn(
            "h-11 w-11 rounded-xl flex items-center justify-center shrink-0",
            accent.iconBg
          )}
        >
          <Icon className={cn("h-5 w-5", accent.iconText)} strokeWidth={1.75} />
        </div>
        <span
          className={cn(
            "font-mono text-[10px] tracking-widest uppercase px-2 py-0.5 rounded-md border",
            accent.badge
          )}
        >
          {mode.shortTitle}
        </span>
      </div>

      {/* Title — clamp to 2 lines to keep tagline baseline identical across cards */}
      <h3 className="text-lg font-semibold text-zinc-50 tracking-tight line-clamp-2 min-h-[3.5rem]">
        {mode.title}
      </h3>
      <p className="mt-1 text-sm text-zinc-400 line-clamp-2 min-h-[2.5rem]">
        {mode.tagline}
      </p>

      {/* Description — clamp to 4 lines so the chip row sits at the same y */}
      <p className="mt-3 text-[13px] leading-relaxed text-zinc-500 line-clamp-4 min-h-[5.25rem]">
        {mode.description}
      </p>

      {/* Key metrics chips */}
      {mode.keyMetrics.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-1.5 content-start">
          {mode.keyMetrics.map((metric) => (
            <span
              key={metric}
              className={cn(
                "font-mono tabular-nums text-[10px] px-2 py-0.5 rounded-md border bg-white/[0.02]",
                accent.chip
              )}
            >
              {metric}
            </span>
          ))}
        </div>
      )}

      {/* CTA row — pinned to bottom via mt-auto so every card's separator
          line lands on the same y-coordinate. */}
      <div className="mt-auto pt-4 border-t border-white/[0.05] flex items-center justify-between">
        <span
          className={cn(
            "text-xs font-medium tracking-wide transition-colors",
            accent.cta
          )}
        >
          {mode.cta}
        </span>
        <ArrowUpRight
          className={cn(
            "h-4 w-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5",
            accent.cta
          )}
          strokeWidth={1.75}
        />
      </div>
    </motion.button>
  );
}
