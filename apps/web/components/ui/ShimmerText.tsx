"use client";

/** Texte avec gradient shimmer en boucle (passe gauche -> droite). Variants gold, cyan, white, accent. */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type ShimmerVariant = "gold" | "cyan" | "white" | "accent";

export interface ShimmerTextProps {
  children: ReactNode;
  variant?: ShimmerVariant;
  /** Element rendu. Defaut "span". */
  as?: "span" | "p" | "h1" | "h2" | "h3" | "h4" | "div";
  /** Duree d'un cycle en secondes. Defaut 3.5. */
  duration?: number;
  className?: string;
}

const PALETTE: Record<ShimmerVariant, { base: string; shine: string }> = {
  gold: { base: "#a16207", shine: "#f59e0b" },
  cyan: { base: "#0e7490", shine: "#22d3ee" },
  white: { base: "#71717a", shine: "#fafafa" },
  accent: { base: "#4f46e5", shine: "#a5b4fc" },
};

export function ShimmerText({
  children,
  variant = "gold",
  as: Tag = "span",
  duration = 3.5,
  className,
}: ShimmerTextProps) {
  const palette = PALETTE[variant];

  // Note: les @keyframes shimmer-slide et l'override reduced-motion sont
  // declares dans globals.css pour eviter de polluer textContent du tag
  // (regression a11y/SEO observee quand le <style> etait enfant du <Tag>).
  return (
    <Tag
      className={cn("shimmer-text inline-block font-semibold", className)}
      style={{
        backgroundImage: `linear-gradient(110deg, ${palette.base} 0%, ${palette.base} 40%, ${palette.shine} 50%, ${palette.base} 60%, ${palette.base} 100%)`,
        backgroundSize: "250% 100%",
        backgroundClip: "text",
        WebkitBackgroundClip: "text",
        color: "transparent",
        WebkitTextFillColor: "transparent",
        animation: `shimmer-slide ${duration}s linear infinite`,
      }}
    >
      {children}
    </Tag>
  );
}
