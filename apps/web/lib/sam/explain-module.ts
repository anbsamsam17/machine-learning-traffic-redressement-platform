"use client";

/**
 * explain-module — compose le message que Sam doit lire dans la bulle
 * quand un utilisateur clique le bouton "Resume par Sam" d'une ModeCardPremium.
 *
 * Le rendu est anime char-par-char par `useTypewriter` cote SamWidget
 * (25 ms/char, skip si reduce-motion). On garde un texte structure et
 * lisible meme une fois entierement frappe.
 *
 * Format choisi :
 *   <tagline>
 *
 *   <description>
 *
 *   Points cles :
 *     • <metric 0>
 *     • <metric 1>
 *     • <metric 2>
 *
 * Le titre n'est pas repete dans le message : il reste visible sur la
 * card a cote de la bulle. La duree d'auto-reset (60s) est exposee pour
 * que le composant trigger reste DRY.
 */

import type { LandingModeContent } from "@/components/landing/types";

/** Duree d'affichage de la bulle apres declenchement (ms). */
export const SAM_EXPLAIN_AUTO_RESET_MS = 60000;

/**
 * Compose le message lu par Sam dans la bulle a partir d'un module
 * de la landing. Les keyMetrics sont prefixees d'une puce ASCII (le
 * typewriter rend mieux que les puces Unicode dans une bulle compacte).
 */
export function composeSamExplainMessage(mode: LandingModeContent): string {
  const lines: string[] = [];
  lines.push(mode.tagline);
  lines.push("");
  lines.push(mode.description);

  if (mode.keyMetrics.length > 0) {
    lines.push("");
    lines.push("Points cles :");
    for (const metric of mode.keyMetrics) {
      lines.push(`- ${metric}`);
    }
  }

  return lines.join("\n");
}
