/**
 * Sam mascot — mood definitions, image assets, and default messages.
 *
 * Sam is the data-engineer companion that follows the user through the
 * redressement pipeline. He surfaces six contextual moods. Each mood maps
 * to a 256x256 PNG (background baked into the image — no transparency on
 * the subject) and a sensible default message that any component can use
 * when no custom copy is provided.
 */

export type SamMood =
  | "welcome"
  | "based"
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

/** Public PNG asset paths (served from `apps/web/public/sam/`). */
export const SAM_IMAGES: Record<SamMood, string> = {
  welcome: "/sam/sam-welcome.png",
  based: "/sam/sam-based.png",
  analysing: "/sam/sam-analysing.png",
  thinking: "/sam/sam-thinking.png",
  goodjob: "/sam/sam-goodjob.png",
  error: "/sam/sam-error.png",
};

/** Sober French copy used when no `message` prop / store value is set. */
export const SAM_DEFAULT_MESSAGES: Record<SamMood, string> = {
  welcome: "Salut ! Content de te revoir.",
  based: "Pret quand tu l'es.",
  analysing: "Je lis tes donnees...",
  thinking: "Je reflechis a la suite...",
  goodjob: "Beau travail !",
  error: "Quelque chose a coince.",
};

/** Optional secondary line, used when the caller wants a slightly richer bubble. */
export const SAM_DEFAULT_SUBTITLES: Record<SamMood, string | undefined> = {
  welcome: "Choisis un mode pour commencer.",
  based: undefined,
  analysing: "Inspection des colonnes en cours.",
  thinking: "Cela peut prendre quelques instants.",
  goodjob: "On passe a la suite quand tu veux.",
  error: "Verifie le detail puis reessaie.",
};

/**
 * Trigger event vocabulary used by `useSamMood({ trigger })` and downstream
 * code that wants to map a domain event to a mood without hard-coding the
 * `SamMood` strings everywhere.
 */
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
  | "extrapolation-started"
  | "extrapolation-success"
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
  "extrapolation-started": "thinking",
  "extrapolation-success": "goodjob",
  "generic-error": "error",
};

/** Pathname -> mood mapping used by `useSamMood({ pathname })`. */
export function moodForPathname(pathname: string | null | undefined): SamMood {
  if (!pathname) return "based";
  // Strip query/hash, normalise trailing slash.
  const path = pathname.split("?")[0].split("#")[0].replace(/\/+$/, "") || "/";

  if (path === "/" || path === "/landing") return "welcome";
  if (path.startsWith("/login") || path.startsWith("/auth")) return "welcome";
  if (path.startsWith("/donnees") || path.startsWith("/upload")) return "analysing";
  if (path.startsWith("/mapping") || path.startsWith("/config")) return "analysing";
  if (path.startsWith("/training")) return "thinking";
  if (path.startsWith("/evaluation")) return "based";
  if (path.startsWith("/extrapolation")) return "thinking";
  if (path.startsWith("/carte")) return "based";
  return "based";
}

/**
 * Stage vocabulary — convenient shortcuts used by `useSamMood({ stage })`.
 * Less specific than triggers; intended for long-lived UI sections.
 */
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
