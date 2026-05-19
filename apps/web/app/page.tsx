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
  Brain,
  Truck,
  Map as MapIcon,
  Activity,
  type LucideIcon,
} from "lucide-react";
import { useAppStore, type AppMode } from "@/lib/store";
import { samMood } from "@/lib/sam/store";
import { getPageMessage } from "@/lib/sam/page-messages";
import { HeroLanding } from "@/components/landing/HeroLanding";
import { ModesGrid } from "@/components/landing/ModesGrid";
import { QuickStats } from "@/components/landing/QuickStats";
import { RecentActivity } from "@/components/landing/RecentActivity";
import { SamZone } from "@/components/landing/SamZone";
import type {
  LandingContent,
  LandingMode,
  LandingModeContent,
} from "@/components/landing/types";
import { SamAvatar } from "@/components/avatar/SamAvatar";
import { LandingBg } from "@/components/landing/animations/LandingBg";
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
  tv: { accent: "indigo", icon: Brain as LucideIcon },
  pl: { accent: "amber", icon: Truck as LucideIcon },
  carte: { accent: "cyan", icon: MapIcon as LucideIcon },
  compteurs: { accent: "emerald", icon: Activity as LucideIcon },
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
      {/* Animated background (full-viewport, behind everything) */}
      <LandingBg />

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

      {/* SamWidget is mounted globally in app/layout.tsx, no per-page SamZone. */}
    </>
  );
}
