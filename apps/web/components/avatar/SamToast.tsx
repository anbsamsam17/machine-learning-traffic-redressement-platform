"use client";

import * as React from "react";
import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";
import {
  SAM_MOOD_TOKENS,
  type SamMood,
} from "@/lib/sam/moods";

export interface SamToastContentProps {
  mood: SamMood;
  title?: string;
  message: string;
  bubbleSide?: "right" | "left";
  /** Forwarded by sonner — id of the toast (currently unused, kept for future close button). */
  toastId?: string | number;
}

/**
 * Custom layout used inside `sonner.toast.custom(...)`.
 *
 * Sam's persistent avatar lives in the bottom-right `<SamWidget />`. Toasts
 * are intentionally avatar-less to avoid the "two Sams on screen" effect —
 * they read as text messages from Sam, prefixed with "Sam : " so the speaker
 * is unambiguous.
 *
 * a11y:
 *  - `role="alert"` for `error`, `role="status"` for everything else.
 *  - `aria-live` driven by mood tokens.
 *
 * Motion:
 *  - slide-in / scale-up via framer-motion.
 *  - `useReducedMotion()` short-circuits to instant render.
 */
export function SamToastContent({
  mood,
  title,
  message,
  bubbleSide = "right",
  toastId,
}: SamToastContentProps) {
  const tokens = SAM_MOOD_TOKENS[mood];
  const prefersReducedMotion = useReducedMotion();
  const bubbleId = React.useId();
  const isError = mood === "error";

  // Slide direction is opposite of the bubble side (bubble on right → toast slides in from right).
  const slideFrom = bubbleSide === "right" ? 24 : -24;

  return (
    <motion.div
      role={isError ? "alert" : "status"}
      aria-live={tokens.aria}
      aria-atomic="true"
      data-mood={mood}
      data-toast-id={toastId}
      initial={
        prefersReducedMotion
          ? { opacity: 1, x: 0, scale: 1 }
          : { opacity: 0, x: slideFrom, scale: 0.95 }
      }
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={
        prefersReducedMotion
          ? { opacity: 0 }
          : { opacity: 0, x: slideFrom, scale: 0.95 }
      }
      transition={
        prefersReducedMotion
          ? { duration: 0 }
          : { duration: 0.25, ease: [0.34, 1.56, 0.64, 1] /* back.out(1.2) approx */ }
      }
      className="pointer-events-auto"
    >
      {/* Bubble — Sam speaks via text, no avatar (the floating SamWidget shows Sam) */}
      <div
        id={bubbleId}
        className={cn(
          "relative max-w-[360px] rounded-lg px-3.5 py-3",
          "bg-zinc-900/95 backdrop-blur-md",
          "border",
          tokens.border,
          "shadow-lg shadow-black/40",
        )}
      >
        {title ? (
          <div
            className={cn(
              "text-xs font-semibold uppercase tracking-wide mb-1",
              tokens.title,
            )}
          >
            {title}
          </div>
        ) : null}
        <div className="text-sm leading-snug text-zinc-100">
          <span className={cn("font-semibold", tokens.title)}>Sam :</span>{" "}
          {message}
        </div>

        {/* Subtle accent tint stripe */}
        <span
          aria-hidden="true"
          className={cn(
            "pointer-events-none absolute inset-0 rounded-lg",
            tokens.accentBg,
            "opacity-60",
          )}
          style={{ mixBlendMode: "overlay" }}
        />
      </div>
    </motion.div>
  );
}

export default SamToastContent;
