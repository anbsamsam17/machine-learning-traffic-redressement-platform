/**
 * Compatibility re-export shim.
 *
 * Pipeline pages (agent P) were briefed to import samNotify/samMood from
 * `@/lib/sam-fallback` because their worktree was created before agent N's
 * `@/lib/sam/notify` and `@/lib/sam/store` existed. Now that N has merged,
 * we keep this module as a thin re-export so the page files don't need to
 * be touched. New code should import directly from the real modules.
 */

export { samNotify } from "@/lib/sam/notify";
export { samMood, useSamStore } from "@/lib/sam/store";
export type { SamMood } from "@/lib/sam/moods";
