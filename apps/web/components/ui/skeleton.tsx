/**
 * Skeleton — pure CSS shimmer (M10). No GSAP, animation is the
 * `skeleton-shimmer` keyframe defined in globals.css and gated by the
 * global prefers-reduced-motion guard.
 */
import { cn } from "@/lib/utils";

interface SkeletonProps {
  className?: string;
  /** When true, the element renders as an inline-block (text). */
  inline?: boolean;
  "aria-label"?: string;
}

export function Skeleton({
  className,
  inline = false,
  "aria-label": ariaLabel,
}: SkeletonProps) {
  return (
    <span
      role="status"
      aria-busy="true"
      aria-label={ariaLabel ?? "Chargement"}
      className={cn(
        "skeleton",
        inline ? "inline-block align-middle" : "block",
        className
      )}
    />
  );
}
