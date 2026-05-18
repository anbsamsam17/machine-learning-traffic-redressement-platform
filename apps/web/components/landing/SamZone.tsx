"use client";

import { motion, useReducedMotion } from "framer-motion";
import type { ComponentType } from "react";
import { cn } from "@/lib/utils";

/**
 * Props contract for the upstream `<SamAvatar />` shipped by the avatar agent.
 * Mirrored locally so this file remains compilable even when the real
 * component is replaced by a no-op stub during integration.
 */
export interface SamAvatarProps {
  mood: "welcome" | "based" | "analysing" | "thinking" | "goodjob" | "error";
  message?: string;
  subtitle?: string;
  placement?: "card" | "inline";
  size?: "sm" | "md" | "lg";
}

interface SamZoneProps {
  /** Real avatar component (passed from `page.tsx` to dodge import-cycle risk). */
  SamAvatar: ComponentType<SamAvatarProps>;
  message: string;
  subtitle: string;
}

/**
 * Holographic floating card that anchors Sam in the bottom-right corner of the
 * landing. On mobile it collapses to a smaller, less intrusive footprint and
 * still respects `prefers-reduced-motion`.
 */
export function SamZone({ SamAvatar, message, subtitle }: SamZoneProps) {
  const reduce = useReducedMotion();

  return (
    <motion.aside
      aria-label="Assistant Sam"
      initial={reduce ? false : { opacity: 0, y: 24, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.5, delay: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "pointer-events-auto",
        "fixed bottom-5 right-5 z-30",
        "md:bottom-6 md:right-6",
        "max-w-[min(320px,calc(100vw-2.5rem))]"
      )}
    >
      <div
        className={cn(
          "rounded-2xl border border-white/10",
          "bg-zinc-950/80 backdrop-blur-xl",
          "shadow-[0_8px_40px_-12px_rgba(99,102,241,0.4)]",
          "p-3 md:p-4"
        )}
      >
        <SamAvatar
          mood="welcome"
          message={message}
          subtitle={subtitle}
          placement="card"
          size="md"
        />
      </div>
    </motion.aside>
  );
}
