"use client";

/**
 * ModeCardPremium — Module card built on UX5 GlowCard.
 *
 * Each landing module is rendered as a GlowCard with a tone aligned to
 * its semantic accent. The whole card is a button (semantics preserved
 * for keyboard a11y), and the CTA row uses an MagneticButton-style hover
 * delegated to the parent.
 */

import type { MouseEvent as ReactMouseEvent, KeyboardEvent as ReactKeyboardEvent } from "react";
import { ArrowUpRight, Info, type LucideIcon } from "lucide-react";
import { GlowCardPremium } from "@/components/ui";
import type { GlowCardTone } from "@/components/ui/GlowCard";
import { cn } from "@/lib/utils";
import { useSamStore } from "@/lib/sam/store";
import {
  SAM_EXPLAIN_AUTO_RESET_MS,
  composeSamExplainMessage,
} from "@/lib/sam/explain-module";
import type { LandingModeContent } from "./types";

interface ModeCardPremiumProps {
  mode: LandingModeContent;
  onSelect: (key: LandingModeContent["key"]) => void;
}

/** Tooltip + aria-label (sortie humanizer_msg). */
const SAM_EXPLAIN_TOOLTIP = "Resume du module par Sam dans la bulle";
/** Label visible au hover (sortie humanizer_msg). */
const SAM_EXPLAIN_LABEL = "Resume par Sam";

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

  /**
   * Trigger Sam explain : compose le message depuis le contenu du module
   * et pousse un mood "analysing" (aura cyan pulse — naturellement visible
   * sur le SamWidget global en bas-droite, pas besoin de mod externe).
   * `stopPropagation` indispensable pour ne pas declencher onSelect (la
   * card entiere est un button qui navigue vers le module).
   */
  function handleSamExplain(e: ReactMouseEvent | ReactKeyboardEvent) {
    e.stopPropagation();
    const message = composeSamExplainMessage(mode);
    useSamStore.getState().setMood("analysing", {
      message,
      autoResetMs: SAM_EXPLAIN_AUTO_RESET_MS,
    });
  }

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
        {/* Top row: icon + short title badge + Sam explain trigger */}
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
          <div className="flex items-center gap-2 shrink-0">
            {/* Sam explain trigger — discreet at rest, reveals label on
                card-hover. stopPropagation evite la navigation parasite
                vers /donnees ou /carte. */}
            <button
              type="button"
              onClick={handleSamExplain}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleSamExplain(e);
                }
              }}
              aria-label={SAM_EXPLAIN_TOOLTIP}
              title={SAM_EXPLAIN_TOOLTIP}
              data-sam-explain={mode.key}
              className={cn(
                "group/sam inline-flex items-center gap-1.5 rounded-md",
                "px-1.5 py-1 border border-white/[0.06] bg-white/[0.02]",
                "text-text-subtle hover:text-cyan-200",
                "hover:border-cyan-400/40 hover:bg-cyan-500/[0.08]",
                "opacity-60 hover:opacity-100",
                "transition-all duration-200 ease-out",
                "hover:scale-[1.04]",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950 focus-visible:opacity-100",
                "cursor-pointer"
              )}
            >
              <Info
                className="h-3.5 w-3.5 shrink-0"
                strokeWidth={1.75}
                aria-hidden
              />
              <span className="hidden md:inline text-[10px] font-mono tracking-wide uppercase whitespace-nowrap max-w-0 group-hover/sam:max-w-[120px] focus-visible:max-w-[120px] overflow-hidden transition-[max-width] duration-200 ease-out">
                {SAM_EXPLAIN_LABEL}
              </span>
            </button>
            <span
              className={cn(
                "font-mono text-[10px] tracking-widest uppercase px-2 py-0.5 rounded-md border bg-white/[0.02]",
                CHIP_BORDER[mode.accent]
              )}
            >
              {mode.shortTitle}
            </span>
          </div>
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
