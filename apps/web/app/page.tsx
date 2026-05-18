"use client";

import { useRouter } from "next/navigation";
import { Brain, Truck, Map, Activity } from "lucide-react";
import { ModeCard } from "@/components/pipeline/mode-card";
import { useAppStore } from "@/lib/store";
import { fr } from "@/lib/i18n/fr";

export default function HomePage() {
  const router = useRouter();
  const setMode = useAppStore((s) => s.setMode);

  function handleMode(mode: "tv" | "pl" | "carte" | "compteurs") {
    setMode(mode);
    if (mode === "carte") router.push("/carte");
    else if (mode === "compteurs") router.push("/compteurs");
    else router.push("/donnees");
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] px-4 py-12">
      <div className="max-w-3xl mx-auto space-y-8">
        <header className="space-y-2">
          <p className="text-xs font-medium text-accent uppercase tracking-wider">
            {fr.common.appName}
          </p>
          <h1 className="text-2xl sm:text-3xl font-semibold text-text">
            {fr.landing.title}
          </h1>
          <p className="text-sm text-text-muted max-w-xl">{fr.landing.subtitle}</p>
        </header>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <ModeCard
            title={fr.landing.cards.tv.title}
            description={fr.landing.cards.tv.desc}
            icon={<Brain aria-hidden="true" />}
            onClick={() => handleMode("tv")}
          />
          <ModeCard
            title={fr.landing.cards.pl.title}
            description={fr.landing.cards.pl.desc}
            icon={<Truck aria-hidden="true" />}
            onClick={() => handleMode("pl")}
          />
          <ModeCard
            title={fr.landing.cards.carte.title}
            description={fr.landing.cards.carte.desc}
            icon={<Map aria-hidden="true" />}
            onClick={() => handleMode("carte")}
          />
          <ModeCard
            title={fr.landing.cards.compteurs.title}
            description={fr.landing.cards.compteurs.desc}
            icon={<Activity aria-hidden="true" />}
            onClick={() => handleMode("compteurs")}
          />
        </div>

        <p className="text-xs text-text-subtle">
          Vos donnees sont traitees sur le serveur MDL Redressement. Aucun stockage tiers.
        </p>
      </div>
    </div>
  );
}
