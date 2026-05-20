"use client";

import { ModeCard } from "./ModeCard";
import type { LandingModeContent } from "./types";

interface ModesGridProps {
  modes: LandingModeContent[];
  onSelect: (key: LandingModeContent["key"]) => void;
}

export function ModesGrid({ modes, onSelect }: ModesGridProps) {
  return (
    <section aria-labelledby="modes-heading" className="relative">
      <header className="flex items-end justify-between mb-5">
        <div>
          <h2
            id="modes-heading"
            className="text-base font-semibold text-zinc-100 tracking-tight"
          >
            Modules
          </h2>
          <p className="text-xs text-zinc-500 mt-0.5">
            Selectionnez un module pour demarrer un pipeline ou ouvrir un atelier.
          </p>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">
          {modes.length} disponibles
        </span>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-stretch">
        {modes.map((mode, i) => (
          <ModeCard key={mode.key} mode={mode} onSelect={onSelect} index={i} />
        ))}
      </div>
    </section>
  );
}
