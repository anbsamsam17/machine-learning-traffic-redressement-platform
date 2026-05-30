/**
 * Sam page-messages registry.
 *
 * Central source of truth for the contextual mood + bubble copy Sam
 * surfaces on every route. Pages no longer need to call
 * `samMood.set(...)` manually for their "landing" mood — the
 * `<SamPageBinder />` component (mounted once in the root layout)
 * reads this registry on every pathname change and pushes the entry
 * into the global store.
 *
 * Pages remain free to override transiently (e.g. set "thinking"
 * while a long task runs); the registry only owns the page's *idle*
 * mood.
 *
 * Lookup rules:
 *   1. Exact pathname match (after normalising trailing slash, query
 *      and hash).
 *   2. Longest-prefix match on registered keys (so `/training/run/42`
 *      still inherits `/training`).
 *   3. `undefined` — the binder treats that as "no opinion" and
 *      resets the store to defaults.
 *
 * Style guide for new entries:
 *   - French *without* accents (project convention).
 *   - Sam tone: friendly, slightly relaxed, peer-to-peer engineer;
 *     "On itere..." not "Vous etes en train de...".
 *   - `message`  max 90 characters.
 *   - `subtitle` max 100 characters (optional).
 *   - Mention the action expected on the page when possible — avoid
 *     filler ("Bienvenue", "Cette page sert a...").
 */

import type { SamMood } from "@/lib/sam/moods";

export interface PageMessage {
  /** Mood that drives the avatar art + accent color. */
  mood: SamMood;
  /** Primary bubble line. */
  message: string;
  /** Optional secondary line for richer bubbles. */
  subtitle?: string;
}

/**
 * Pathname -> contextual message.
 * Keys are normalised (no trailing slash, no query/hash). The empty
 * trailing-slash case `/` is the only one with a leading slash by
 * itself; every other key omits the trailing slash.
 */
export const PAGE_MESSAGES: Record<string, PageMessage> = {
  "/": {
    mood: "welcome",
    message: "Choisis un outil pour demarrer ton analyse trafic.",
    subtitle: "TV, PL, Carte ou Compteurs — au choix.",
  },
  "/login": {
    mood: "welcome",
    message: "Connecte-toi pour acceder a tes outils data engineering.",
    subtitle: "Chaque session reste isolee, tes donnees ne traversent jamais.",
  },
  "/register": {
    mood: "welcome",
    message: "Premier passage ? Cree ton compte interne en deux clics.",
    subtitle: "On te bascule direct sur les outils ensuite.",
  },
  "/donnees": {
    mood: "based",
    message: "Importe tes donnees brutes, je m'occupe du mapping auto.",
    subtitle: "CSV, XLSX, GeoJSON ou shapefile zippe — tout passe.",
  },
  "/config": {
    mood: "based",
    message: "Configure le grid search. Je compte les combinaisons en live.",
    subtitle: "Activation, learning rate, dropouts, batch sizes...",
  },
  "/training": {
    mood: "thinking",
    message: "On itere sur le grid search. Je veille sur les epochs.",
    subtitle: "Patience, c'est bientot fini.",
  },
  "/evaluation": {
    mood: "based",
    message: "Verifions la qualite de ton modele sur le jeu de validation.",
    subtitle: "GEH, MAE, R² et rapport detaille a la cle.",
  },
  "/carte": {
    mood: "based",
    message: "Genere une carte de debits sur le reseau FCD.",
    subtitle: "TV + PL appliques aux segments, viewer maplibre integre.",
  },
  "/compteurs": {
    mood: "based",
    message: "Extrais le fichier compteurs au format standardise.",
    subtitle: "Schema 9 colonnes, compatible QGIS et ArcGIS.",
  },
  "/visualisation": {
    mood: "based",
    message: "Charge ton GeoJSON enrichi pour explorer la carte des debits.",
    subtitle: "JOr, DPL, PM, PS avec intervalles de confiance — popup au clic.",
  },
  "/discontinuites": {
    mood: "based",
    message: "Charge tes segments + FCD pour detecter les ruptures de flux.",
    subtitle: "8 causes typees, 3 topologies, NodePanel drill-down par segment.",
  },
};

/**
 * Normalise a Next.js pathname: drop query/hash, strip trailing
 * slash(es) except for the root.
 */
function normalisePath(pathname: string): string {
  const base = pathname.split("?")[0]!.split("#")[0]!;
  const stripped = base.replace(/\/+$/, "");
  return stripped.length === 0 ? "/" : stripped;
}

/**
 * Resolve a `PageMessage` for the given pathname.
 *
 * Order:
 *   1. exact match on the normalised path,
 *   2. longest-prefix match among the registered keys (root `/`
 *      excluded from the prefix race so it does not swallow
 *      everything),
 *   3. `undefined` when nothing matches.
 */
export function getPageMessage(
  pathname: string | null | undefined,
): PageMessage | undefined {
  if (!pathname) return undefined;
  const path = normalisePath(pathname);

  const exact = PAGE_MESSAGES[path];
  if (exact) return exact;

  let best: { key: string; entry: PageMessage } | null = null;
  for (const key of Object.keys(PAGE_MESSAGES)) {
    if (key === "/") continue;
    // Only match on path-segment boundaries so `/config` does not
    // also match `/configurations`.
    if (path === key || path.startsWith(`${key}/`)) {
      if (!best || key.length > best.key.length) {
        best = { key, entry: PAGE_MESSAGES[key]! };
      }
    }
  }
  return best?.entry;
}
