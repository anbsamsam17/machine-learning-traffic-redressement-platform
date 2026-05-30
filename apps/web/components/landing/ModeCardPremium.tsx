"use client";

/**
 * ModeCardPremium — Module card built on UX5 GlowCard.
 *
 * Each landing module is rendered as a GlowCard with a tone aligned to
 * its semantic accent. The whole card is a button (semantics preserved
 * for keyboard a11y), and the CTA row uses an MagneticButton-style hover
 * delegated to the parent.
 */

import { ArrowUpRight, type LucideIcon } from "lucide-react";
import { GlowCardPremium } from "@/components/ui";
import type { GlowCardTone } from "@/components/ui/GlowCard";
import { cn } from "@/lib/utils";
import type { LandingModeContent } from "./types";

interface ModeCardPremiumProps {
  mode: LandingModeContent;
  onSelect: (key: LandingModeContent["key"]) => void;
}

/**
 * Map our 6-accent palette down to the 4-tone GlowCard system.
 * - indigo  -> accent
 * - amber   -> amber
 * - cyan    -> cyan
 * - emerald -> cyan (fallback closest)
 * - rose    -> amber (warm)
 * - violet  -> violet
 */
const ACCENT_TO_TONE: Record<LandingModeContent["accent"], GlowCardTone> = {
  indigo: "accent",
  amber: "amber",
  cyan: "cyan",
  emerald: "cyan",
  rose: "amber",
  violet: "violet",
};

const ICON_COLOR: Record<LandingModeContent["accent"], string> = {
  indigo: "text-accent",
  amber: "text-amber-300",
  cyan: "text-cyan-300",
  emerald: "text-emerald-300",
  rose: "text-rose-300",
  violet: "text-violet-300",
};

const CHIP_BORDER: Record<LandingModeContent["accent"], string> = {
  indigo: "border-accent/25 text-accent",
  amber: "border-amber-400/25 text-amber-200/90",
  cyan: "border-cyan-400/25 text-cyan-200/90",
  emerald: "border-emerald-400/25 text-emerald-200/90",
  rose: "border-rose-400/25 text-rose-200/90",
  violet: "border-violet-400/25 text-violet-200/90",
};

const ICON_BG: Record<LandingModeContent["accent"], string> = {
  indigo: "bg-accent/12",
  amber: "bg-amber-500/12",
  cyan: "bg-cyan-500/12",
  emerald: "bg-emerald-500/12",
  rose: "bg-rose-500/12",
  violet: "bg-violet-500/12",
};

export function ModeCardPremium({ mode, onSelect }: ModeCardPremiumProps) {
  const tone = ACCENT_TO_TONE[mode.accent];
  const Icon: LucideIcon = mode.icon;

  return (
    <GlowCardPremium
      tone={tone}
      intensity={0.55}
      className="h-full"
      role="button"
      tabIndex={0}
      aria-label={`${mode.title} — ${mode.tagline}`}
      data-mode-card={mode.key}
      onClick={() => onSelect(mode.key)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(mode.key);
        }
      }}
    >
      <div className="flex flex-col h-full cursor-pointer">
        {/* Top row: icon + short title badge */}
        <div className="flex items-start justify-between gap-3 mb-4">
          <div
            className={cn(
              "h-11 w-11 rounded-lg flex items-center justify-center shrink-0",
              "ring-1 ring-white/[0.06]",
              ICON_BG[mode.accent]
            )}
          >
            <Icon
              className={cn("h-5 w-5", ICON_COLOR[mode.accent])}
              strokeWidth={1.75}
            />
          </div>
          <span
            className={cn(
              "font-mono text-[10px] tracking-widest uppercase px-2 py-0.5 rounded-md border bg-white/[0.02]",
              CHIP_BORDER[mode.accent]
            )}
          >
            {mode.shortTitle}
          </span>
        </div>

        {/* Title + tagline */}
        <h3 className="text-base md:text-[17px] font-semibold text-zinc-50 tracking-tight line-clamp-2 min-h-[3rem]">
          {mode.title}
        </h3>
        <p className="mt-1 text-sm text-zinc-400 line-clamp-2 min-h-[2.5rem]">
          {mode.tagline}
        </p>

        {/* Description */}
        <p className="mt-3 text-[13px] leading-relaxed text-zinc-500 line-clamp-4 min-h-[5.25rem]">
          {mode.description}
        </p>

        {/* Key metrics chips */}
        {mode.keyMetrics.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1.5 content-start">
            {mode.keyMetrics.map((metric) => (
              <span
                key={metric}
                className={cn(
                  "font-mono tabular-nums text-[10px] px-2 py-0.5 rounded-md border bg-white/[0.02]",
                  CHIP_BORDER[mode.accent]
                )}
              >
                {metric}
              </span>
            ))}
          </div>
        )}

        {/* CTA pinned to bottom */}
        <div className="mt-auto pt-4 border-t border-white/[0.05] flex items-center justify-between">
          <span
            className={cn(
              "text-xs font-medium tracking-wide transition-colors",
              ICON_COLOR[mode.accent]
            )}
          >
            {mode.cta}
          </span>
          <ArrowUpRight
            className={cn(
              "h-4 w-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5",
              ICON_COLOR[mode.accent]
            )}
            strokeWidth={1.75}
          />
        </div>
      </div>
    </GlowCardPremium>
  );
}
