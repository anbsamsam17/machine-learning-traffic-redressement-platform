"use client";

import { motion, useReducedMotion } from "framer-motion";
import { Sparkles, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface HeroLandingProps {
  eyebrow: string;
  title: string;
  subtitle: string;
  tagline: string;
  cta?: string;
  onCta?: () => void;
}

export function HeroLanding({
  eyebrow,
  title,
  subtitle,
  tagline,
  cta,
  onCta,
}: HeroLandingProps) {
  const reduce = useReducedMotion();

  return (
    <section
      aria-labelledby="hero-title"
      className="relative pt-10 pb-12 md:pt-14 md:pb-16"
    >
      <motion.div
        initial={reduce ? false : { opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        className="space-y-5 max-w-3xl"
      >
        {/* Eyebrow badge */}
        <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full border border-indigo-400/20 bg-indigo-500/10 backdrop-blur-sm">
          <Sparkles
            className="h-3 w-3 text-indigo-300"
            strokeWidth={2}
            aria-hidden
          />
          <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-indigo-200/90">
            {eyebrow}
          </span>
        </div>

        {/* Title */}
        <h1
          id="hero-title"
          className={cn(
            "font-sans font-bold tracking-tight text-zinc-50",
            "text-4xl md:text-5xl lg:text-6xl",
            "leading-[1.05]"
          )}
        >
          {title}
        </h1>

        {/* Subtitle (masque si chaine vide) */}
        {subtitle && (
          <p className="text-base md:text-lg text-zinc-300/90 max-w-2xl leading-relaxed">
            {subtitle}
          </p>
        )}

        {/* Tagline + CTA row */}
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3 pt-2">
          <p className="text-sm text-zinc-500 max-w-xl">{tagline}</p>
          {cta && (
            <button
              type="button"
              onClick={onCta}
              className={cn(
                "inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg",
                "text-xs font-medium tracking-wide",
                "bg-indigo-500/15 hover:bg-indigo-500/25 text-indigo-200",
                "border border-indigo-400/25 hover:border-indigo-400/40",
                "transition-all",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60"
              )}
            >
              {cta}
              <ArrowRight className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
            </button>
          )}
        </div>
      </motion.div>
    </section>
  );
}
