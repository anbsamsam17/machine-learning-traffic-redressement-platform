"use client";

import Image from "next/image";
import * as React from "react";

import {
  samAttentionPulse,
  samIdleFloat,
  samMoodTransition,
  samWelcomeEntrance,
} from "@/lib/animations/sam";
import {
  SAM_DEFAULT_MESSAGES,
  SAM_DEFAULT_SUBTITLES,
  SAM_IMAGES,
  type SamMood,
} from "@/lib/sam/moods";
import { useSamStore } from "@/lib/sam/store";
import { cn } from "@/lib/utils";

import { SamBubble } from "./SamBubble";

export type SamPlacement = "card" | "inline" | "fixed-corner";
export type SamSize = "sm" | "md" | "lg";

export interface SamAvatarProps {
  /** Override the store-driven mood for this instance. */
  mood?: SamMood;
  /** Override the store-driven message. */
  message?: string;
  /** Override the default subtitle. */
  subtitle?: string;
  /** Layout style — `card` is self-contained, `inline` slots into rows,
   *  `fixed-corner` mounts at `bottom-6 right-6` like an assistant widget. */
  placement?: SamPlacement;
  /** Avatar size — sm=64px, md=96px, lg=128px. */
  size?: SamSize;
  /** Render the speech bubble next to / above the avatar. */
  showBubble?: boolean;
  /** Extra classes on the outermost wrapper. */
  className?: string;
  /** Optional: when fixed-corner, hide on click (returns true to dismiss). */
  onDismiss?: () => void;
}

const SIZE_PX: Record<SamSize, number> = { sm: 64, md: 96, lg: 128 };

const FRAME_CLASSES: Record<SamSize, string> = {
  sm: "rounded-full p-[3px]",
  md: "rounded-xl p-1",
  lg: "rounded-2xl p-1",
};

/**
 * SamAvatar — the data-engineer mascot, surfaced anywhere in the product.
 *
 * - Reads `mood` from props OR from `useSamStore` when no prop is provided.
 * - Animates a soft crossfade when the mood changes (GSAP, respects
 *   prefers-reduced-motion).
 * - Plays an idle float loop while mounted.
 * - Plays a one-shot welcome entrance + ring pulse on every store version bump.
 */
export function SamAvatar({
  mood: moodProp,
  message: messageProp,
  subtitle: subtitleProp,
  placement = "card",
  size = "md",
  showBubble = false,
  className,
  onDismiss,
}: SamAvatarProps) {
  const storeMood = useSamStore((s) => s.mood);
  const storeMessage = useSamStore((s) => s.message);
  const storeSubtitle = useSamStore((s) => s.subtitle);
  const storeVisible = useSamStore((s) => s.visible);
  const storeVersion = useSamStore((s) => s.version);

  const mood: SamMood = moodProp ?? storeMood;
  const message = messageProp ?? storeMessage ?? SAM_DEFAULT_MESSAGES[mood];
  const subtitle =
    subtitleProp ?? storeSubtitle ?? SAM_DEFAULT_SUBTITLES[mood];

  // Crossfade book-keeping: keep the previous mood mounted for one frame
  // so GSAP can fade it out while the new image fades in.
  const [previousMood, setPreviousMood] = React.useState<SamMood | null>(null);
  const moodRef = React.useRef<SamMood>(mood);

  React.useEffect(() => {
    if (moodRef.current !== mood) {
      setPreviousMood(moodRef.current);
      moodRef.current = mood;
    }
  }, [mood]);

  const rootRef = React.useRef<HTMLDivElement | null>(null);
  const floatRef = React.useRef<HTMLDivElement | null>(null);
  const frameRef = React.useRef<HTMLDivElement | null>(null);
  const oldImgRef = React.useRef<HTMLDivElement | null>(null);
  const newImgRef = React.useRef<HTMLDivElement | null>(null);

  // Mount: welcome entrance + idle float.
  React.useEffect(() => {
    const cleanupEntrance = samWelcomeEntrance(rootRef.current);
    const cleanupFloat = samIdleFloat(floatRef.current);
    return () => {
      cleanupEntrance();
      cleanupFloat();
    };
  }, []);

  // Crossfade on mood change + clear the previousMood ghost when done.
  React.useEffect(() => {
    if (!previousMood) return;
    const cleanup = samMoodTransition(oldImgRef.current, newImgRef.current);
    const timer = window.setTimeout(() => setPreviousMood(null), 350);
    return () => {
      cleanup();
      window.clearTimeout(timer);
    };
  }, [previousMood, mood]);

  // Pulse the ring when the store version bumps (i.e. someone called setMood).
  React.useEffect(() => {
    if (moodProp) return; // Local-driven instance: no global pulse.
    if (storeVersion === 0) return; // Skip initial mount.
    const cleanup = samAttentionPulse(frameRef.current);
    return cleanup;
  }, [storeVersion, moodProp]);

  // fixed-corner placement respects the store's visibility flag.
  if (placement === "fixed-corner" && !storeVisible) return null;

  const px = SIZE_PX[size];
  const alt = `Sam avatar (humeur: ${mood})`;

  const avatar = (
    <div
      ref={floatRef}
      className={cn(
        "relative inline-flex shrink-0 will-change-transform",
        showBubble ? "" : ""
      )}
    >
      <div
        ref={frameRef}
        className={cn(
          "relative overflow-hidden border border-cyan-500/20 bg-zinc-950/40 ring-1 ring-cyan-500/10 shadow-[0_0_24px_-6px_rgba(6,182,212,0.35)]",
          FRAME_CLASSES[size]
        )}
        style={{ width: px + 8, height: px + 8 }}
      >
        <div
          className={cn(
            "relative overflow-hidden",
            size === "sm" ? "rounded-full" : "rounded-lg"
          )}
          style={{ width: px, height: px }}
        >
          {/* Previous mood (fading out) */}
          {previousMood ? (
            <div
              ref={oldImgRef}
              className="absolute inset-0"
              aria-hidden="true"
            >
              <Image
                src={SAM_IMAGES[previousMood]}
                alt=""
                width={px}
                height={px}
                priority={false}
                className="h-full w-full object-cover"
              />
            </div>
          ) : null}

          {/* Current mood (fading in) */}
          <div ref={newImgRef} className="absolute inset-0">
            <Image
              src={SAM_IMAGES[mood]}
              alt={alt}
              width={px}
              height={px}
              priority={placement !== "fixed-corner"}
              className="h-full w-full object-cover"
            />
          </div>
        </div>
      </div>
    </div>
  );

  const bubble =
    showBubble && message ? (
      <SamBubble
        message={message}
        subtitle={subtitle}
        size={size}
        side={placement === "fixed-corner" ? "top" : "right"}
      />
    ) : null;

  if (placement === "inline") {
    return (
      <div
        ref={rootRef}
        className={cn("inline-flex items-center gap-2", className)}
      >
        {avatar}
        {bubble}
      </div>
    );
  }

  if (placement === "fixed-corner") {
    return (
      <div
        ref={rootRef}
        className={cn(
          "pointer-events-auto fixed bottom-6 right-6 z-50 flex flex-col items-end",
          className
        )}
      >
        {bubble}
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Sam — clique pour masquer"
          className="rounded-full bg-transparent p-0 outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
        >
          {avatar}
        </button>
      </div>
    );
  }

  // card placement (default)
  return (
    <div
      ref={rootRef}
      className={cn(
        "inline-flex items-center gap-3 rounded-xl border border-zinc-800/60 bg-zinc-950/40 p-3 backdrop-blur-sm",
        className
      )}
    >
      {avatar}
      {bubble}
    </div>
  );
}

export default SamAvatar;
