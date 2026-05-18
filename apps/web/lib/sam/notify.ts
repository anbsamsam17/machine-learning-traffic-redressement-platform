"use client";

import * as React from "react";
import { toast } from "sonner";
import {
  SAM_MOOD_TOKENS,
  type SamMood,
} from "@/lib/sam/moods";
import { SamToastContent } from "@/components/avatar/SamToast";

/**
 * Public Sam notification API — thin wrapper on top of `sonner`.
 *
 * Each method builds a custom toast that renders <SamToastContent /> (Sam
 * avatar + speech bubble, mood-tinted border) and optionally syncs the global
 * <SamWidget /> mood through `samMood.set(...)`.
 *
 * Usage:
 *   import { samNotify } from "@/lib/sam/notify";
 *   samNotify.analysing("Training en cours...", { title: "Sam" });
 *   samNotify.success("Modele entraine !");
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

/**
 * Architecture decision (retour 6/7): samNotify creates ONLY the toast. It does
 * NOT mutate the SamWidget bubble. The widget bubble is reserved for the
 * ambient page mood set by `<SamPageBinder />` from PAGE_MESSAGES — that way
 * we never render the same Sam message twice on screen at once.
 *
 * If a page needs Sam's face to change in the widget for a long-running event
 * (e.g. training spinner), call `samMood.set(mood)` explicitly — but skip the
 * `message` argument so the bubble stays at the ambient text.
 */
function fireToast(
  mood: SamMood,
  message: string,
  opts: SamNotifyOptions = {},
): string | number {
  const tokens = SAM_MOOD_TOKENS[mood];
  const duration = opts.autoCloseMs ?? tokens.defaultDurationMs;

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
      // SamToastContent draws its own surface (bubble + avatar). Disable
      // sonner's default wrapper styling so it doesn't double-render.
      unstyled: true,
      classNames: {
        toast: "bg-transparent border-none shadow-none p-0",
      },
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
