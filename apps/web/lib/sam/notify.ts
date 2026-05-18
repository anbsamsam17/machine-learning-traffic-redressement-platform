"use client";

import * as React from "react";
import { toast } from "sonner";
import {
  SAM_MOOD_TOKENS,
  type SamMood,
} from "@/lib/sam/moods";
import { useSamStore } from "@/lib/sam/store";
import { SamToastContent } from "@/components/avatar/SamToast";

/**
 * Public Sam notification API — thin wrapper on top of `sonner`.
 *
 * Each method:
 *   1. fires a custom sonner toast that renders <SamToastContent /> (mood-
 *      tinted bubble preceded by "Sam :"),
 *   2. swaps Sam's *face* on the floating <SamWidget /> for the duration of
 *      the toast (mood-only — the ambient bubble message from SamPageBinder
 *      is preserved),
 *   3. increments an `activeToastCount` in the store so SamWidget can
 *      suppress its bubble while a toast is on screen — guarantee: at most
 *      one Sam message visible at any time. Bubble re-appears once all
 *      toasts have dismissed or auto-closed.
 *
 * Usage:
 *   import { samNotify } from "@/lib/sam/notify";
 *   samNotify.analysing("Training en cours...");
 *   samNotify.success("Modele entraine !");
 *   samNotify.error("Echec : Not authenticated");
 */

export interface SamNotifyOptions {
  /** Optional title line above the message (xs, mood color). */
  title?: string;
  /** Override sonner duration. 0 = persistent. Defaults from mood tokens. */
  autoCloseMs?: number;
  /** Speech bubble side relative to Sam. Default "right". */
  bubbleSide?: "right" | "left";
  /** Stable id to allow updating/dismissing a specific toast. */
  id?: string | number;
}

function fireToast(
  mood: SamMood,
  message: string,
  opts: SamNotifyOptions = {},
): string | number {
  const tokens = SAM_MOOD_TOKENS[mood];
  const duration = opts.autoCloseMs ?? tokens.defaultDurationMs;
  const store = useSamStore.getState();

  // 1) Swap Sam's face for the toast's lifetime. Mood-only — bubble message
  //    is preserved (ambient from SamPageBinder). When the toast finishes,
  //    the auto-reset returns the mood to "based".
  const moodAutoReset =
    duration > 0 && mood !== "based" ? duration + 100 : undefined;
  if (mood !== "based") {
    store.setMoodOnly(mood, moodAutoReset);
  }

  // 2) Suppress widget bubble while this toast is on screen.
  store.pushToast();
  const popOnce = (() => {
    let popped = false;
    return () => {
      if (popped) return;
      popped = true;
      useSamStore.getState().popToast();
    };
  })();

  return toast.custom(
    (t) =>
      React.createElement(SamToastContent, {
        mood,
        title: opts.title,
        message,
        bubbleSide: opts.bubbleSide ?? "right",
        toastId: t,
      }),
    {
      id: opts.id,
      duration: duration === 0 ? Infinity : duration,
      // SamToastContent draws its own surface (bubble). Disable sonner's
      // default wrapper styling so it doesn't double-render a card.
      unstyled: true,
      classNames: {
        toast: "bg-transparent border-none shadow-none p-0",
      },
      onAutoClose: popOnce,
      onDismiss: popOnce,
    },
  );
}

export const samNotify = {
  success: (message: string, opts?: SamNotifyOptions) =>
    fireToast("goodjob", message, opts),

  error: (message: string, opts?: SamNotifyOptions) =>
    fireToast("error", message, opts),

  analysing: (message: string, opts?: SamNotifyOptions) =>
    fireToast("analysing", message, opts),

  thinking: (message: string, opts?: SamNotifyOptions) =>
    fireToast("thinking", message, opts),

  info: (message: string, opts?: SamNotifyOptions) =>
    fireToast("based", message, opts),

  welcome: (message: string, opts?: SamNotifyOptions) =>
    fireToast("welcome", message, opts),

  /** Dismiss a specific toast (by id) or all toasts. */
  dismiss: (id?: string | number) => {
    if (id === undefined) {
      toast.dismiss();
    } else {
      toast.dismiss(id);
    }
  },

  /**
   * Sonner-style promise wrapper. Renders an `analysing` toast while loading,
   * then swaps to `goodjob` / `error` based on resolution.
   *
   * Returns the original promise so callers can `await` it transparently.
   */
  promise<T>(
    promise: Promise<T>,
    msgs: {
      loading: string;
      success: string | ((value: T) => string);
      error: string | ((err: unknown) => string);
    },
    opts?: Pick<SamNotifyOptions, "title" | "bubbleSide">,
  ): Promise<T> {
    const id = fireToast("analysing", msgs.loading, {
      ...opts,
      autoCloseMs: 0, // persistent until settled
    });

    promise
      .then((value) => {
        const msg =
          typeof msgs.success === "function" ? msgs.success(value) : msgs.success;
        fireToast("goodjob", msg, { ...opts, id });
      })
      .catch((err: unknown) => {
        const msg =
          typeof msgs.error === "function" ? msgs.error(err) : msgs.error;
        fireToast("error", msg, { ...opts, id });
      });

    return promise;
  },
};

export type SamNotifyApi = typeof samNotify;
