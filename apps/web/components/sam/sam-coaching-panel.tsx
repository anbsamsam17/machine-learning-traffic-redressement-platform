"use client";

/**
 * SamCoachingPanel — sits at the top of `/config`. Sam (mascot) welcomes the
 * user and surfaces audit-driven recommendations for calibrating the grid
 * search. Content lives in `lib/sam/coaching-content.ts` so the copy is
 * editable in one place.
 *
 * Behaviour:
 *   - Mounted as a static card (no toast, no global Sam-store mutation)
 *   - GSAP fade-in + slight bounce on mount (respects prefers-reduced-motion)
 *   - Advanced recommendations hidden behind a "Voir plus" toggle
 *   - Dismissible — choice persists in localStorage per coaching version
 */

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import gsap from "gsap";
import { cn } from "@/lib/utils";
import { SamAvatar } from "@/components/avatar/SamAvatar";
import {
  samConfigRecommendations,
  SAM_COACHING_VERSION,
} from "@/lib/sam/coaching-content";

const PREFERENCE = "(prefers-reduced-motion: no-preference)";
const STORAGE_KEY = `sam-coaching-config-dismissed-${SAM_COACHING_VERSION}`;

export function SamCoachingPanel() {
  // Avoid flash-of-content for users who already dismissed: start hidden until
  // we've read localStorage on mount.
  const [hydrated, setHydrated] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Hydration: read the dismissed flag and reveal.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "1") {
        setDismissed(true);
      }
    } catch {
      // localStorage may be unavailable (private mode, SSR mismatch) — ignore.
    }
    setHydrated(true);
  }, []);

  // Mount animation: fade in + soft scale bump. Respects reduced-motion.
  useEffect(() => {
    if (!hydrated || dismissed) return;
    const el = rootRef.current;
    if (!el) return;
    const mm = gsap.matchMedia();
    mm.add(PREFERENCE, () => {
      gsap.fromTo(
        el,
        { autoAlpha: 0, y: 8, scale: 0.99 },
        {
          autoAlpha: 1,
          y: 0,
          scale: 1,
          duration: 0.5,
          ease: "power2.out",
        }
      );
      return () => {
        gsap.set(el, { clearProps: "transform,opacity,visibility" });
      };
    });
    if (
      typeof window !== "undefined" &&
      !window.matchMedia(PREFERENCE).matches
    ) {
      gsap.set(el, { autoAlpha: 1, y: 0, scale: 1 });
    }
    return () => mm.revert();
  }, [hydrated, dismissed]);

  function handleDismiss() {
    setDismissed(true);
    try {
      window.localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      // ignore — best-effort persistence
    }
  }

  if (!hydrated || dismissed) return null;

  const { mainRecommendations, pitfalls, strategy, advancedRecommendations } =
    samConfigRecommendations;

  return (
    <div
      ref={rootRef}
      role="region"
      aria-label="Recommandations de Sam pour la configuration"
      className={cn(
        // Glass card — cyan/violet bordered, sits above the form.
        "relative overflow-hidden rounded-xl",
        "border border-cyan-400/30 bg-bg-elevated/70 backdrop-blur",
        "shadow-[0_10px_40px_-15px_rgba(34,211,238,0.25)]",
        "p-5 sm:p-6"
      )}
      style={{ opacity: 0 }}
    >
      {/* Subtle gradient halo behind the content */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-60"
        style={{
          background:
            "radial-gradient(60% 80% at 0% 0%, rgba(34, 211, 238, 0.10), transparent 60%), radial-gradient(50% 80% at 100% 100%, rgba(129, 140, 248, 0.10), transparent 60%)",
        }}
      />

      {/* Dismiss button */}
      <button
        type="button"
        onClick={handleDismiss}
        aria-label="Masquer les recommandations de Sam"
        className={cn(
          "absolute top-3 right-3 z-10",
          "inline-flex items-center justify-center size-7 rounded-md",
          "text-text-subtle hover:text-text hover:bg-bg-subtle",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          "transition-colors"
        )}
      >
        <X size={14} aria-hidden="true" />
      </button>

      <div className="relative flex gap-4 sm:gap-5">
        {/* Sam avatar — small, welcome mood */}
        <div className="shrink-0 hidden sm:block">
          <SamAvatar mood="welcome" size="sm" placement="inline" />
        </div>
        <div className="block sm:hidden shrink-0">
          <SamAvatar mood="welcome" size="sm" placement="inline" />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 space-y-4">
          <header className="space-y-1 pr-8">
            <h2 className="text-base sm:text-lg font-semibold text-text leading-tight">
              Voici mes recommandations pour ton grid…
            </h2>
            <p className="text-xs text-text-muted">
              Tous les champs ci-dessous ont une info-bulle dédiée
              (icône&nbsp;
              <span className="inline-block size-3 rounded-full border border-accent/50 align-middle" />
              ) pour creuser un par un.
            </p>
          </header>

          {/* Main recommendations */}
          <section aria-labelledby="sam-coaching-main">
            <h3
              id="sam-coaching-main"
              className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-text-muted mb-2"
            >
              <Sparkles size={12} aria-hidden="true" className="text-accent" />
              Recommandations principales
            </h3>
            <ul className="space-y-1.5">
              {mainRecommendations.map((rec) => (
                <li
                  key={rec.label}
                  className="text-xs text-text leading-relaxed flex gap-2"
                >
                  <span
                    aria-hidden="true"
                    className="mt-1 size-1.5 shrink-0 rounded-full bg-accent"
                  />
                  <span>
                    <span className="font-semibold text-text">
                      {rec.label}
                    </span>{" "}
                    <span className="text-text-muted">— {rec.body}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>

          {/* Pitfalls */}
          <section aria-labelledby="sam-coaching-pitfalls">
            <h3
              id="sam-coaching-pitfalls"
              className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-text-muted mb-2"
            >
              <AlertTriangle
                size={12}
                aria-hidden="true"
                className="text-warning"
              />
              Pièges à éviter
            </h3>
            <ul className="space-y-1.5">
              {pitfalls.map((p) => (
                <li
                  key={p.label}
                  className="text-xs text-text leading-relaxed flex gap-2"
                >
                  <span
                    aria-hidden="true"
                    className="mt-1 size-1.5 shrink-0 rounded-full bg-warning"
                  />
                  <span>
                    <span className="font-semibold text-text">
                      {p.label}
                    </span>{" "}
                    <span className="text-text-muted">— {p.body}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>

          {/* Strategy chips */}
          <section
            aria-labelledby="sam-coaching-strategy"
            className="rounded-lg border border-border bg-bg-subtle/40 p-3"
          >
            <h3
              id="sam-coaching-strategy"
              className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-text-muted mb-2"
            >
              <Target size={12} aria-hidden="true" className="text-accent" />
              Stratégie batch recommandée
            </h3>
            <div className="flex flex-wrap gap-1.5 mb-2">
              <StrategyChip>{strategy.models}</StrategyChip>
              <StrategyChip>{strategy.epochs}</StrategyChip>
              <StrategyChip>{strategy.batch}</StrategyChip>
            </div>
            <p className="text-[11px] text-text-subtle italic">
              {strategy.rationale}
            </p>
          </section>

          {/* Advanced recommendations (collapsed) */}
          <section>
            <button
              type="button"
              onClick={() => setAdvancedOpen((v) => !v)}
              aria-expanded={advancedOpen}
              aria-controls="sam-coaching-advanced"
              className={cn(
                "inline-flex items-center gap-1.5 text-xs",
                "text-accent hover:underline",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
              )}
            >
              <ChevronDown
                size={12}
                aria-hidden="true"
                className={cn(
                  "transition-transform duration-200",
                  advancedOpen && "rotate-180"
                )}
              />
              {advancedOpen
                ? "Masquer les recommandations avancées"
                : "Voir les recommandations avancées"}
            </button>
            {advancedOpen && (
              <ul
                id="sam-coaching-advanced"
                className="mt-2 space-y-1.5 border-l-2 border-accent/30 pl-3"
              >
                {advancedRecommendations.map((rec) => (
                  <li
                    key={rec.label}
                    className="text-xs text-text leading-relaxed"
                  >
                    <span className="font-semibold text-text">
                      {rec.label}
                    </span>{" "}
                    <span className="text-text-muted">— {rec.body}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function StrategyChip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center px-2 h-6 rounded text-[11px] font-mono font-medium bg-accent-subtle text-accent border border-accent/30">
      {children}
    </span>
  );
}

export default SamCoachingPanel;
