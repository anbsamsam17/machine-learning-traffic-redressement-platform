"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { hoverLift, hoverReset, countTo } from "@/lib/animations/gsap";
import type { ReactNode } from "react";

interface StatCardProps {
  label: string;
  value: string | number;
  icon?: ReactNode;
  trend?: "up" | "down" | "neutral";
  className?: string;
  /**
   * When set, animates the displayed value from 0 to `tween.to` using GSAP
   * (M3 counter). `tween.format` controls the rendered text on each frame.
   * Respects prefers-reduced-motion via the helper.
   */
  tween?: {
    to: number;
    format: (n: number) => string;
    /** Re-trigger key — change this to re-run the animation. */
    key?: string | number;
  };
}

export function StatCard({
  label,
  value,
  icon,
  trend,
  className,
  tween,
}: StatCardProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const valueRef = useRef<HTMLParagraphElement>(null);

  // M3 — count-to tween whenever `tween.key` changes.
  useEffect(() => {
    if (!tween || !valueRef.current) return;
    const animation = countTo(valueRef.current, tween.to, tween.format);
    return () => {
      animation.kill();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tween?.to, tween?.key]);

  return (
    <div
      ref={rootRef}
      onMouseEnter={() => rootRef.current && hoverLift(rootRef.current)}
      onMouseLeave={() => rootRef.current && hoverReset(rootRef.current)}
      className={cn(
        "stat-card surface-elevated p-4 flex items-start gap-3 transition-colors hover:border-border-strong",
        className
      )}
    >
      {icon && (
        <div className="shrink-0 w-8 h-8 rounded bg-accent-subtle flex items-center justify-center text-accent [&_svg]:size-4">
          {icon}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="text-[11px] uppercase tracking-wide text-text-muted truncate">
          {label}
        </p>
        <p
          ref={valueRef}
          className={cn(
            "font-mono text-xl font-semibold mt-1 tabular-nums leading-none",
            trend === "up" && "text-success",
            trend === "down" && "text-danger",
            !trend && "text-text"
          )}
          aria-live="polite"
        >
          {value}
        </p>
      </div>
    </div>
  );
}
