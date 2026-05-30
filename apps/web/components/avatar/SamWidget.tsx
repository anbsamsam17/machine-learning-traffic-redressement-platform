"use client";

import * as React from "react";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { cn } from "@/lib/utils";
import { useSamStore } from "@/lib/sam/store";
import { SAM_MOOD_TOKENS, samMoodImage } from "@/lib/sam/moods";
// Note: detail panel + reset button removed — Sam is a passive companion,
// users should not be able to override his contextual mood.

/**
 * SamWidget — persistent avatar in the bottom-right corner, present on every
 * page except /login and /register (where Sam is rendered larger inside the
 * page hero, so we avoid duplicating the mascot). Distinct from the
 * ephemeral `samNotify` toasts — this is the "background" mood, the one
 * the user can glance at.
 *
 * - Reads `useSamStore` for mood / message / visibility.
 * - Auto-fades the message bubble after 4s for non-persistent moods
 *   (analysing & thinking remain shown until cleared).
 * - Click on the avatar re-summons the page-level bubble (handy after the
 *   auto-dismiss timer). Acts as a toggle when the bubble is already shown.
 * - Idle float animation, skipped under prefers-reduced-motion.
 * - Uses the cutout (transparent) assets — no opaque card around the
 *   silhouette, only a soft mood-tinted glow.
 */

const PERSISTENT_MOODS = new Set(["analysing", "thinking"]);

/**
 * Mood-tinted CSS drop-shadow halo applied directly to the cutout PNG so
 * the soft glow follows Sam's silhouette instead of a square frame.
 */
const MOOD_DROP_SHADOW: Record<string, string> = {
  // Subtle mood auras: blue family for thinking/analysing, green for success, red for error.
  // Two stacked drop-shadows (close + far) for a soft halo without a hard ring.
  based:
    "drop-shadow(0 4px 14px rgba(113, 113, 122, 0.28)) drop-shadow(0 0 28px rgba(113, 113, 122, 0.18))",
  welcome:
    "drop-shadow(0 4px 14px rgba(251, 191, 36, 0.30)) drop-shadow(0 0 28px rgba(251, 191, 36, 0.18))",
  analysing:
    "drop-shadow(0 4px 14px rgba(34, 211, 238, 0.34)) drop-shadow(0 0 32px rgba(34, 211, 238, 0.22))",
  thinking:
    "drop-shadow(0 4px 14px rgba(129, 140, 248, 0.34)) drop-shadow(0 0 32px rgba(129, 140, 248, 0.22))",
  goodjob:
    "drop-shadow(0 4px 14px rgba(52, 211, 153, 0.36)) drop-shadow(0 0 32px rgba(52, 211, 153, 0.24))",
  error:
    "drop-shadow(0 4px 14px rgba(248, 113, 113, 0.36)) drop-shadow(0 0 32px rgba(248, 113, 113, 0.24))",
};

export function SamWidget() {
  const pathname = usePathname();
  const mood = useSamStore((s) => s.mood);
  const message = useSamStore((s) => s.message);
  const visible = useSamStore((s) => s.visible);
  const activeToastCount = useSamStore((s) => s.activeToastCount);

  const prefersReducedMotion = useReducedMotion();
  const [showBubble, setShowBubble] = React.useState(false);

  const bubbleId = React.useId();
  const tokens = SAM_MOOD_TOKENS[mood];

  // GSAP crossfade between mood PNGs. The <Image> `src` is swapped by React
  // on mood change; we just fade-out then fade-in the wrapper so the swap is
  // not visually brutal. Respects prefers-reduced-motion (no animation, image
  // stays fully visible).
  const imageWrapperRef = React.useRef<HTMLDivElement | null>(null);
  const prevMoodRef = React.useRef<string | null>(null);
  useGSAP(
    () => {
      const el = imageWrapperRef.current;
      if (!el) return;
      // First render: just record the mood, no animation.
      if (prevMoodRef.current === null) {
        prevMoodRef.current = mood;
        return;
      }
      if (prevMoodRef.current === mood) return;
      prevMoodRef.current = mood;
      if (prefersReducedMotion) return;

      gsap.killTweensOf(el);
      gsap.fromTo(
        el,
        { opacity: 0.2, scale: 0.95 },
        { opacity: 1, scale: 1, duration: 0.35, ease: "power2.out" },
      );
    },
    { dependencies: [mood, prefersReducedMotion] },
  );

  // Show bubble whenever a message arrives, auto-hide for non-persistent moods.
  // CRITICAL: bubble is suppressed entirely while any samNotify toast is on
  // screen (activeToastCount > 0) — guarantees no overlap between toast text
  // and widget text. Bubble re-appears once toasts have dismissed.
  React.useEffect(() => {
    if (!message || activeToastCount > 0) {
      setShowBubble(false);
      return;
    }
    setShowBubble(true);
    if (PERSISTENT_MOODS.has(mood)) return;
    const t = window.setTimeout(() => setShowBubble(false), 4000);
    return () => window.clearTimeout(t);
  }, [message, mood, activeToastCount]);

  // Click handler — re-summons the bubble after the 4s auto-dismiss, or
  // collapses it when already shown. No-op when no message is registered
  // for the current route (page-binder hasn't pushed anything yet).
  const handleAvatarClick = React.useCallback(() => {
    if (!message) return;
    setShowBubble((v) => !v);
  }, [message]);

  // Hide on auth pages.
  const onAuthPage = pathname === "/login" || pathname === "/register";
  if (!visible || onAuthPage) return null;

  const floatAnim = prefersReducedMotion
    ? undefined
    : {
        y: [0, -4, 0],
        transition: { duration: 4, repeat: Infinity, ease: "easeInOut" as const },
      };

  return (
    <div
      className="fixed bottom-6 right-6 z-50 flex flex-col items-end gap-2 pointer-events-none"
      data-sam-widget
    >
      {/* Message bubble — above the avatar */}
      <AnimatePresence>
        {showBubble && message ? (
          <motion.div
            key="sam-bubble"
            id={bubbleId}
            role="status"
            aria-live={tokens.aria}
            initial={
              prefersReducedMotion ? { opacity: 1 } : { opacity: 0, y: 8, scale: 0.95 }
            }
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.95 }}
            transition={prefersReducedMotion ? { duration: 0 } : { duration: 0.22 }}
            className={cn(
              "pointer-events-auto max-w-[280px] rounded-lg px-3 py-2",
              "bg-zinc-900/95 backdrop-blur-md border shadow-lg shadow-black/40",
              tokens.border,
            )}
          >
            <p className="text-xs leading-snug text-zinc-100">
              <span className={cn("font-semibold", tokens.title)}>Sam :</span>{" "}
              {message}
            </p>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {/* Avatar — cutout silhouette (~128px) with mood-tinted glow.
          Click toggles the bubble back on after auto-dismiss; falls back
          to a static <div> render when no message is registered for the
          route so we never expose a dead button to AT users. */}
      <motion.div
        animate={floatAnim}
        style={{ filter: MOOD_DROP_SHADOW[mood] ?? MOOD_DROP_SHADOW.based }}
        className="pointer-events-auto relative size-32"
      >
        {message ? (
          <button
            type="button"
            onClick={handleAvatarClick}
            aria-label={
              showBubble
                ? `Masquer le message de Sam (humeur: ${mood})`
                : `Afficher le message de Sam (humeur: ${mood})`
            }
            aria-expanded={showBubble}
            aria-controls={bubbleId}
            className={cn(
              "block size-full rounded-full",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950",
              "cursor-pointer"
            )}
          >
            <div ref={imageWrapperRef} className="relative size-full">
              <Image
                src={samMoodImage(mood)}
                alt=""
                fill
                sizes="128px"
                className="object-contain"
                priority={false}
              />
            </div>
          </button>
        ) : (
          <div
            role="img"
            aria-label={`Sam (humeur courante: ${mood})`}
            className="block size-full"
          >
            <div ref={imageWrapperRef} className="relative size-full">
              <Image
                src={samMoodImage(mood)}
                alt=""
                fill
                sizes="128px"
                className="object-contain"
                priority={false}
              />
            </div>
          </div>
        )}
      </motion.div>
    </div>
  );
}

export default SamWidget;
