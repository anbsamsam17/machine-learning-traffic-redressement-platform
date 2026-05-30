"use client";

/** Card premium avec halo conic anime, fond glass et lift au hover (GSAP). */
import { useRef, type HTMLAttributes, type ReactNode } from "react";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";
import { cn } from "@/lib/utils";

export type GlowCardTone = "accent" | "amber" | "cyan" | "violet";

export interface GlowCardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  /** Couleur dominante du halo conic-gradient. Defaut "accent". */
  tone?: GlowCardTone;
  /** Intensite du halo (0..1). Defaut 0.6. */
  intensity?: number;
  /** Active le lift au survol. Defaut true. */
  interactive?: boolean;
}

const TONE: Record<GlowCardTone, { from: string; to: string; ring: string }> = {
  accent: {
    from: "rgba(99,102,241,0.55)",
    to: "rgba(99,102,241,0.05)",
    ring: "rgba(99,102,241,0.35)",
  },
  amber: {
    from: "rgba(245,158,11,0.55)",
    to: "rgba(245,158,11,0.05)",
    ring: "rgba(245,158,11,0.35)",
  },
  cyan: {
    from: "rgba(6,182,212,0.55)",
    to: "rgba(6,182,212,0.05)",
    ring: "rgba(6,182,212,0.35)",
  },
  violet: {
    from: "rgba(139,92,246,0.55)",
    to: "rgba(139,92,246,0.05)",
    ring: "rgba(139,92,246,0.35)",
  },
};

export function GlowCard({
  children,
  tone = "accent",
  intensity = 0.6,
  interactive = true,
  className,
  ...rest
}: GlowCardProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const haloRef = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const halo = haloRef.current;
      if (!halo) return;
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.to(halo, {
          rotate: 360,
          duration: 14,
          ease: "none",
          repeat: -1,
        });
      });
    },
    { scope: rootRef }
  );

  const palette = TONE[tone];
  const haloBg = `conic-gradient(from 0deg, ${palette.from}, ${palette.to} 40%, transparent 60%, ${palette.from} 100%)`;

  const onEnter = () => {
    if (!interactive || !rootRef.current) return;
    const mm = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mm.matches) return;
    gsap.to(rootRef.current, {
      y: -4,
      boxShadow: `0 24px 48px -24px ${palette.ring}, 0 0 0 1px ${palette.ring}`,
      duration: 0.25,
      ease: "power2.out",
    });
    if (haloRef.current) {
      gsap.to(haloRef.current, { opacity: intensity, duration: 0.25, ease: "power2.out" });
    }
  };
  const onLeave = () => {
    if (!interactive || !rootRef.current) return;
    const mm = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mm.matches) return;
    gsap.to(rootRef.current, {
      y: 0,
      boxShadow: "0 0 0 1px rgba(255,255,255,0.04)",
      duration: 0.3,
      ease: "power2.out",
    });
    if (haloRef.current) {
      gsap.to(haloRef.current, { opacity: intensity * 0.45, duration: 0.3, ease: "power2.out" });
    }
  };

  return (
    <div
      ref={rootRef}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      className={cn(
        "group relative isolate overflow-hidden rounded-lg",
        "bg-bg-elevated/70 backdrop-blur-md",
        "border border-border",
        "shadow-[0_0_0_1px_rgba(255,255,255,0.04)]",
        "will-change-transform",
        className
      )}
      {...rest}
    >
      {/* Halo conic anime — couche en dessous du contenu, opacite initiale partielle */}
      <div
        ref={haloRef}
        aria-hidden
        className="pointer-events-none absolute -inset-[40%] -z-10"
        style={{
          background: haloBg,
          opacity: intensity * 0.45,
          filter: "blur(40px)",
        }}
      />
      {/* Voile interne pour relever la lisibilite */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 rounded-lg"
        style={{
          background:
            "linear-gradient(180deg, rgba(9,9,11,0.55) 0%, rgba(9,9,11,0.78) 100%)",
        }}
      />
      <div className="relative p-5">{children}</div>
    </div>
  );
}
