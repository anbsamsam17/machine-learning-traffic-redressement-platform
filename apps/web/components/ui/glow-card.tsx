"use client";

/**
 * Compat shim — original GlowCard had glassmorphism + neon glow.
 * Replaced with the sober Card (surface-elevated + border, no glow).
 * The `glowColor` prop is accepted but ignored.
 */
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface GlowCardProps {
  children: ReactNode;
  className?: string;
  glowColor?: "accent" | "cyan" | "violet";
  onClick?: () => void;
}

export function GlowCard({
  children,
  className,
  glowColor: _glowColor,
  onClick,
}: GlowCardProps) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "surface-elevated p-5 text-text transition-colors",
        onClick &&
          "cursor-pointer hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        className
      )}
    >
      {children}
    </div>
  );
}

/** New primary export: prefer `<Card>` in new code */
export const Card = GlowCard;
