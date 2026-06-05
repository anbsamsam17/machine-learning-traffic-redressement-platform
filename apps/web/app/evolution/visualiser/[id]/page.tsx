"use client";

/**
 * Route historique du visualiseur d'evolution.
 *
 * Depuis la refonte UX 2026-06, la carte d'evolution est affichee INLINE dans
 * la page principale `/evolution` (carte MapLibre unique + crossfade preview ->
 * reel, calque sur /discontinuites). Cette route est conservee pour ne pas
 * casser d'anciens liens : elle redirige vers `/evolution`.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

export default function EvolutionVisualiserRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/evolution");
  }, [router]);

  return (
    <div className="flex items-center justify-center min-h-[calc(100vh-3rem)]">
      <div className="flex flex-col items-center gap-3 text-text-muted">
        <Loader2 className="animate-spin text-accent" size={24} />
        <p className="text-xs">Redirection vers la carte d&apos;evolution...</p>
      </div>
    </div>
  );
}
