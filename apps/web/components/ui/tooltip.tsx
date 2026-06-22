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
  // Auto-flip horizontal alignment when the trigger is near a viewport edge.
  // Default "center"; switched to "start" or "end" if the centered popover
  // would clip horizontally (avoids the "tooltips cut off" bug reported by
  // testers when info-bubbles sit near the right edge of the ML section).
  const [align, setAlign] = useState<"start" | "center" | "end">("center");
  // Same for vertical: flip to "bottom" if there's not enough room above.
  const [resolvedSide, setResolvedSide] = useState<TooltipSide>(side);

  // Dismiss on Escape (only when open).
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // Recompute alignment when opening — uses the trigger's rect to decide
  // whether a centered, left-anchored, or right-anchored popover fits.
  // Intentional layout-measurement effect: reads the DOM rect and stores the
  // resolved alignment/side in state (cannot be derived during render).
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!open) return;
    const el = triggerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const POPOVER_MAX_WIDTH = 280;
    const POPOVER_MAX_HEIGHT = 140;
    const MARGIN = 8;

    if (side === "top" || side === "bottom") {
      const centerX = rect.left + rect.width / 2;
      const halfPopover = POPOVER_MAX_WIDTH / 2;
      if (centerX - halfPopover < MARGIN) {
        setAlign("start");
      } else if (centerX + halfPopover > vw - MARGIN) {
        setAlign("end");
      } else {
        setAlign("center");
      }
      // Vertical flip
      if (side === "top" && rect.top < POPOVER_MAX_HEIGHT + MARGIN) {
        setResolvedSide("bottom");
      } else if (
        side === "bottom" &&
        vh - rect.bottom < POPOVER_MAX_HEIGHT + MARGIN
      ) {
        setResolvedSide("top");
      } else {
        setResolvedSide(side);
      }
    } else {
      setResolvedSide(side);
    }
  }, [open, side]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // Position offsets — combine side (top/bottom/right/left) with horizontal
  // align (start/center/end) for vertical sides.
  function positionClass(s: TooltipSide, a: "start" | "center" | "end"): string {
    if (s === "right")
      return "left-full top-1/2 -translate-y-1/2 ml-1.5";
    if (s === "left") return "right-full top-1/2 -translate-y-1/2 mr-1.5";
    const vertical = s === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5";
    if (a === "start") return `${vertical} left-0`;
    if (a === "end") return `${vertical} right-0`;
    return `${vertical} left-1/2 -translate-x-1/2`;
  }

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
            "max-w-[min(280px,calc(100vw-16px))] w-max px-2.5 py-1.5 rounded-md",
            "bg-bg-elevated border border-border shadow-lg",
            "text-[11px] leading-snug text-text break-words",
            "animate-in fade-in zoom-in-95 duration-150",
            positionClass(resolvedSide, align)
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
