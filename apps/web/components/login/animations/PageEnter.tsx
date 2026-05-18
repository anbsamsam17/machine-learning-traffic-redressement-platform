"use client";

/**
 * Wrapper that staggers in any descendant with `[data-enter]` on mount.
 * Defaults to a soft "rise + fade" (opacity 0 → 1, y 10 → 0) over 500ms with
 * 100ms stagger and `power2.out` easing.
 *
 * Reduced motion: elements appear immediately at their final state (no .from()).
 * Cleanup is automatic via useGSAP's scope.
 *
 * Usage:
 *   <PageEnter>
 *     <h1 data-enter>Title</h1>
 *     <p data-enter>Subtitle</p>
 *     <form data-enter>...</form>
 *   </PageEnter>
 */

import { useRef, type ReactNode } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";

interface PageEnterProps {
  children: ReactNode;
  /** Stagger between elements (s). Default 0.1. */
  staggerDelay?: number;
  /** Optional className passed to the wrapper. */
  className?: string;
}

export function PageEnter({
  children,
  staggerDelay = 0.1,
  className,
}: PageEnterProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      if (!containerRef.current) return;
      const targets = containerRef.current.querySelectorAll<HTMLElement>("[data-enter]");
      if (targets.length === 0) return;

      const mm = gsap.matchMedia();

      // Active animation only when user has not requested reduced motion
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.from(targets, {
          opacity: 0,
          y: 10,
          duration: 0.5,
          ease: "power2.out",
          stagger: staggerDelay,
          // Avoid any FOUC: ensure final state stays at 1 / 0
          clearProps: "transform,opacity",
        });
      });

      // Reduced motion: leave elements at their natural rendered state — no-op.
      // (Default DOM state already has opacity 1 / y 0, so nothing to do.)
    },
    { scope: containerRef, dependencies: [staggerDelay] }
  );

  return (
    <div ref={containerRef} className={className}>
      {children}
    </div>
  );
}

export default PageEnter;
