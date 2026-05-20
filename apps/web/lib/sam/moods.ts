/**
 * Sam mascot — single source of truth for moods, image assets, default copy,
 * and visual tokens (toast border colors, aria-live, durations).
 *
 * Sam is the data-engineer companion that follows the user through the
 * redressement pipeline. He surfaces six contextual moods. Each mood maps
 * to a PNG asset (cutout / RGBA — transparent background so Sam blends
 * directly into the surrounding UI), a sensible default message, and a set
 * of visual tokens consumed by SamToast / SamWidget / samNotify.
 *
 * `working.png` is shared between the `analysing` and `thinking` moods
 * since both share the same posture (Sam focused on screens). Visual tokens
 * (border / ring color) still differentiate them.
 */

export type SamMood =
  | "based"
  | "welcome"
  | "analysing"
  | "thinking"
  | "goodjob"
  | "error";

export const SAM_MOODS: readonly SamMood[] = [
  "welcome",
  "based",
  "analysing",
  "thinking",
  "goodjob",
  "error",
] as const;

// ---------------------------------------------------------------------------
// Image assets
// ---------------------------------------------------------------------------

/**
 * Public PNG asset paths (served from `apps/web/public/sam/cutout/`).
 *
 * All assets are detoured / transparent (RGBA) — Sam is rendered as a
 * silhouette without any baked background, so the surrounding UI shines
 * through naturally. `analysing` and `thinking` share `working.png` since
 * they depict the same posture (focused on screens).
 */
export const SAM_IMAGES: Record<SamMood, string> = {
  welcome: "/sam/cutout/welcome.png",
  based: "/sam/cutout/based.png",
  analysing: "/sam/cutout/working.png", // shared with thinking
  thinking: "/sam/cutout/working.png", // shared with analysing
  goodjob: "/sam/cutout/goodjob.png",
  error: "/sam/cutout/error.png",
};

/**
 * Legacy (pre-cutout) image paths — kept for backward compatibility in case
 * an external caller still references them. These point to the historical
 * PNGs with a baked-in background. Prefer `SAM_IMAGES` for all new code.
 */
export const SAM_IMAGES_LEGACY: Record<SamMood, string> = {
  welcome: "/sam/sam-welcome.png",
  based: "/sam/sam-based.png",
  analysing: "/sam/sam-analysing.png",
  thinking: "/sam/sam-thinking.png",
  goodjob: "/sam/sam-goodjob.png",
  error: "/sam/sam-error.png",
};

export const SAM_DEFAULT_AVATAR = SAM_IMAGES.based;

/** Resolve the image path for a mood (callers can override). */
export function samMoodImage(mood: SamMood): string {
  return SAM_IMAGES[mood] ?? SAM_DEFAULT_AVATAR;
}

// ---------------------------------------------------------------------------
// Default copy (used when no message prop / store value is set)
// ---------------------------------------------------------------------------

export const SAM_DEFAULT_MESSAGES: Record<SamMood, string> = {
  welcome: "Salut ! Content de te revoir.",
  based: "Pret quand tu l'es.",
  analysing: "Je lis tes donnees...",
  thinking: "Je reflechis a la suite...",
  goodjob: "Beau travail !",
  error: "Quelque chose a coince.",
};

export const SAM_DEFAULT_SUBTITLES: Record<SamMood, string | undefined> = {
  welcome: "Choisis un mode pour commencer.",
  based: undefined,
  analysing: "Inspection des colonnes en cours.",
  thinking: "Cela peut prendre quelques instants.",
  goodjob: "On passe a la suite quand tu veux.",
  error: "Verifie le detail puis reessaie.",
};

// ---------------------------------------------------------------------------
// Visual tokens (toast border, ring, aria-live, default duration)
// ---------------------------------------------------------------------------

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
    defaultMessage: SAM_DEFAULT_MESSAGES.based,
  },
  welcome: {
    border: "border-amber-400/60",
    title: "text-amber-200",
    accentBg: "bg-amber-500/10",
    ring: "ring-amber-400/50",
    aria: "polite",
    defaultDurationMs: 5000,
    defaultMessage: SAM_DEFAULT_MESSAGES.welcome,
  },
  analysing: {
    border: "border-cyan-400/60",
    title: "text-cyan-200",
    accentBg: "bg-cyan-500/10",
    ring: "ring-cyan-400/50",
    aria: "polite",
    defaultDurationMs: 8000,
    defaultMessage: SAM_DEFAULT_MESSAGES.analysing,
  },
  thinking: {
    border: "border-indigo-400/60",
    title: "text-indigo-200",
    accentBg: "bg-indigo-500/10",
    ring: "ring-indigo-400/50",
    aria: "polite",
    defaultDurationMs: 8000,
    defaultMessage: SAM_DEFAULT_MESSAGES.thinking,
  },
  goodjob: {
    border: "border-emerald-400/60",
    title: "text-emerald-200",
    accentBg: "bg-emerald-500/10",
    ring: "ring-emerald-400/50",
    aria: "polite",
    defaultDurationMs: 4000,
    defaultMessage: SAM_DEFAULT_MESSAGES.goodjob,
  },
  error: {
    border: "border-red-400/60",
    title: "text-red-200",
    accentBg: "bg-red-500/10",
    ring: "ring-red-400/50",
    aria: "assertive",
    defaultDurationMs: 6000,
    defaultMessage: SAM_DEFAULT_MESSAGES.error,
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

// ---------------------------------------------------------------------------
// Domain-event vocabularies (consumed by useSamMood / setters in pages)
// ---------------------------------------------------------------------------

export type SamTrigger =
  | "page-landing"
  | "page-login"
  | "page-pipeline"
  | "upload-started"
  | "upload-success"
  | "upload-error"
  | "mapping-started"
  | "mapping-success"
  | "training-started"
  | "training-success"
  | "training-error"
  | "evaluation-good"
  | "evaluation-bad"
  | "generic-error";

export const SAM_TRIGGER_TO_MOOD: Record<SamTrigger, SamMood> = {
  "page-landing": "welcome",
  "page-login": "welcome",
  "page-pipeline": "based",
  "upload-started": "analysing",
  "upload-success": "goodjob",
  "upload-error": "error",
  "mapping-started": "analysing",
  "mapping-success": "goodjob",
  "training-started": "thinking",
  "training-success": "goodjob",
  "training-error": "error",
  "evaluation-good": "goodjob",
  "evaluation-bad": "thinking",
  "generic-error": "error",
};

export function moodForPathname(pathname: string | null | undefined): SamMood {
  if (!pathname) return "based";
  const path = pathname.split("?")[0].split("#")[0].replace(/\/+$/, "") || "/";

  if (path === "/" || path === "/landing") return "welcome";
  if (path.startsWith("/login") || path.startsWith("/auth")) return "welcome";
  if (path.startsWith("/donnees") || path.startsWith("/upload")) return "analysing";
  if (path.startsWith("/mapping") || path.startsWith("/config")) return "analysing";
  if (path.startsWith("/training")) return "thinking";
  if (path.startsWith("/evaluation")) return "based";
  if (path.startsWith("/carte")) return "based";
  return "based";
}

export type SamStage =
  | "idle"
  | "uploading"
  | "mapping"
  | "training"
  | "evaluating"
  | "extrapolating"
  | "done"
  | "failed";

export const SAM_STAGE_TO_MOOD: Record<SamStage, SamMood> = {
  idle: "based",
  uploading: "analysing",
  mapping: "analysing",
  training: "thinking",
  evaluating: "thinking",
  extrapolating: "thinking",
  done: "goodjob",
  failed: "error",
};
