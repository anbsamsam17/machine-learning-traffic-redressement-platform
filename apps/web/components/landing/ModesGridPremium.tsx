"use client";

/**
 * ModesGridPremium — grid of ModeCardPremium with RevealOnScroll stagger.
 */

import { RevealOnScroll } from "@/components/ui";
import { ModeCardPremium } from "./ModeCardPremium";
import type { LandingModeContent } from "./types";

interface ModesGridPremiumProps {
  modes: LandingModeContent[];
  onSelect: (key: LandingModeContent["key"]) => void;
}

export function ModesGridPremium({ modes, onSelect }: ModesGridPremiumProps) {
  return (
    <section aria-labelledby="modes-heading" className="relative mt-2">
      <header className="flex items-end justify-between mb-6">
        <div>
          <h2
            id="modes-heading"
            className="text-base font-semibold text-zinc-100 tracking-tight"
          >
            Modules
          </h2>
          <p className="text-xs text-text-muted mt-1">
            Selectionnez un module pour demarrer un pipeline ou ouvrir un
            atelier.
          </p>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-widest text-text-subtle">
          {modes.length} disponibles
        </span>
      </header>

      <RevealOnScroll
        variant="slide-up"
        stagger={0.08}
        distance={24}
        className="grid grid-cols-1 md:grid-cols-2 gap-6 items-stretch"
      >
        {modes.map((mode) => (
          <div key={mode.key} data-reveal className="h-full">
            <ModeCardPremium mode={mode} onSelect={onSelect} />
          </div>
        ))}
      </RevealOnScroll>
    </section>
  );
}
