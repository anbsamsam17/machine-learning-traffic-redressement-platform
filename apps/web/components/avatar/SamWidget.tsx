"use client";

import * as React from "react";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";
import { useSamStore } from "@/lib/sam/store";
import { SAM_MOOD_TOKENS, samMoodImage } from "@/lib/sam/moods";

/**
 * SamWidget — persistent avatar in the bottom-right corner, present on every
 * page except /login and /register. Distinct from the ephemeral `samNotify`
 * toasts — this is the "background" mood, the one the user can glance at.
 *
 * - Reads `useSamStore` for mood / message / visibility.
 * - Auto-fades the message bubble after 4s for non-persistent moods
 *   (analysing & thinking remain shown until cleared).
 * - Click opens a small detail panel (mood label + Reset button).
 * - Idle float animation, skipped under prefers-reduced-motion.
 */

const PERSISTENT_MOODS = new Set(["analysing", "thinking"]);

export function SamWidget() {
  const pathname = usePathname();
  const mood = useSamStore((s) => s.mood);
  const message = useSamStore((s) => s.message);
  const visible = useSamStore((s) => s.visible);
  const clearMessage = useSamStore((s) => s.clearMessage);
  const reset = useSamStore((s) => s.reset);

  const prefersReducedMotion = useReducedMotion();
  const [open, setOpen] = React.useState(false);
  const [showBubble, setShowBubble] = React.useState(false);

  const bubbleId = React.useId();
  const tokens = SAM_MOOD_TOKENS[mood];

  // Show bubble whenever a message arrives, auto-hide for non-persistent moods.
  React.useEffect(() => {
    if (!message) {
      setShowBubble(false);
      return;
    }
    setShowBubble(true);
    if (PERSISTENT_MOODS.has(mood)) return;
    const t = window.setTimeout(() => setShowBubble(false), 4000);
    return () => window.clearTimeout(t);
  }, [message, mood]);

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
            <p className={cn("text-[10px] font-semibold uppercase tracking-wide", tokens.title)}>
              Sam
            </p>
            <p className="text-xs leading-snug text-zinc-100">{message}</p>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {/* Detail panel — toggled by click */}
      <AnimatePresence>
        {open ? (
          <motion.div
            key="sam-detail"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 6 }}
            transition={{ duration: 0.18 }}
            className={cn(
              "pointer-events-auto rounded-lg p-3 min-w-[180px]",
              "bg-zinc-900/95 backdrop-blur-md border shadow-lg shadow-black/40",
              tokens.border,
            )}
          >
            <div className="flex items-center justify-between gap-3 mb-2">
              <span className={cn("text-[10px] font-semibold uppercase tracking-wide", tokens.title)}>
                Humeur
              </span>
              <span className="text-xs text-zinc-300">{mood}</span>
            </div>
            <button
              type="button"
              onClick={() => {
                reset();
                clearMessage();
                setOpen(false);
              }}
              className={cn(
                "w-full text-xs px-2 py-1.5 rounded-md",
                "bg-zinc-800 hover:bg-zinc-700 text-zinc-100 transition-colors",
                "focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-zinc-950",
                "focus:ring-indigo-400/50",
              )}
            >
              Reset Sam
            </button>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {/* Avatar — holographic 96x96 card */}
      <motion.button
        type="button"
        aria-label={`Sam avatar (humeur courante: ${mood})`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-describedby={message ? bubbleId : undefined}
        onClick={() => setOpen((o) => !o)}
        animate={floatAnim}
        className={cn(
          "pointer-events-auto relative size-24 rounded-2xl overflow-hidden",
          "ring-2 ring-offset-2 ring-offset-zinc-950",
          tokens.ring,
          "bg-gradient-to-br from-cyan-500/20 via-indigo-500/20 to-violet-500/20",
          "shadow-xl shadow-black/50",
          "focus:outline-none focus:ring-indigo-400/70",
          "transition-transform hover:scale-105",
        )}
      >
        <Image
          src={samMoodImage(mood)}
          alt=""
          fill
          sizes="96px"
          className="object-cover"
          priority={false}
          unoptimized
        />
        {/* Subtle accent overlay */}
        <span
          aria-hidden="true"
          className={cn(
            "pointer-events-none absolute inset-0",
            tokens.accentBg,
            "opacity-30",
          )}
        />
      </motion.button>
    </div>
  );
}

export default SamWidget;
