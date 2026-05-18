"use client";

/**
 * Global Sam mood store.
 *
 * Any page / async handler can mutate Sam's mood without prop-drilling:
 *
 *     useSamStore.getState().setMood("thinking", "On lance le training...");
 *     useSamStore.getState().setMood("error", "Upload echoue.", 5_000); // auto-reset
 *
 * `<SamAvatar />` (without a `mood` prop) subscribes to this store and
 * re-renders when it changes. A single `<SamAvatar placement="fixed-corner" />`
 * mounted in the root layout is enough to surface mood changes app-wide.
 */

import { create } from "zustand";

import type { SamMood } from "./moods";

interface SamState {
  /** Currently displayed mood. */
  mood: SamMood;
  /** Optional message override (falls back to SAM_DEFAULT_MESSAGES). */
  message?: string;
  /** Optional subtitle override (falls back to SAM_DEFAULT_SUBTITLES). */
  subtitle?: string;
  /** Visibility flag for fixed-corner placement. */
  visible: boolean;
  /** Monotonic counter incremented on every setMood — useful to trigger pulse animations. */
  version: number;

  /**
   * Set mood and optional message. If `autoResetMs` is provided, the store
   * reverts to the previous mood (or "based") after that delay.
   */
  setMood: (
    mood: SamMood,
    options?: { message?: string; subtitle?: string; autoResetMs?: number }
  ) => void;

  /** Reset to defaults. */
  reset: () => void;

  /** Show/hide the corner-mounted Sam widget. */
  setVisible: (visible: boolean) => void;
}

let resetTimer: ReturnType<typeof setTimeout> | null = null;

const clearTimer = () => {
  if (resetTimer) {
    clearTimeout(resetTimer);
    resetTimer = null;
  }
};

export const useSamStore = create<SamState>((set, get) => ({
  mood: "based",
  message: undefined,
  subtitle: undefined,
  visible: true,
  version: 0,

  setMood: (mood, options) => {
    clearTimer();
    const previous = get().mood;
    set((s) => ({
      mood,
      message: options?.message,
      subtitle: options?.subtitle,
      version: s.version + 1,
    }));

    if (options?.autoResetMs && options.autoResetMs > 0) {
      resetTimer = setTimeout(() => {
        // Only revert if no later setMood overrode us in the meantime.
        if (get().mood === mood) {
          set((s) => ({
            mood: previous === mood ? "based" : previous,
            message: undefined,
            subtitle: undefined,
            version: s.version + 1,
          }));
        }
        resetTimer = null;
      }, options.autoResetMs);
    }
  },

  reset: () => {
    clearTimer();
    set((s) => ({
      mood: "based",
      message: undefined,
      subtitle: undefined,
      version: s.version + 1,
    }));
  },

  setVisible: (visible) => set({ visible }),
}));

/** Tiny imperative helper for non-React callsites (e.g. error handlers). */
export const samMood = {
  set: (mood: SamMood, message?: string, autoResetMs?: number) =>
    useSamStore.getState().setMood(mood, { message, autoResetMs }),
  reset: () => useSamStore.getState().reset(),
  hide: () => useSamStore.getState().setVisible(false),
  show: () => useSamStore.getState().setVisible(true),
};
