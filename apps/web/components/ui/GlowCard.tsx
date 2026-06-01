"use client";

/** Card premium avec halo conic anime, fond glass et lift au hover (GSAP). */
import { useRef, type HTMLAttributes, type ReactNode } from "react";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";
import { cn } from "@/lib/utils";

export type GlowCardTone = "accent" | "amber" | "cyan" | "violet";

/**
 * Variants de fond de card.
 * - "default"          : voile sombre quasi-opaque (legacy, base zinc-950 ~75%)
 * - "translucent-video": fond rgba(9,9,11,0.55) + backdrop-blur(24px) saturate(150%).
 *   Pensé pour reposer au-dessus d'un background video sans masquer la scene
 *   tout en gardant le texte AAA grace au voile sombre + saturate qui aplatit
 *   les couleurs vives de la video.
 */
export type GlowCardVariant = "default" | "translucent-video";

export interface GlowCardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  /** Couleur dominante du halo conic-gradient. Defaut "accent". */
  tone?: GlowCardTone;
  /** Intensite du halo (0..1). Defaut 0.6. */
  intensity?: number;
  /** Active le lift au survol. Defaut true. */
  interactive?: boolean;
  /**
   * Variante de fond (Defaut "default").
   * Voir {@link GlowCardVariant} pour les valeurs autorisees.
   */
  variant?: GlowCardVariant;
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
  variant = "default",
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

  // Translucent-video variant : on remplace le voile interne sombre (qui
  // masquerait la video) par un fond rgba + backdrop-blur applique sur le
  // wrapper directement. La bordure est legerement renforcee + un inset
  // highlight pour conserver le "verre" premium au-dessus de la video.
  const isTranslucent = variant === "translucent-video";
  const wrapperStyle = isTranslucent
    ? {
        background: "rgba(9, 9, 11, 0.55)",
        backdropFilter: "blur(24px) saturate(150%)",
        WebkitBackdropFilter: "blur(24px) saturate(150%)",
        borderColor: "rgba(255,255,255,0.10)",
        boxShadow:
          "0 1px 0 rgba(255,255,255,0.08) inset, 0 0 0 1px rgba(99,102,241,0.12), 0 28px 80px -20px rgba(0,0,0,0.7), 0 0 60px -10px rgba(99,102,241,0.18)",
      }
    : undefined;

  // Shadows : on hover on conserve le glow ring tinte. En mode translucent,
  // on garde l'inset highlight + glow indigo de base pour ne pas perdre
  // le look "verre" au repos.
  const shadowRest = isTranslucent
    ? "0 1px 0 rgba(255,255,255,0.08) inset, 0 0 0 1px rgba(99,102,241,0.12), 0 28px 80px -20px rgba(0,0,0,0.7), 0 0 60px -10px rgba(99,102,241,0.18)"
    : "0 0 0 1px rgba(255,255,255,0.04)";
  const shadowHover = isTranslucent
    ? `0 1px 0 rgba(255,255,255,0.08) inset, 0 0 0 1px ${palette.ring}, 0 32px 90px -20px rgba(0,0,0,0.8), 0 0 70px -10px ${palette.from}`
    : `0 24px 48px -24px ${palette.ring}, 0 0 0 1px ${palette.ring}`;

  const onEnter = () => {
    if (!interactive || !rootRef.current) return;
    const mm = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mm.matches) return;
    gsap.to(rootRef.current, {
      y: -4,
      boxShadow: shadowHover,
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
      boxShadow: shadowRest,
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
        // Le fond glass legacy est conserve pour la variante "default" ;
        // la variante translucent-video pilote son fond via wrapperStyle.
        !isTranslucent && "bg-bg-elevated/70 backdrop-blur-md",
        "border border-border",
        !isTranslucent && "shadow-[0_0_0_1px_rgba(255,255,255,0.04)]",
        "will-change-transform",
        className
      )}
      style={wrapperStyle}
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
      {/* Voile interne pour relever la lisibilite — uniquement en mode default.
          La variante translucent-video utilise rgba(9,9,11,0.55) + backdrop-blur
          sur le wrapper directement, donc pas besoin de re-cumuler un voile. */}
      {!isTranslucent && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-10 rounded-lg"
          style={{
            background:
              "linear-gradient(180deg, rgba(9,9,11,0.55) 0%, rgba(9,9,11,0.78) 100%)",
          }}
        />
      )}
      <div className="relative p-5">{children}</div>
    </div>
  );
}
