/**
 * Reusable GSAP animation helpers for the /login traffic-lights theme.
 *
 * Each helper wraps its active animation in `gsap.matchMedia('(prefers-reduced-motion: no-preference)')`
 * so that users with `prefers-reduced-motion: reduce` get a sober/static final state instead of
 * continuous tweens. This is a GSAP performance/a11y best practice (severity High).
 *
 * Returned `MatchMedia` instances should be `.revert()`ed by the caller on cleanup. When used
 * inside `useGSAP({ scope })` the cleanup is automatic.
 */

import gsap from "gsap";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: no-preference)";

// ─────────────────────────────────────────────────────────────────────────────
// pulse — opacity 1 → 0.6 → 1 infinite loop. Useful for nodes, dots, idle CTAs.
// ─────────────────────────────────────────────────────────────────────────────

export interface PulseOptions {
  /** Duration (s) of half-cycle (1 -> 0.6). Default 1. */
  duration?: number;
  /** Min opacity at the bottom of the pulse. Default 0.6. */
  min?: number;
  /** Stagger value forwarded to GSAP when `el` resolves to multiple targets. */
  stagger?: number | gsap.StaggerVars;
  /** Start delay (s). Default 0. */
  delay?: number;
}

export function pulse(
  el: gsap.TweenTarget,
  options: PulseOptions = {}
): gsap.MatchMedia {
  const { duration = 1, min = 0.6, stagger, delay = 0 } = options;
  const mm = gsap.matchMedia();
  mm.add(REDUCED_MOTION_QUERY, () => {
    gsap.to(el, {
      opacity: min,
      duration,
      delay,
      ease: "sine.inOut",
      yoyo: true,
      repeat: -1,
      stagger,
    });
  });
  // reduced-motion: leave at final/idle state (opacity 1, no tween)
  return mm;
}

// ─────────────────────────────────────────────────────────────────────────────
// dashFlow — animate stroke-dashoffset to create a continuous "flow" effect
// on an SVG path. Performant: only touches a stroke attribute (no layout).
// ─────────────────────────────────────────────────────────────────────────────

export interface DashFlowOptions {
  /** Tween duration (s). Longer = slower flow. Default 14. */
  duration?: number;
  /** Reverse flow direction. Default false (positive offset). */
  reverse?: boolean;
  /** Start delay (s). Default 0. */
  delay?: number;
  /** Override the dash length used (must already be set via CSS or attr). */
  dashLength?: number;
}

export function dashFlow(
  path: SVGPathElement,
  options: DashFlowOptions = {}
): gsap.MatchMedia {
  const { duration = 14, reverse = false, delay = 0, dashLength } = options;
  const mm = gsap.matchMedia();
  mm.add(REDUCED_MOTION_QUERY, () => {
    // Use full path length if dashLength not provided — gives a single
    // unbroken flowing dash; combined with a dasharray on the SVG you get
    // the "stream" effect.
    const length =
      dashLength ?? (typeof path.getTotalLength === "function" ? path.getTotalLength() : 1000);
    gsap.fromTo(
      path,
      { strokeDashoffset: reverse ? -length : length },
      {
        strokeDashoffset: 0,
        duration,
        delay,
        ease: "none",
        repeat: -1,
      }
    );
  });
  return mm;
}

// ─────────────────────────────────────────────────────────────────────────────
// signalCycle — traffic-light cycle: red → amber → emerald → red.
// Each "on" state lifts opacity to 1 + scale 1.15 + adds a subtle glow shadow
// via `boxShadow` for ~800ms, then returns to dim base.
// ─────────────────────────────────────────────────────────────────────────────

export interface SignalCycleRefs {
  red: Element | null;
  amber: Element | null;
  green: Element | null;
}

export interface SignalCycleOptions {
  /** Total cycle duration (s). Default 3. */
  cycle?: number;
  /** Duration each light is "on" (s). Default 0.8. */
  onDuration?: number;
  /** Min opacity for the dim/off state. Default 0.3. */
  dim?: number;
  /** Color glow intensity in px for box-shadow blur. Default 8. */
  glow?: number;
}

export function signalCycle(
  refs: SignalCycleRefs,
  options: SignalCycleOptions = {}
): gsap.MatchMedia {
  const { cycle = 3, onDuration = 0.8, dim = 0.3, glow = 8 } = options;
  const mm = gsap.matchMedia();

  mm.add(REDUCED_MOTION_QUERY, () => {
    if (!refs.red || !refs.amber || !refs.green) return;
    const tl = gsap.timeline({ repeat: -1, defaults: { ease: "power1.inOut" } });
    const step = cycle / 3;

    const animateLight = (el: Element, startAt: number, color: string) => {
      tl.to(
        el,
        {
          opacity: 1,
          scale: 1.15,
          boxShadow: `0 0 ${glow}px ${color}`,
          duration: onDuration / 2,
        },
        startAt
      );
      tl.to(
        el,
        {
          opacity: dim,
          scale: 1,
          boxShadow: `0 0 0px ${color}`,
          duration: onDuration / 2,
        },
        startAt + onDuration / 2
      );
    };

    animateLight(refs.red, 0, "#ef4444");
    animateLight(refs.amber, step, "#f59e0b");
    animateLight(refs.green, step * 2, "#10b981");
    // Pad timeline to full cycle if onDuration < step*3
    tl.to({}, { duration: Math.max(0, cycle - (step * 2 + onDuration)) });
  });

  // reduced-motion: green stays "on", others dim. Applied unconditionally below
  // (matchMedia .add only fires when the query matches; this runs in all cases).
  if (refs.red) gsap.set(refs.red, { opacity: dim, scale: 1 });
  if (refs.amber) gsap.set(refs.amber, { opacity: dim, scale: 1 });
  if (refs.green) gsap.set(refs.green, { opacity: 1, scale: 1 });

  return mm;
}
