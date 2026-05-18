"use client";

/**
 * Global Sam mood store.
 *
 * Any page / async handler can mutate Sam's mood without prop-drilling:
 *
 *     samMood.set("thinking", "On lance le training...");
 *     samMood.set("error", "Upload echoue.", 5000); // auto-reset
 *     useSamStore.getState().setMood("welcome", { message: "Salut", autoResetMs: 4000 });
 *
 * `<SamWidget />` (mounted globally in app/layout.tsx) and `<SamAvatar />`
 * (without an explicit `mood` prop) subscribe to this store.
 *
 * Two APIs are exposed:
 *  - `useSamStore` zustand hook + `setMood({...})` options-object setter.
 *  - `samMood.set(mood, message?, autoResetMs?)` positional facade for
 *    non-React callsites (sonner toasts, fetch handlers, error catchers).
 */

import { create } from "zustand";

import type { SamMood } from "./moods";

interface SamState {
  /** Currently displayed mood. */
  mood: SamMood;
  /** Optional message override (falls back to SAM_DEFAULT_MESSAGES). */
  message: string | null;
  /** Optional subtitle override (falls back to SAM_DEFAULT_SUBTITLES). */
  subtitle?: string;
  /** Visibility flag for fixed-corner widget (auto-hidden on /login + /register). */
  visible: boolean;
  /** Monotonic counter incremented on every setMood — for pulse anims. */
  version: number;
  /** Timestamp of the last `set` call — used to guard auto-reset timers. */
  _lastSetAt: number;

  /**
   * Set mood (options-object form). If `autoResetMs` is provided, the store
   * reverts to "based" after that delay (unless another set/setMood happened
   * in the meantime).
   */
  setMood: (
    mood: SamMood,
    options?: { message?: string | null; subtitle?: string; autoResetMs?: number }
  ) => void;

  /** Positional setter — kept for the `samMood.set(...)` facade. */
  set: (mood: SamMood, message?: string | null, autoResetMs?: number) => void;

  /** Clear only the bubble message — leave mood/visibility intact. */
  clearMessage: () => void;

  /** Reset to default (mood=based, message=null). */
  reset: () => void;

  /** Show/hide the corner-mounted Sam widget. */
  setVisible: (visible: boolean) => void;
  show: () => void;
  hide: () => void;
}

export const useSamStore = create<SamState>((set, get) => ({
  mood: "based",
  message: null,
  subtitle: undefined,
  visible: true,
  version: 0,
  _lastSetAt: 0,

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
}));

/**
 * Imperative facade — usable outside React.
 * API: `samMood.set(mood, message?, autoResetMs?)`.
 */
export const samMood = {
  set: (mood: SamMood, message?: string | null, autoResetMs?: number) =>
    useSamStore.getState().setMood(mood, { message: message ?? null, autoResetMs }),
  reset: () => useSamStore.getState().reset(),
  clearMessage: () => useSamStore.getState().clearMessage(),
  show: () => useSamStore.getState().show(),
  hide: () => useSamStore.getState().hide(),
};
