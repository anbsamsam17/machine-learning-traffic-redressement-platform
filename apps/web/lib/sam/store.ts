"use client";

/**
 * Global Sam mood store.
 *
 * Three concerns are separated:
 *
 *   1. `mood` + `message`: persistent ambient state for `<SamWidget />`
 *      (driven by `<SamPageBinder />` from PAGE_MESSAGES).
 *
 *   2. `setMoodOnly(mood, autoResetMs?)`: a transient face change without
 *      touching the bubble message. Used by `samNotify` so Sam's face
 *      reflects the event (analysing / thinking / goodjob / error) while
 *      the bubble message is owned by the page-binder.
 *
 *   3. `activeToastCount`: incremented by `samNotify` while a toast is on
 *      screen; the widget bubble suppresses itself when the count > 0 so
 *      we never render two Sam messages simultaneously.
 *
 *      ┌── ambient bubble (page context) ──┐
 *      ╳ toast appears ─→ count++ ─→ bubble hidden
 *      ╳ toast dismissed ─→ count-- ─→ bubble re-appears
 */

import { create } from "zustand";

import type { SamMood } from "./moods";

interface SamState {
  mood: SamMood;
  message: string | null;
  subtitle?: string;
  visible: boolean;
  version: number;
  _lastSetAt: number;
  /** Counter of active toasts on screen. Widget bubble is suppressed when > 0. */
  activeToastCount: number;

  setMood: (
    mood: SamMood,
    options?: { message?: string | null; subtitle?: string; autoResetMs?: number }
  ) => void;

  /** Positional setter — kept for the `samMood.set(...)` facade. */
  set: (mood: SamMood, message?: string | null, autoResetMs?: number) => void;

  /**
   * Mood-only update: change Sam's face without touching the bubble message.
   * Used by samNotify to swap the avatar to the event mood (error / goodjob /
   * thinking / analysing) while the ambient bubble keeps its page-binder text.
   */
  setMoodOnly: (mood: SamMood, autoResetMs?: number) => void;

  clearMessage: () => void;
  reset: () => void;
  setVisible: (visible: boolean) => void;
  show: () => void;
  hide: () => void;

  pushToast: () => void;
  popToast: () => void;
}

export const useSamStore = create<SamState>((set, get) => ({
  mood: "based",
  message: null,
  subtitle: undefined,
  visible: true,
  version: 0,
  _lastSetAt: 0,
  activeToastCount: 0,

  setMood: (mood, options) => {
    const stamp = Date.now();
    set((s) => ({
      mood,
      message: options?.message ?? null,
      subtitle: options?.subtitle,
      version: s.version + 1,
      _lastSetAt: stamp,
    }));

    if (options?.autoResetMs && options.autoResetMs > 0 && typeof window !== "undefined") {
      window.setTimeout(() => {
        if (get()._lastSetAt === stamp) {
          set((s) => ({
            mood: "based",
            message: null,
            subtitle: undefined,
            version: s.version + 1,
          }));
        }
      }, options.autoResetMs);
    }
  },

  set: (mood, message, autoResetMs) =>
    get().setMood(mood, { message: message ?? null, autoResetMs }),

  setMoodOnly: (mood, autoResetMs) => {
    const stamp = Date.now();
    set((s) => ({
      mood,
      version: s.version + 1,
      _lastSetAt: stamp,
    }));

    if (autoResetMs && autoResetMs > 0 && typeof window !== "undefined") {
      window.setTimeout(() => {
        if (get()._lastSetAt === stamp) {
          set((s) => ({
            mood: "based",
            version: s.version + 1,
          }));
        }
      }, autoResetMs);
    }
  },

  clearMessage: () => set({ message: null }),

  reset: () => {
    set((s) => ({
      mood: "based",
      message: null,
      subtitle: undefined,
      version: s.version + 1,
    }));
  },

  setVisible: (visible) => set({ visible }),
  show: () => set({ visible: true }),
  hide: () => set({ visible: false }),

  pushToast: () => set((s) => ({ activeToastCount: s.activeToastCount + 1 })),
  popToast: () =>
    set((s) => ({ activeToastCount: Math.max(0, s.activeToastCount - 1) })),
}));

/**
 * Imperative facade — usable outside React.
 * API: `samMood.set(mood, message?, autoResetMs?)`.
 */
export const samMood = {
  set: (mood: SamMood, message?: string | null, autoResetMs?: number) =>
    useSamStore.getState().setMood(mood, { message: message ?? null, autoResetMs }),
  setMoodOnly: (mood: SamMood, autoResetMs?: number) =>
    useSamStore.getState().setMoodOnly(mood, autoResetMs),
  reset: () => useSamStore.getState().reset(),
  clearMessage: () => useSamStore.getState().clearMessage(),
  show: () => useSamStore.getState().show(),
  hide: () => useSamStore.getState().hide(),
};
