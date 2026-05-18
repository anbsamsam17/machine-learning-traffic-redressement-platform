/**
 * Sam mood system — single source of truth for moods + their visual tokens.
 *
 * A mood drives:
 *  - The avatar artwork (or facial expression layer) used by SamWidget / SamToast.
 *  - The accent color (border / text) on toasts and the widget halo.
 *  - The aria-live politeness level of the toast.
 *
 * Moods are intentionally compact — extend here when you add a new emotion
 * (and add the corresponding image under /public/sam/<mood>.png if you want
 * artwork variation; otherwise the default avatar is used as a fallback).
 */

export type SamMood =
  | "based" // neutral / default
  | "welcome" // greeting, soft amber-pink
  | "analysing" // working, cyan, persistent
  | "thinking" // pondering, indigo, persistent
  | "goodjob" // success, emerald
  | "error"; // alert, red

export interface SamMoodTokens {
  /** Tailwind border color class for the toast bubble + widget halo. */
  border: string;
  /** Tailwind text color class for the title line. */
  title: string;
  /** Tailwind background tint (very subtle, used on the bubble accent). */
  accentBg: string;
  /** Tailwind glow/ring color for the avatar frame. */
  ring: string;
  /** aria-live level for assistive tech. */
  aria: "polite" | "assertive";
  /** Default duration in ms for sonner. 0 = persistent. */
  defaultDurationMs: number;
  /** Fallback prose tone — used when no message is provided. */
  defaultMessage: string;
}

export const SAM_MOOD_TOKENS: Record<SamMood, SamMoodTokens> = {
  based: {
    border: "border-zinc-700",
    title: "text-zinc-200",
    accentBg: "bg-zinc-500/10",
    ring: "ring-zinc-500/40",
    aria: "polite",
    defaultDurationMs: 4000,
    defaultMessage: "Tout va bien.",
  },
  welcome: {
    border: "border-amber-400/60",
    title: "text-amber-200",
    accentBg: "bg-amber-500/10",
    ring: "ring-amber-400/50",
    aria: "polite",
    defaultDurationMs: 5000,
    defaultMessage: "Bienvenue !",
  },
  analysing: {
    border: "border-cyan-400/60",
    title: "text-cyan-200",
    accentBg: "bg-cyan-500/10",
    ring: "ring-cyan-400/50",
    aria: "polite",
    defaultDurationMs: 8000,
    defaultMessage: "Analyse en cours...",
  },
  thinking: {
    border: "border-indigo-400/60",
    title: "text-indigo-200",
    accentBg: "bg-indigo-500/10",
    ring: "ring-indigo-400/50",
    aria: "polite",
    defaultDurationMs: 8000,
    defaultMessage: "Reflexion...",
  },
  goodjob: {
    border: "border-emerald-400/60",
    title: "text-emerald-200",
    accentBg: "bg-emerald-500/10",
    ring: "ring-emerald-400/50",
    aria: "polite",
    defaultDurationMs: 4000,
    defaultMessage: "Bien joue !",
  },
  error: {
    border: "border-red-400/60",
    title: "text-red-200",
    accentBg: "bg-red-500/10",
    ring: "ring-red-400/50",
    aria: "assertive",
    defaultDurationMs: 6000,
    defaultMessage: "Une erreur est survenue.",
  },
};

/** Moods that should auto-sync to the global SamWidget by default. */
export const SYNC_WIDGET_BY_DEFAULT: ReadonlySet<SamMood> = new Set<SamMood>([
  "analysing",
  "thinking",
  "goodjob",
  "error",
  "welcome",
]);

/** Default fallback artwork — every mood resolves to /public/sam/<mood>.png if present, else this. */
export const SAM_DEFAULT_AVATAR = "/sam/based.png";

/** Resolve the image path for a mood (callers can override). */
export function samMoodImage(mood: SamMood): string {
  return `/sam/${mood}.png`;
}
