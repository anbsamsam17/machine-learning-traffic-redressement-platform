"use client";

/**
 * `useSamMood` — derive the current Sam mood from a variety of inputs.
 *
 * The hook supports three independent, optional inputs (any combination):
 *   - `trigger`  : a one-shot domain event (mapped via SAM_TRIGGER_TO_MOOD)
 *   - `stage`    : a long-lived UI stage     (mapped via SAM_STAGE_TO_MOOD)
 *   - `pathname` : the current Next.js route (mapped via moodForPathname)
 *
 * Precedence (highest first): explicit `mood` prop > trigger > stage > pathname > store.
 *
 * The hook also reads the global Zustand store, so any imperative
 * `useSamStore.getState().setMood(...)` call still wins when no local
 * override is provided.
 *
 * Pass `{ syncStore: true }` to push the derived mood back into the store
 * (useful for a route-level "<SamMoodSync />" component that keeps the
 * corner widget in sync with the current page).
 */

import { useEffect, useMemo } from "react";

import {
  SAM_DEFAULT_MESSAGES,
  SAM_DEFAULT_SUBTITLES,
  SAM_STAGE_TO_MOOD,
  SAM_TRIGGER_TO_MOOD,
  moodForPathname,
  type SamMood,
  type SamStage,
  type SamTrigger,
} from "./moods";
import { useSamStore } from "./store";

export interface UseSamMoodOptions {
  /** Hard override — short-circuits all other inputs. */
  mood?: SamMood;
  trigger?: SamTrigger;
  stage?: SamStage;
  pathname?: string | null;
  /** When true, the resolved mood is pushed into `useSamStore`. */
  syncStore?: boolean;
  /** Optional message override propagated when `syncStore` is true. */
  message?: string;
}

export interface UseSamMoodResult {
  mood: SamMood;
  message: string;
  subtitle: string | undefined;
}

export function useSamMood(options: UseSamMoodOptions = {}): UseSamMoodResult {
  const storeMood = useSamStore((s) => s.mood);
  const storeMessage = useSamStore((s) => s.message);
  const storeSubtitle = useSamStore((s) => s.subtitle);
  const setMood = useSamStore((s) => s.setMood);

  const resolved = useMemo<SamMood>(() => {
    if (options.mood) return options.mood;
    if (options.trigger) return SAM_TRIGGER_TO_MOOD[options.trigger];
    if (options.stage) return SAM_STAGE_TO_MOOD[options.stage];
    if (options.pathname !== undefined) return moodForPathname(options.pathname);
    return storeMood;
  }, [options.mood, options.trigger, options.stage, options.pathname, storeMood]);

  useEffect(() => {
    if (!options.syncStore) return;
    setMood(resolved, { message: options.message });
  }, [options.syncStore, options.message, resolved, setMood]);

  const message =
    options.message ??
    storeMessage ??
    SAM_DEFAULT_MESSAGES[resolved];
  const subtitle = storeSubtitle ?? SAM_DEFAULT_SUBTITLES[resolved];

  return { mood: resolved, message, subtitle };
}
