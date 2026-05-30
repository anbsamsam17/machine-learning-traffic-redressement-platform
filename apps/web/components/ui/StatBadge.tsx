"use client";

/** Badge KPI compact : icone + valeur + label, fond glass et glow subtil. */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type StatBadgeTone = "accent" | "amber" | "cyan" | "violet" | "success" | "danger" | "neutral";
export type StatBadgeSize = "sm" | "md";

export interface StatBadgeProps {
  label: string;
  value: ReactNode;
  icon?: ReactNode;
  tone?: StatBadgeTone;
  size?: StatBadgeSize;
  className?: string;
  title?: string;
}

const TONE: Record<StatBadgeTone, { text: string; ring: string; bg: string; glow: string }> = {
  accent: {
    text: "text-accent",
    ring: "ring-[rgba(99,102,241,0.25)]",
    bg: "bg-[rgba(99,102,241,0.08)]",
    glow: "shadow-[0_0_18px_-6px_rgba(99,102,241,0.5)]",
  },
  amber: {
    text: "text-[#f59e0b]",
    ring: "ring-[rgba(245,158,11,0.25)]",
    bg: "bg-[rgba(245,158,11,0.08)]",
    glow: "shadow-[0_0_18px_-6px_rgba(245,158,11,0.5)]",
  },
  cyan: {
    text: "text-[#22d3ee]",
    ring: "ring-[rgba(6,182,212,0.25)]",
    bg: "bg-[rgba(6,182,212,0.08)]",
    glow: "shadow-[0_0_18px_-6px_rgba(6,182,212,0.5)]",
  },
  violet: {
    text: "text-[#a78bfa]",
    ring: "ring-[rgba(139,92,246,0.25)]",
    bg: "bg-[rgba(139,92,246,0.08)]",
    glow: "shadow-[0_0_18px_-6px_rgba(139,92,246,0.5)]",
  },
  success: {
    text: "text-success",
    ring: "ring-[rgba(16,185,129,0.25)]",
    bg: "bg-[rgba(16,185,129,0.08)]",
    glow: "shadow-[0_0_18px_-6px_rgba(16,185,129,0.5)]",
  },
  danger: {
    text: "text-danger",
    ring: "ring-[rgba(239,68,68,0.25)]",
    bg: "bg-[rgba(239,68,68,0.08)]",
    glow: "shadow-[0_0_18px_-6px_rgba(239,68,68,0.5)]",
  },
  neutral: {
    text: "text-text",
    ring: "ring-[rgba(255,255,255,0.08)]",
    bg: "bg-bg-elevated/60",
    glow: "shadow-none",
  },
};

const SIZE: Record<StatBadgeSize, { pad: string; gap: string; val: string; label: string; icon: string }> = {
  sm: {
    pad: "px-2.5 py-1",
    gap: "gap-1.5",
    val: "text-xs font-semibold tabular-nums",
    label: "text-[10px] uppercase tracking-wider",
    icon: "[&_svg]:size-3",
  },
  md: {
    pad: "px-3 py-1.5",
    gap: "gap-2",
    val: "text-sm font-semibold tabular-nums",
    label: "text-[11px] uppercase tracking-wider",
    icon: "[&_svg]:size-3.5",
  },
};

export function StatBadge({
  label,
  value,
  icon,
  tone = "accent",
  size = "md",
  className,
  title,
}: StatBadgeProps) {
  const tonePalette = TONE[tone];
  const sizePalette = SIZE[size];

  return (
    <div
      title={title}
      className={cn(
        "inline-flex items-center rounded-full backdrop-blur-sm ring-1",
        "transition-colors",
        tonePalette.bg,
        tonePalette.ring,
        tonePalette.glow,
        sizePalette.pad,
        sizePalette.gap,
        className
      )}
    >
      {icon && (
        <span className={cn("shrink-0", tonePalette.text, sizePalette.icon)}>{icon}</span>
      )}
      <span className={cn("font-mono", tonePalette.text, sizePalette.val)}>{value}</span>
      <span className={cn("text-text-muted", sizePalette.label)}>{label}</span>
    </div>
  );
}
