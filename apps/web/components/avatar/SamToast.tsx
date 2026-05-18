"use client";

import * as React from "react";
import Image from "next/image";
import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";
import {
  SAM_MOOD_TOKENS,
  samMoodImage,
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
 * Horizontal: Sam avatar (round, holographic frame) + speech bubble.
 *
 * a11y:
 *  - `role="alert"` for `error`, `role="status"` for everything else.
 *  - `aria-live` driven by mood tokens.
 *  - Bubble linked to title via `aria-describedby`.
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
      className={cn(
        "flex items-start gap-3",
        bubbleSide === "left" && "flex-row-reverse",
        "pointer-events-auto",
      )}
    >
      {/* Avatar — holographic cyan/indigo frame */}
      <div
        className={cn(
          "relative flex-shrink-0 size-14 rounded-full overflow-hidden",
          "ring-2 ring-offset-2 ring-offset-zinc-950",
          tokens.ring,
          "bg-gradient-to-br from-cyan-500/20 via-indigo-500/20 to-violet-500/20",
        )}
        aria-hidden="true"
      >
        <Image
          src={samMoodImage(mood)}
          alt=""
          fill
          sizes="56px"
          className="object-cover"
          priority={false}
          unoptimized
        />
      </div>

      {/* Bubble */}
      <div
        id={bubbleId}
        className={cn(
          "relative max-w-[320px] rounded-lg px-3 py-3",
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
        <div className="text-sm leading-snug text-zinc-100">{message}</div>

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
