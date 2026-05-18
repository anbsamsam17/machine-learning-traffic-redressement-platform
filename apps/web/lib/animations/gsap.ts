/**
 * GSAP helpers — reduced-motion aware.
 *
 * Every animation should be wrapped via `safeAnimate(scope, () => { ... })`
 * which uses `gsap.matchMedia()` to no-op when the user has
 * `prefers-reduced-motion: reduce`.
 */
import { gsap } from "gsap";

export { gsap };

export const EASE = {
  out: "power2.out",
  in: "power2.in",
  inOut: "power2.inOut",
  back: "back.out(1.5)",
} as const;

/**
 * Run animation code only if the user has NOT requested reduced motion.
 * `scope` lets GSAP track and revert tweens when the component unmounts.
 * Returns a cleanup function.
 */
export function safeAnimate(
  scope: HTMLElement | null,
  fn: () => void
): () => void {
  const mm = gsap.matchMedia(scope ?? undefined);
  mm.add("(prefers-reduced-motion: no-preference)", () => {
    fn();
  });
  return () => mm.revert();
}

/** M1 — Stepper transition. Animates the active step into place. */
export function stepperTransition(
  activeStepEl: HTMLElement | null,
  connectorEls: HTMLElement[],
  scope?: HTMLElement | null
) {
  if (!activeStepEl) return () => {};
  return safeAnimate(scope ?? activeStepEl.parentElement ?? null, () => {
    gsap.fromTo(
      activeStepEl,
      { scale: 0.92, opacity: 0.6 },
      { scale: 1, opacity: 1, duration: 0.3, ease: EASE.out }
    );
    if (connectorEls.length > 0) {
      gsap.fromTo(
        connectorEls,
        { scaleX: 0, transformOrigin: "left center" },
        {
          scaleX: 1,
          duration: 0.4,
          stagger: 0.06,
          ease: EASE.out,
        }
      );
    }
  });
}

/** M3 — Counter tween. Animates numeric textContent toward `to`. */
export function countTo(
  el: HTMLElement,
  to: number,
  format: (n: number) => string,
  duration = 1.0
) {
  // Always respect reduced motion globally — short-circuit here.
  if (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    el.textContent = format(to);
    return gsap.to({}, { duration: 0 });
  }
  const obj = { v: 0 };
  return gsap.to(obj, {
    v: to,
    duration,
    ease: EASE.out,
    onUpdate: () => {
      el.textContent = format(obj.v);
    },
  });
}

/** M5 — DropZone reception. Subtle scale on drag-enter. */
export function dropZonePulse(el: HTMLElement) {
  if (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    return;
  }
  gsap.fromTo(
    el,
    { scale: 1 },
    { scale: 1.01, duration: 0.18, ease: EASE.out, yoyo: true, repeat: 1 }
  );
}

/** M6 — Hover lift. Call inside mouseenter/leave handlers. */
export function hoverLift(el: HTMLElement, lift = -2) {
  if (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    return;
  }
  gsap.to(el, { y: lift, duration: 0.15, ease: EASE.out });
}
export function hoverReset(el: HTMLElement) {
  if (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    return;
  }
  gsap.to(el, { y: 0, duration: 0.15, ease: EASE.out });
}

/** M7 — Stagger-in cards/metrics. */
export function staggerIn(
  selector: string | Element[] | NodeList,
  scope?: HTMLElement | null
) {
  return safeAnimate(scope ?? null, () => {
    gsap.from(selector as gsap.TweenTarget, {
      opacity: 0,
      y: 8,
      duration: 0.3,
      stagger: 0.05,
      ease: EASE.out,
    });
  });
}
