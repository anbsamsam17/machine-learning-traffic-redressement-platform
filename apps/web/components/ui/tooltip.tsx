"use client";

/**
 * Lightweight, dependency-free Tooltip primitive.
 *
 * Why custom? `@radix-ui/react-tooltip` is not in the dependency tree of
 * apps/web and we want to avoid pulling in a new package just for the
 * config-form coaching tooltips. This component covers our needs:
 *
 *   - Hover + focus trigger (keyboard accessible)
 *   - aria-describedby / aria-label wiring
 *   - Configurable side (top | right | bottom | left)
 *   - Auto-dismiss on Escape
 *   - Reduced-motion friendly (CSS transition, no JS animation)
 *
 * Usage:
 *   <FieldTooltip purpose="..." recommendation="...">
 *     {(triggerProps) => <button {...triggerProps}><Info /></button>}
 *   </FieldTooltip>
 *
 * For the typical case (an Info icon next to a label) use `<FieldInfo />`.
 */

import {
  useState,
  useRef,
  useEffect,
  useId,
  type ReactNode,
  type CSSProperties,
} from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

type TooltipSide = "top" | "right" | "bottom" | "left";

interface TooltipProps {
  /** Trigger element — receives ref + handlers via render prop. */
  children: (triggerProps: {
    ref: React.Ref<HTMLButtonElement>;
    onMouseEnter: () => void;
    onMouseLeave: () => void;
    onFocus: () => void;
    onBlur: () => void;
    "aria-describedby": string;
  }) => ReactNode;
  /** Tooltip body — string or rich React node. */
  content: ReactNode;
  /** Preferred side. Defaults to "top". */
  side?: TooltipSide;
  /** Wrapper class for the trigger span. */
  className?: string;
}

export function Tooltip({
  children,
  content,
  side = "top",
  className,
}: TooltipProps) {
  const [open, setOpen] = useState(false);
  const tooltipId = useId();
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  // Dismiss on Escape (only when open).
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // Position offsets for each side — applied to the popover wrapper.
  const positionClass: Record<TooltipSide, string> = {
    top: "bottom-full left-1/2 -translate-x-1/2 mb-1.5",
    right: "left-full top-1/2 -translate-y-1/2 ml-1.5",
    bottom: "top-full left-1/2 -translate-x-1/2 mt-1.5",
    left: "right-full top-1/2 -translate-y-1/2 mr-1.5",
  };

  return (
    <span className={cn("relative inline-flex", className)}>
      {children({
        ref: triggerRef,
        onMouseEnter: () => setOpen(true),
        onMouseLeave: () => setOpen(false),
        onFocus: () => setOpen(true),
        onBlur: () => setOpen(false),
        "aria-describedby": tooltipId,
      })}
      {open && (
        <span
          role="tooltip"
          id={tooltipId}
          className={cn(
            "absolute z-50 pointer-events-none",
            "max-w-[280px] w-max px-2.5 py-1.5 rounded-md",
            "bg-bg-elevated border border-border shadow-lg",
            "text-[11px] leading-snug text-text",
            "animate-in fade-in zoom-in-95 duration-150",
            positionClass[side]
          )}
          style={{ "--tw-enter-scale": 0.95 } as CSSProperties}
        >
          {content}
        </span>
      )}
    </span>
  );
}

interface FieldInfoProps {
  /** Short purpose sentence. */
  purpose: string;
  /** Recommendation drawn from coaching-content.ts. */
  recommendation: string;
  /** Accessible label fallback. */
  label?: string;
  /** Preferred side (top by default). */
  side?: TooltipSide;
  /** Extra class on the trigger button. */
  className?: string;
}

/**
 * The standard "ⓘ" icon next to a form label — opens a two-line tooltip
 * (purpose + recommendation) on hover OR focus. Keyboard accessible.
 */
export function FieldInfo({
  purpose,
  recommendation,
  label,
  side = "top",
  className,
}: FieldInfoProps) {
  const ariaLabel = label
    ? `Informations sur ${label}`
    : "Informations sur ce champ";
  return (
    <Tooltip
      side={side}
      content={
        <span className="block space-y-1">
          <span className="block text-text">{purpose}</span>
          <span className="block text-accent font-medium">
            {recommendation}
          </span>
        </span>
      }
    >
      {(triggerProps) => (
        <button
          {...triggerProps}
          type="button"
          aria-label={ariaLabel}
          className={cn(
            "inline-flex items-center justify-center",
            "size-4 rounded text-text-subtle hover:text-accent",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
            "transition-colors",
            className
          )}
        >
          <Info size={12} aria-hidden="true" />
        </button>
      )}
    </Tooltip>
  );
}
