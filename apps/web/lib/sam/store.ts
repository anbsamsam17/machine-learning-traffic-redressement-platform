"use client";

import { create } from "zustand";
import type { SamMood } from "@/lib/sam/moods";

/**
 * SamStore — global state for the persistent <SamWidget /> mascot.
 *
 * - `mood`         current visible humeur of the widget
 * - `message`      optional bubble text shown next to the widget
 * - `visible`      master toggle (auto-hidden on /login + /register by SamWidget)
 * - `autoResetMs`  if set, after this delay the mood auto-resets to "based"
 *
 * Backwards-compat: `samMood.set(mood, message?, autoResetMs?)` keeps the
 * external API stable for callers that already invoke it.
 */

interface SamState {
  mood: SamMood;
  message: string | null;
  visible: boolean;
  /** Timestamp of the last `set` call — used to detect stale auto-reset timers. */
  _lastSetAt: number;
}

interface SamActions {
  set: (mood: SamMood, message?: string | null, autoResetMs?: number) => void;
  clearMessage: () => void;
  reset: () => void;
  show: () => void;
  hide: () => void;
}

export const useSamStore = create<SamState & SamActions>((set, get) => ({
  mood: "based",
  message: null,
  visible: true,
  _lastSetAt: 0,

  set: (mood, message = null, autoResetMs) => {
    const stamp = Date.now();
    set({ mood, message, _lastSetAt: stamp });

    if (autoResetMs && autoResetMs > 0 && typeof window !== "undefined") {
      window.setTimeout(() => {
        // Only reset if no other set() has happened since.
        if (get()._lastSetAt === stamp) {
          set({ mood: "based", message: null });
        }
      }, autoResetMs);
    }
  },

  clearMessage: () => set({ message: null }),

  reset: () => set({ mood: "based", message: null }),

  show: () => set({ visible: true }),

  hide: () => set({ visible: false }),
}));

/**
 * Imperative facade — usable outside React (event handlers, fetch callbacks).
 * Mirrors the API documented in the brief: `samMood.set(mood, message?, autoResetMs?)`.
 */
export const samMood = {
  set: (mood: SamMood, message?: string | null, autoResetMs?: number) =>
    useSamStore.getState().set(mood, message ?? null, autoResetMs),
  reset: () => useSamStore.getState().reset(),
  clearMessage: () => useSamStore.getState().clearMessage(),
  show: () => useSamStore.getState().show(),
  hide: () => useSamStore.getState().hide(),
};
