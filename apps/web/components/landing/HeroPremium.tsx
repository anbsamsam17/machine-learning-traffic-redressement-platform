"use client";

/**
 * HeroPremium — landing hero using UX5 primitives.
 *
 * - Eyebrow pill (sober chip, mono)
 * - Title via ShimmerText (gold gradient sweeping slowly)
 * - Tagline (text-text-muted, max-width respiré)
 * - Optional CTA via MagneticButton
 *
 * Server-safe: only the leaf primitives are "use client".
 */

import { ArrowRight, Sparkles } from "lucide-react";
import {
  MagneticButton,
  RevealOnScroll,
  ShimmerText,
} from "@/components/ui";
import { cn } from "@/lib/utils";

interface HeroPremiumProps {
  eyebrow: string;
  title: string;
  subtitle?: string;
  tagline: string;
  cta?: string;
  onCta?: () => void;
}

export function HeroPremium({
  eyebrow,
  title,
  subtitle,
  tagline,
  cta,
  onCta,
}: HeroPremiumProps) {
  return (
    <section
      aria-labelledby="hero-title"
      className="relative pt-12 pb-14 md:pt-16 md:pb-20"
    >
      <RevealOnScroll variant="slide-up" stagger={0.12} distance={20}>
        {/* Eyebrow */}
        <div data-reveal>
          <span
            className={cn(
              "inline-flex items-center gap-2 px-3 py-1 rounded-full",
              "border border-accent/25 bg-accent-subtle backdrop-blur-sm"
            )}
          >
            <Sparkles
              className="h-3 w-3 text-accent"
              strokeWidth={2}
              aria-hidden
            />
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-accent">
              {eyebrow}
            </span>
          </span>
        </div>

        {/* Title — ShimmerText gold, large display */}
        <h1
          id="hero-title"
          data-reveal
          className={cn(
            "mt-5 font-sans font-bold tracking-tight",
            "text-4xl md:text-5xl lg:text-[3.5rem]",
            "leading-[1.05] max-w-4xl"
          )}
        >
          <ShimmerText as="span" variant="neon-white" duration={5.5}>
            {title}
          </ShimmerText>
        </h1>

        {/* Subtitle */}
        {subtitle && (
          <p
            data-reveal
            className="mt-4 text-base md:text-lg text-text-muted max-w-2xl leading-relaxed"
          >
            {subtitle}
          </p>
        )}

        {/* Tagline + CTA */}
        <div
          data-reveal
          className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-4"
        >
          <p className="text-sm text-text-subtle max-w-xl leading-relaxed">
            {tagline}
          </p>
          {cta && (
            <MagneticButton
              type="button"
              variant="primary"
              size="md"
              onClick={onCta}
              className="uppercase tracking-wider text-xs"
            >
              {cta}
              <ArrowRight className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
            </MagneticButton>
          )}
        </div>
      </RevealOnScroll>
    </section>
  );
}
