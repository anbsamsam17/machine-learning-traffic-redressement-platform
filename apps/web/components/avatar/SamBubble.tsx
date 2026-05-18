"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface SamBubbleProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Primary chat line. */
  message: string;
  /** Optional secondary line, smaller. */
  subtitle?: string;
  /** Layout direction — bubble sits to the right (default) or above. */
  side?: "right" | "top";
  /** Visual size — matches SamAvatar `size`. */
  size?: "sm" | "md" | "lg";
}

const SIZE_CLASSES: Record<NonNullable<SamBubbleProps["size"]>, string> = {
  sm: "max-w-[180px] px-2.5 py-1.5 text-xs",
  md: "max-w-[240px] px-3 py-2 text-sm",
  lg: "max-w-[320px] px-3.5 py-2.5 text-sm",
};

/**
 * Chat-bubble used by `SamAvatar` and reusable for ad-hoc Sam notifications
 * (e.g. inline toast). Rendered with `role="status"` + `aria-live="polite"`
 * so screen readers announce mood changes without interrupting.
 */
export const SamBubble = React.forwardRef<HTMLDivElement, SamBubbleProps>(
  function SamBubble(
    { message, subtitle, side = "right", size = "md", className, ...rest },
    ref
  ) {
    return (
      <div
        ref={ref}
        role="status"
        aria-live="polite"
        className={cn(
          "relative rounded-lg border border-zinc-800 bg-zinc-900/95 text-zinc-100 shadow-sm backdrop-blur-sm",
          SIZE_CLASSES[size],
          side === "top" ? "mb-2" : "ml-3",
          className
        )}
        {...rest}
      >
        <p className="font-medium leading-tight">{message}</p>
        {subtitle ? (
          <p className="mt-1 text-xs leading-tight text-zinc-400">{subtitle}</p>
        ) : null}
      </div>
    );
  }
);
