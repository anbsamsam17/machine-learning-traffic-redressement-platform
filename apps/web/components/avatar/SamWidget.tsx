"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";
import { useSamStore } from "@/lib/sam/store";
import { SAM_MOOD_TOKENS } from "@/lib/sam/moods";
import { SamLottie } from "./SamLottie";
import { useTypewriter } from "@/lib/sam/use-typewriter";
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
 * - Lottie-like idle (breath + sway + aura) via `SamLottie`, skipped under
 *   prefers-reduced-motion.
 * - Bubble messages : typewriter effect au-dela de 30 chars.
 */

const PERSISTENT_MOODS = new Set(["analysing", "thinking"]);

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

  // Typewriter pour la bubble : message long => frappe progressive.
  const typed = useTypewriter(message ?? "", {
    enabled: showBubble && Boolean(message),
    msPerChar: 25,
    skipThreshold: 30,
  });

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
        y: [0, -3, 0],
        transition: { duration: 4.6, repeat: Infinity, ease: "easeInOut" as const },
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
              {typed}
            </p>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {/* Avatar — SamLottie gere le respirement + sway + aura color-shift.
          Le button (ou div fallback) EST l'element anime/pointer-events,
          garantit que les 4 coins de la hitbox 128x128 absorbent le click
          (correction du bug d'interception observee : sans cela, click souris
          rate le button et navigue sur la card sous-jacente). */}
      {message ? (
        <motion.button
          type="button"
          onClick={handleAvatarClick}
          animate={floatAnim}
          aria-label={
            showBubble
              ? `Masquer le message de Sam (humeur: ${mood})`
              : `Afficher le message de Sam (humeur: ${mood})`
          }
          aria-expanded={showBubble}
          aria-controls={bubbleId}
          className={cn(
            "pointer-events-auto relative size-32 rounded-full",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950",
            "cursor-pointer"
          )}
        >
          <SamLottie mood={mood} size={128} />
        </motion.button>
      ) : (
        <motion.div
          role="img"
          aria-label={`Sam (humeur courante: ${mood})`}
          animate={floatAnim}
          className="pointer-events-auto relative size-32"
        >
          <SamLottie mood={mood} size={128} />
        </motion.div>
      )}
    </div>
  );
}

export default SamWidget;
