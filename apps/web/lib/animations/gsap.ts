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

/** Stagger-in cards (M7) */
export function staggerIn(selector: string | Element[], scope?: HTMLElement | null) {
  return safeAnimate(scope ?? null, () => {
    gsap.from(selector, {
      opacity: 0,
      y: 8,
      duration: 0.3,
      stagger: 0.05,
      ease: EASE.out,
    });
  });
}

/** Hover lift (M6) — call inside event handlers, not in matchMedia */
export function hoverLift(el: HTMLElement, lift = -2) {
  gsap.to(el, { y: lift, duration: 0.15, ease: EASE.out });
}
export function hoverReset(el: HTMLElement) {
  gsap.to(el, { y: 0, duration: 0.15, ease: EASE.out });
}

/** Counter tween (M3) — animates numeric textContent toward `to`. */
export function countTo(el: HTMLElement, to: number, format: (n: number) => string) {
  const obj = { v: 0 };
  return gsap.to(obj, {
    v: to,
    duration: 1.2,
    ease: EASE.out,
    onUpdate: () => {
      el.textContent = format(obj.v);
    },
  });
}
