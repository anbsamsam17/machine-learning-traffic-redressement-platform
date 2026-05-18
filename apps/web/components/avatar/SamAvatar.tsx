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
export type SamSize = "sm" | "md" | "lg" | "xl";

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
  /** Avatar size — sm=80px, md=128px, lg=192px, xl=256px (hero). */
  size?: SamSize;
  /** Render the speech bubble next to / above the avatar. */
  showBubble?: boolean;
  /** Extra classes on the outermost wrapper. */
  className?: string;
  /** Optional: when fixed-corner, hide on click (returns true to dismiss). */
  onDismiss?: () => void;
}

/**
 * Pixel dimensions per size. Cutout assets are detoured so Sam can now
 * render larger without competing with a baked-in background.
 */
const SIZE_PX: Record<SamSize, number> = {
  sm: 80,
  md: 128,
  lg: 192,
  xl: 256,
};

/**
 * Subtle drop-shadow color per mood — a soft halo that hints at the
 * current emotional context without enclosing Sam in a hard frame.
 * Applied via CSS `filter: drop-shadow(...)` so it follows the silhouette
 * (transparent PNG) rather than the bounding box.
 */
const MOOD_DROP_SHADOW: Record<SamMood, string> = {
  based: "drop-shadow(0 6px 18px rgba(113, 113, 122, 0.28))",
  welcome: "drop-shadow(0 6px 22px rgba(251, 191, 36, 0.32))",
  analysing: "drop-shadow(0 6px 22px rgba(34, 211, 238, 0.32))",
  thinking: "drop-shadow(0 6px 22px rgba(129, 140, 248, 0.32))",
  goodjob: "drop-shadow(0 6px 22px rgba(52, 211, 153, 0.32))",
  error: "drop-shadow(0 6px 22px rgba(248, 113, 113, 0.32))",
};

/**
 * SamAvatar — the data-engineer mascot, surfaced anywhere in the product.
 *
 * - Reads `mood` from props OR from `useSamStore` when no prop is provided.
 * - Animates a soft crossfade when the mood changes (GSAP, respects
 *   prefers-reduced-motion).
 * - Plays an idle float loop while mounted.
 * - Plays a one-shot welcome entrance + soft pulse on every store version
 *   bump.
 * - Cutout assets are transparent (RGBA): no holographic frame, ring or
 *   border — only a subtle mood-tinted drop-shadow keeps Sam grounded in
 *   the layout.
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

  // Pulse the shadow when the store version bumps (i.e. someone called
  // setMood). Visible without a hard ring thanks to the drop-shadow halo.
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
  const dropShadow = MOOD_DROP_SHADOW[mood];

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
        className="relative"
        style={{ width: px, height: px, filter: dropShadow }}
      >
        <div
          className="relative"
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
                className="h-full w-full object-contain"
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
              className="h-full w-full object-contain"
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
        size={size === "xl" ? "lg" : size}
        side={placement === "fixed-corner" ? "top" : "right"}
      />
    ) : null;

  if (placement === "inline") {
    return (
      <div
        ref={rootRef}
        className={cn("inline-flex items-center gap-3", className)}
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

  // card placement (default) — no opaque frame around Sam anymore; the
  // optional bubble keeps its own surface so the message stays legible.
  return (
    <div
      ref={rootRef}
      className={cn("inline-flex items-center gap-4", className)}
    >
      {avatar}
      {bubble}
    </div>
  );
}

export default SamAvatar;
