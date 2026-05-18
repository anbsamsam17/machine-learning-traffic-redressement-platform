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
import { useMemo } from "react";
import {
  Brain,
  Truck,
  Map as MapIcon,
  Activity,
  type LucideIcon,
} from "lucide-react";
import { useAppStore, type AppMode } from "@/lib/store";
import { HeroLanding } from "@/components/landing/HeroLanding";
import { ModesGrid } from "@/components/landing/ModesGrid";
import { QuickStats } from "@/components/landing/QuickStats";
import { RecentActivity } from "@/components/landing/RecentActivity";
import { SamZone, type SamAvatarProps } from "@/components/landing/SamZone";
import type {
  LandingContent,
  LandingMode,
  LandingModeContent,
} from "@/components/landing/types";

// ─────────────────────────────────────────────────────────────────────────────
// FALLBACK STUBS — to be replaced once sibling agents merge their modules.
// Keep this block tightly scoped so the swap is a single import line each.
// ─────────────────────────────────────────────────────────────────────────────

/** Stub for `@/components/avatar/SamAvatar` (agent SAM). */
function SamAvatarStub({ message, subtitle }: SamAvatarProps) {
  return (
    <div className="flex items-start gap-3">
      <div
        aria-hidden
        className="h-10 w-10 shrink-0 rounded-full bg-gradient-to-br from-indigo-400 to-cyan-400 flex items-center justify-center font-mono text-xs font-bold text-zinc-900"
      >
        S
      </div>
      <div className="min-w-0">
        <p className="text-xs font-medium text-zinc-100">{message}</p>
        {subtitle && (
          <p className="mt-0.5 text-[10px] text-zinc-400">{subtitle}</p>
        )}
      </div>
    </div>
  );
}

/** Stub for `@/components/landing/animations/LandingBg` (agent BG-LANDING). */
function LandingBgStub() {
  return (
    <div
      aria-hidden
      className="bg-landing pointer-events-none fixed inset-0 -z-10"
    />
  );
}

/** Stub for `@/lib/content/landing` (agent R). */
function buildFallbackContent(): LandingContent {
  const modes: LandingModeContent[] = [
    {
      key: "tv",
      shortTitle: "TV",
      title: "Modele TV",
      tagline: "Tous Vehicules",
      description:
        "Pipeline complet d'entrainement et d'evaluation du modele de redressement pour les vehicules legers.",
      keyMetrics: ["MLP · XGB · RF", "Grid-search", "5-fold CV"],
      accent: "indigo",
      icon: Brain as LucideIcon,
      cta: "Lancer l'analyse",
    },
    {
      key: "pl",
      shortTitle: "PL",
      title: "Modele PL",
      tagline: "Poids Lourds",
      description:
        "Meme pipeline calibre pour les flux poids-lourds — moins de stations, plus de variance.",
      keyMetrics: ["MLP · XGB · RF", "Stratifie", "5-fold CV"],
      accent: "amber",
      icon: Truck as LucideIcon,
      cta: "Lancer l'analyse",
    },
    {
      key: "carte",
      shortTitle: "CARTE",
      title: "Carte de debits",
      tagline: "Visualisation reseau",
      description:
        "Generation cartographique des debits redresses sur le reseau routier — export GeoJSON / tuiles.",
      keyMetrics: ["MapLibre", "GeoJSON", "Tuiles MBTiles"],
      accent: "cyan",
      icon: MapIcon as LucideIcon,
      cta: "Ouvrir la carte",
    },
    {
      key: "compteurs",
      shortTitle: "CPTRS",
      title: "Boucles de comptage",
      tagline: "Compteurs virtuels",
      description:
        "Construction des boucles de comptage virtuelles a partir des modeles entraines.",
      keyMetrics: ["Sectionnement", "Agregation H", "Export CSV"],
      accent: "emerald",
      icon: Activity as LucideIcon,
      cta: "Generer les boucles",
    },
  ];

  return {
    eyebrow: "Plateforme interne · v2.0",
    title: "Outils Data Engineering · Etudes Trafic",
    subtitle:
      "Une station de travail unifiee pour le redressement FCD : import, calibration, evaluation multi-modeles et livrables cartographiques.",
    tagline:
      "Tous les calculs s'executent sur le serveur. Vos donnees restent dans votre espace.",
    modes,
    quickStats: [
      { label: "Modeles", value: "3", hint: "MLP · XGB · RF" },
      { label: "Sessions", value: "12", hint: "30 derniers jours" },
      { label: "Stations", value: "248", hint: "TV + PL confondus" },
      { label: "Uptime API", value: "99.9%", hint: "Rolling 7j" },
    ],
    recentActivity: [
      {
        id: "a1",
        kind: "training",
        title: "Entrainement TV · grid-search complet",
        status: "success",
        time: "il y a 12 min",
      },
      {
        id: "a2",
        kind: "map",
        title: "Carte de debits · export GeoJSON",
        status: "success",
        time: "il y a 1 h",
      },
      {
        id: "a3",
        kind: "compteurs",
        title: "Boucles virtuelles · departement 75",
        status: "pending",
        time: "il y a 3 h",
      },
      {
        id: "a4",
        kind: "report",
        title: "Rapport d'evaluation PL",
        status: "success",
        time: "hier",
      },
    ],
    sam: {
      welcomeBubble: "Content de te revoir, on attaque par quoi ?",
      welcomeSubtitle: "Choisis un module a droite pour demarrer.",
    },
    footer: {
      legal:
        "MDL Redressement Tool · Plateforme interne · Les donnees restent confinees a votre espace.",
      helpLabel: "Aide",
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Mode routing
// ─────────────────────────────────────────────────────────────────────────────

const MODE_PATH: Record<LandingMode, string> = {
  tv: "/donnees",
  pl: "/donnees",
  carte: "/carte",
  compteurs: "/compteurs",
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
  const content = useMemo<LandingContent>(() => buildFallbackContent(), []);

  function handleModeSelect(key: LandingMode) {
    reset();
    setMode(key as Exclude<AppMode, null>);
    router.push(MODE_PATH[key]);
  }

  return (
    <>
      {/* Animated background (full-viewport, behind everything) */}
      <LandingBgStub />

      <main
        id="landing"
        className="relative z-10 mx-auto w-full max-w-[1280px] px-4 sm:px-6 lg:px-8 pb-24"
      >
        {/* Hero */}
        <HeroLanding
          eyebrow={content.eyebrow}
          title={content.title}
          subtitle={content.subtitle}
          tagline={content.tagline}
          cta={content.cta}
          onCta={() => {
            // Default CTA jumps to TV pipeline if unset by content module.
            handleModeSelect("tv");
          }}
        />

        {/* Quick stats band */}
        <QuickStats stats={content.quickStats} />

        {/* Modes grid + activity sidebar */}
        <section className="mt-8 grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
          <ModesGrid modes={content.modes} onSelect={handleModeSelect} />
          <div className="space-y-6">
            <RecentActivity items={content.recentActivity} />
          </div>
        </section>

        {/* Footer */}
        <footer className="mt-14 pt-6 border-t border-white/[0.05] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
          <p className="text-[11px] text-zinc-500">{content.footer.legal}</p>
          {content.footer.helpLabel && content.footer.helpHref && (
            <a
              href={content.footer.helpHref}
              className="text-[11px] text-zinc-400 hover:text-zinc-200 transition-colors"
            >
              {content.footer.helpLabel} →
            </a>
          )}
        </footer>
      </main>

      {/* Sam floating card (fixed bottom-right) */}
      <SamZone
        SamAvatar={SamAvatarStub}
        message={content.sam.welcomeBubble}
        subtitle={content.sam.welcomeSubtitle}
      />
    </>
  );
}
