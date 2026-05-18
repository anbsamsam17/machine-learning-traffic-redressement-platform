"use client";

import * as React from "react";
import { toast } from "sonner";
import {
  SAM_MOOD_TOKENS,
  SYNC_WIDGET_BY_DEFAULT,
  type SamMood,
} from "@/lib/sam/moods";
import { samMood } from "@/lib/sam/store";
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
  /**
   * Whether to also push the mood to the global SamWidget.
   * Defaults to true for analysing/thinking/goodjob/error/welcome, false for info.
   */
  syncWidget?: boolean;
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

  const shouldSyncWidget =
    opts.syncWidget !== undefined
      ? opts.syncWidget
      : SYNC_WIDGET_BY_DEFAULT.has(mood);

  if (shouldSyncWidget) {
    // Non-persistent moods auto-reset the widget after the toast duration.
    const widgetAutoReset =
      duration > 0 && mood !== "analysing" && mood !== "thinking"
        ? duration + 500
        : undefined;
    samMood.set(mood, message, widgetAutoReset);
  }

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
