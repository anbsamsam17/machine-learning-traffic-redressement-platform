"use client";

/** Texte avec gradient shimmer en boucle (passe gauche -> droite).
 *  Variants : gold, cyan, white, accent, neon-white.
 *  - neon-white : blanc sobre + tres leger halo lavande (style Linear/Vercel/Apple).
 *    Sweep ralenti (~5.5s) et opacite reduite pour rester discret.
 */
import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";

export type ShimmerVariant = "gold" | "cyan" | "white" | "accent" | "neon-white";

export interface ShimmerTextProps {
  children: ReactNode;
  variant?: ShimmerVariant;
  /** Element rendu. Defaut "span". */
  as?: "span" | "p" | "h1" | "h2" | "h3" | "h4" | "div";
  /** Duree d'un cycle en secondes. Defaut 3.5 (5.5 pour neon-white). */
  duration?: number;
  className?: string;
}

const PALETTE: Record<ShimmerVariant, { base: string; shine: string }> = {
  gold: { base: "#a16207", shine: "#f59e0b" },
  cyan: { base: "#0e7490", shine: "#22d3ee" },
  white: { base: "#71717a", shine: "#fafafa" },
  accent: { base: "#4f46e5", shine: "#a5b4fc" },
  // neon-white : base blanc casse, shine lavande tres legere -> sweep
  // a peine perceptible (contraste tres bas), parfait pour un titre sobre.
  "neon-white": { base: "#fafafa", shine: "rgba(165, 180, 252, 0.85)" },
};

// Halo neon (text-shadow) reserve au variant neon-white. Volontairement
// faible : ~0.22 d'opacite sur le halo blanc, ~0.10 sur le halo lavande,
// rayons modestes (12px / 24px). Si ca devient trop visible, baisse encore.
const NEON_WHITE_TEXT_SHADOW =
  "0 0 12px rgba(255, 255, 255, 0.22), 0 0 24px rgba(165, 180, 252, 0.10)";

export function ShimmerText({
  children,
  variant = "gold",
  as: Tag = "span",
  duration,
  className,
}: ShimmerTextProps) {
  const palette = PALETTE[variant];
  const isNeonWhite = variant === "neon-white";
  const effectiveDuration = duration ?? (isNeonWhite ? 5.5 : 3.5);

  // Note: les @keyframes shimmer-slide et l'override reduced-motion sont
  // declares dans globals.css pour eviter de polluer textContent du tag
  // (regression a11y/SEO observee quand le <style> etait enfant du <Tag>).
  const style: CSSProperties = {
    backgroundImage: `linear-gradient(110deg, ${palette.base} 0%, ${palette.base} 40%, ${palette.shine} 50%, ${palette.base} 60%, ${palette.base} 100%)`,
    backgroundSize: "250% 100%",
    backgroundClip: "text",
    WebkitBackgroundClip: "text",
    color: "transparent",
    WebkitTextFillColor: "transparent",
    animation: `shimmer-slide ${effectiveDuration}s linear infinite`,
  };

  if (isNeonWhite) {
    // Halo neon discret. La classe .shimmer-text-neon dans globals.css
    // gere le fallback prefers-reduced-motion (skip sweep, garde le halo).
    style.textShadow = NEON_WHITE_TEXT_SHADOW;
  }

  return (
    <Tag
      className={cn(
        "shimmer-text inline-block font-semibold",
        isNeonWhite && "shimmer-text-neon",
        className
      )}
      style={style}
    >
      {children}
    </Tag>
  );
}
