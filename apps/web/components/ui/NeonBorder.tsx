"use client";

/** Bordure neon animee : box-shadow pulse + gradient border conic. */
import { useRef, type HTMLAttributes, type ReactNode } from "react";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";
import { cn } from "@/lib/utils";

export type NeonTone = "amber" | "cyan" | "violet" | "accent" | "success" | "danger";

export interface NeonBorderProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  tone?: NeonTone;
  /** Vitesse de la pulsation (s). Defaut 2.8. */
  speed?: number;
  /** Epaisseur de la bordure en px. Defaut 1. */
  thickness?: number;
  /** Active la rotation conic du gradient. Defaut true. */
  rotate?: boolean;
}

const TONE: Record<NeonTone, { core: string; halo: string }> = {
  amber: { core: "#f59e0b", halo: "rgba(245,158,11,0.55)" },
  cyan: { core: "#06b6d4", halo: "rgba(6,182,212,0.55)" },
  violet: { core: "#8b5cf6", halo: "rgba(139,92,246,0.55)" },
  accent: { core: "#6366f1", halo: "rgba(99,102,241,0.55)" },
  success: { core: "#10b981", halo: "rgba(16,185,129,0.55)" },
  danger: { core: "#ef4444", halo: "rgba(239,68,68,0.55)" },
};

export function NeonBorder({
  children,
  tone = "accent",
  speed = 2.8,
  thickness = 1,
  rotate = true,
  className,
  ...rest
}: NeonBorderProps) {
  const ringRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const palette = TONE[tone];

  useGSAP(
    () => {
      const ring = ringRef.current;
      const wrap = wrapRef.current;
      if (!ring || !wrap) return;
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        if (rotate) {
          gsap.to(ring, { rotate: 360, duration: 8, ease: "none", repeat: -1 });
        }
        gsap.to(wrap, {
          boxShadow: `0 0 24px ${palette.halo}, 0 0 1px ${palette.core}`,
          duration: speed,
          ease: "sine.inOut",
          yoyo: true,
          repeat: -1,
        });
      });
    },
    { scope: wrapRef, dependencies: [tone, speed, rotate] }
  );

  return (
    <div
      ref={wrapRef}
      className={cn("relative isolate rounded-lg", className)}
      style={{
        boxShadow: `0 0 12px ${palette.halo}`,
      }}
      {...rest}
    >
      {/* Anneau gradient anime (sous le contenu) */}
      <div
        ref={ringRef}
        aria-hidden
        className="pointer-events-none absolute -inset-px -z-10 rounded-[inherit]"
        style={{
          padding: thickness,
          background: `conic-gradient(from 0deg, ${palette.core}, transparent 30%, ${palette.halo} 60%, ${palette.core} 100%)`,
          WebkitMask:
            "linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)",
          WebkitMaskComposite: "xor",
          maskComposite: "exclude",
        }}
      />
      {/* Fond interne sobre */}
      <div className="relative rounded-[inherit] bg-bg-elevated/85 backdrop-blur-sm">
        {children}
      </div>
    </div>
  );
}
