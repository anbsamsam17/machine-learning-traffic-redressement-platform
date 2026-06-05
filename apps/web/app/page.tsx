"use client";

/**
 * Landing dashboard — post-connexion entry point.
 *
 * Layout (Data-Dense Dashboard direction):
 *   ┌───────────────────────────────────────────────────────┐
 *   │  Header (rendered globally in app/layout.tsx)         │
 *   ├───────────────────────────────────────────────────────┤
 *   │  Hero (eyebrow + title + subtitle + tagline)          │
 *   │  QuickStats (4-up band, mono tabular-nums)            │
 *   │  ┌─ ModesGrid (2×2) ────────┬─ RecentActivity ──────┐ │
 *   │  │  TV / PL / Carte / Compt │  3-4 sober list items │ │
 *   │  └──────────────────────────┴───────────────────────┘ │
 *   │  Footer (legal one-liner)                             │
 *   ├───────────────────────────────────────────────────────┤
 *   │  Sam floating card (fixed bottom-right)               │
 *   │  LandingBg animated background (behind everything)    │
 *   └───────────────────────────────────────────────────────┘
 *
 * The three external modules expected from sibling agents
 * (`@/lib/content/landing`, `@/components/avatar/SamAvatar`,
 *  `@/components/landing/animations/LandingBg`) are not yet merged.
 * To keep `next build` green, we declare local fallback stubs below and
 * use them as the runtime values. Once those agents land their files, the
 * stubs can be swapped for real imports without touching the composition.
 */

import { useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";
import {
  Car,
  Truck,
  Sunrise,
  Sunset,
  Map as MapIcon,
  Activity,
  MapPinned,
  AlertCircle,
  GitCompareArrows,
  type LucideIcon,
} from "lucide-react";
import { useAppStore, type AppMode } from "@/lib/store";
import { samMood } from "@/lib/sam/store";
import { getPageMessage } from "@/lib/sam/page-messages";
import { HeroPremium } from "@/components/landing/HeroPremium";
import { ModesGridPremium } from "@/components/landing/ModesGridPremium";
import { QuickStats } from "@/components/landing/QuickStats";
import { RecentActivity } from "@/components/landing/RecentActivity";
import type {
  LandingContent,
  LandingMode,
  LandingModeContent,
} from "@/components/landing/types";
import { TrafficVideoBg } from "@/components/landing/animations/TrafficVideoBg";
import { RevealOnScroll } from "@/components/ui";
import { landingContent as R } from "@/lib/content/landing";

// ─────────────────────────────────────────────────────────────────────────────
// Adapter — bridges R's content shape with UI's component contracts.
// R: { hero.{title,subtitle,...}, modes[].id, footer.helpLink, activity.kind }
// UI: { title/subtitle flat, modes[].key+accent+icon, footer.helpLabel/Href, activity.id+kind }
// ─────────────────────────────────────────────────────────────────────────────

const MODE_VISUAL: Record<
  string,
  { accent: LandingModeContent["accent"]; icon: LucideIcon }
> = {
  tv: { accent: "indigo", icon: Car as LucideIcon },
  pl: { accent: "amber", icon: Truck as LucideIcon },
  // HPM — lever du soleil, palette rose chaude.
  hpm: { accent: "rose", icon: Sunrise as LucideIcon },
  // HPS — coucher du soleil, palette violet/magenta.
  hps: { accent: "violet", icon: Sunset as LucideIcon },
  carte: { accent: "cyan", icon: MapIcon as LucideIcon },
  compteurs: { accent: "emerald", icon: Activity as LucideIcon },
  visualisation: { accent: "cyan", icon: MapPinned as LucideIcon },
  discontinuites: { accent: "amber", icon: AlertCircle as LucideIcon },
  // Evolution inter-annuelle — comparaison T1/T2, palette divergente, accent indigo.
  evolution: { accent: "indigo", icon: GitCompareArrows as LucideIcon },
};

const KIND_MAP: Record<string, "training" | "map" | "compteurs" | "report"> = {
  training: "training",
  carte: "map",
  compteurs: "compteurs",
  eval: "report",
};

function buildContent(): LandingContent {
  const modes: LandingModeContent[] = R.modes.map((m) => ({
    key: m.id as LandingMode,
    shortTitle: m.shortTitle,
    title: m.title,
    tagline: m.tagline,
    description: m.description,
    keyMetrics: [...m.keyMetrics],
    accent: MODE_VISUAL[m.id].accent,
    icon: MODE_VISUAL[m.id].icon,
    cta: m.cta,
  }));

  return {
    eyebrow: R.hero.eyebrow,
    title: R.hero.title,
    subtitle: R.hero.subtitle,
    tagline: R.hero.tagline,
    modes,
    quickStats: R.quickStats.map((s) => ({ ...s })),
    recentActivity: R.recentActivity.map((a, i) => ({
      id: `r${i + 1}`,
      kind: KIND_MAP[a.kind] ?? "training",
      title: a.title,
      status: a.status as "success" | "pending" | "error",
      time: a.time,
    })),
    sam: {
      welcomeBubble: R.sam.welcomeBubble,
      welcomeSubtitle: R.sam.welcomeSubtitle,
    },
    footer: {
      legal: R.footer.legal,
      helpLabel: R.footer.helpLink.label,
      helpHref: R.footer.helpLink.href,
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Mode routing
// ─────────────────────────────────────────────────────────────────────────────

const MODE_PATH: Record<LandingMode, string> = {
  tv: "/donnees",
  pl: "/donnees",
  hpm: "/donnees",
  hps: "/donnees",
  carte: "/carte",
  compteurs: "/compteurs",
  visualisation: "/visualisation",
  discontinuites: "/discontinuites",
  evolution: "/evolution",
};

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

export default function HomePage() {
  const router = useRouter();
  const setMode = useAppStore((s) => s.setMode);
  const reset = useAppStore((s) => s.reset);

  // Re-build the fallback content once per mount. Stable identity is enough
  // for the children — no expensive transforms here.
  const content = useMemo<LandingContent>(() => buildContent(), []);

  // Force-reset Sam's mood to the landing's "welcome" entry on every mount.
  // SamPageBinder already does this on pathname change, but a stale toast
  // (`setMoodOnly` with an autoResetMs setTimeout queued by a samNotify on
  // a previous page like /donnees) can fire after navigation and overwrite
  // the binder's mood back to "based". Re-asserting the landing entry here,
  // after the binder's effect, guarantees Sam always greets with "welcome"
  // on the landing — see QA report APP-P1-1 / QA_B1 §P1-2.
  useEffect(() => {
    const entry = getPageMessage("/");
    if (entry) {
      samMood.set(entry.mood, entry.message);
    } else {
      samMood.set("welcome");
    }
  }, []);

  function handleModeSelect(key: LandingMode) {
    reset();
    setMode(key as Exclude<AppMode, null>);
    router.push(MODE_PATH[key]);
  }

  return (
    <>
      {/* Animated background (full-viewport, behind everything).
          TrafficVideoBg combine une video loop (traffic-bg.mp4) + un
          overlay SVG (2 noeuds smart + 12 packets cyan/indigo en arcs
          Bezier + 12 transmissions pointillees ephemeres) anime via GSAP.
          Strict pointer-events-none / -z-10 / aria-hidden, et desactive
          les animations sous prefers-reduced-motion (la video reste). */}
      <TrafficVideoBg />

      {/* Avoid nested <main> — the root layout already wraps children in
          <main id="main-content">. We use a <div> here with a region label
          for screen readers. */}
      <div
        id="landing"
        className="relative z-10 mx-auto w-full max-w-[1400px] px-4 sm:px-6 lg:px-10 pb-24"
      >
        {/* Hero — no CTA: the ModesGrid below provides clear entry points. */}
        <HeroPremium
          eyebrow={content.eyebrow}
          title={content.title}
          subtitle={content.subtitle}
          tagline={content.tagline}
        />

        {/* Quick stats band — masquee tant qu'aucune source agregee fiable n'existe.
            Voir backend: pas d'endpoint global d'agregation des modeles par
            utilisateur. Plutot que d'afficher des valeurs arbitraires, on n'affiche
            rien jusqu'a ce qu'un endpoint reel soit disponible. */}
        {content.quickStats.length > 0 && <QuickStats stats={content.quickStats} />}

        {/* Pour info — annonce le bouton "Resume par Sam" present sur chaque card.
            Italique discret, couleur zinc-200 + double text-shadow (style
            sous-titre video) pour rester lisible hors-card quelle que soit
            la luminosite de la frame video derriere. */}
        <p
          className="mt-6 italic text-sm leading-relaxed text-zinc-200"
          role="note"
          style={{
            textShadow:
              "0 1px 8px rgba(0,0,0,0.9), 0 0 18px rgba(0,0,0,0.55)",
          }}
        >
          Pour info : clique sur le bouton{" "}
          <span
            className="not-italic font-semibold text-cyan-300"
            style={{
              textShadow:
                "0 0 12px rgba(34,211,238,0.45), 0 1px 8px rgba(0,0,0,0.85)",
            }}
          >
            Resume par Sam
          </span>{" "}
          present sur chaque module pour que Sam te detaille le contenu dans
          sa bulle.
        </p>

        {/* Modes grid + activity sidebar */}
        <section className="mt-4 grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-8">
          <ModesGridPremium modes={content.modes} onSelect={handleModeSelect} />
          <div className="space-y-6">
            <RevealOnScroll variant="fade" stagger={0.12} delay={0.25}>
              <div data-reveal>
                <RecentActivity items={content.recentActivity} />
              </div>
            </RevealOnScroll>
          </div>
        </section>

        {/* Footer — hors-card sur la video : couleurs renforcees + text-shadow
            pour rester lisible sur n'importe quelle frame. */}
        <footer className="mt-16 pt-6 border-t border-white/[0.08] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
          <p
            className="text-[11px] text-zinc-300"
            style={{ textShadow: "0 1px 8px rgba(0,0,0,0.9)" }}
          >
            {content.footer.legal}
          </p>
          {content.footer.helpLabel && content.footer.helpHref && (
            <a
              href={content.footer.helpHref}
              className="text-[11px] text-zinc-200 hover:text-white transition-colors"
              style={{ textShadow: "0 1px 8px rgba(0,0,0,0.9)" }}
            >
              {content.footer.helpLabel} →
            </a>
          )}
        </footer>
      </div>

      {/* SamWidget is mounted globally in app/layout.tsx, no per-page SamZone. */}
    </>
  );
}
