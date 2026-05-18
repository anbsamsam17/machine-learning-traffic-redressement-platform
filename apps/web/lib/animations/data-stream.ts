/**
 * data-stream.ts
 *
 * Lightweight, dependency-free helpers for the landing background animations.
 *
 * Two primitives are exposed:
 *
 *   - streamFlow(dot, path, options)
 *       Slides an SVG element along an SVGPathElement using
 *       getPointAtLength(). Loops forever with a configurable
 *       duration and easing. Returns a cleanup function.
 *
 *   - binaryRain(container, options)
 *       Spawns a vertical column of "0 1 0 1..." glyphs and
 *       tweens its `translateY` from bottom to top in a loop.
 *       Returns a cleanup function.
 *
 * Both helpers respect `prefers-reduced-motion` at call time —
 * they no-op (or render a static frame) when the user opts out.
 *
 * Notes:
 *   - We deliberately avoid GSAP / framer-motion here; the
 *     animations are slow + few enough that vanilla rAF is fine
 *     and keeps the bundle untouched.
 *   - Only `transform` / `opacity` are mutated → cheap to composite.
 */

export type StreamFlowOptions = {
  /** Duration of one full path traversal, in ms. */
  duration?: number;
  /** Delay before the first cycle, in ms. */
  delay?: number;
  /** Easing function, takes t in [0,1] returns [0,1]. */
  ease?: (t: number) => number;
  /** Respect prefers-reduced-motion (default true). */
  respectReducedMotion?: boolean;
};

const easeInOutSine = (t: number): number =>
  -(Math.cos(Math.PI * t) - 1) / 2;

/**
 * Slide `dot` (typically an SVG <circle>) along `path` forever.
 * Returns a cleanup function that cancels the rAF loop.
 */
export function streamFlow(
  dot: SVGGraphicsElement,
  path: SVGPathElement,
  options: StreamFlowOptions = {},
): () => void {
  const {
    duration = 10_000,
    delay = 0,
    ease = easeInOutSine,
    respectReducedMotion = true,
  } = options;

  const reduced =
    respectReducedMotion &&
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const total = path.getTotalLength();

  // Static frame for reduced-motion users: park the dot mid-path
  // so the SVG still looks composed instead of empty.
  if (reduced) {
    const mid = path.getPointAtLength(total * 0.5);
    dot.setAttribute("transform", `translate(${mid.x} ${mid.y})`);
    dot.setAttribute("opacity", "0.6");
    return () => {};
  }

  let raf = 0;
  let start = 0;
  let cancelled = false;

  const tick = (now: number) => {
    if (cancelled) return;
    if (!start) start = now + delay;
    const elapsed = now - start;

    if (elapsed < 0) {
      raf = requestAnimationFrame(tick);
      return;
    }

    const t = (elapsed % duration) / duration;
    const eased = ease(t);
    const p = path.getPointAtLength(total * eased);

    // Fade in/out at the endpoints so the dot doesn't pop.
    const opacity =
      t < 0.08 ? t / 0.08 : t > 0.92 ? (1 - t) / 0.08 : 1;

    dot.setAttribute("transform", `translate(${p.x} ${p.y})`);
    dot.setAttribute("opacity", String(opacity));

    raf = requestAnimationFrame(tick);
  };

  raf = requestAnimationFrame(tick);

  return () => {
    cancelled = true;
    if (raf) cancelAnimationFrame(raf);
  };
}

export type BinaryRainOptions = {
  /** Duration of one full bottom→top traversal, in ms. */
  duration?: number;
  /** Number of glyphs in the column. */
  glyphCount?: number;
  /** Initial offset (0..1) so columns desynchronise. */
  phase?: number;
  /** Respect prefers-reduced-motion (default true). */
  respectReducedMotion?: boolean;
};

/**
 * Animate `column` (a vertical container of "0 1 0 1..." text)
 * by translating it from bottom to top in a slow loop.
 *
 * The caller is responsible for the column's intrinsic content
 * and styling — we only mutate `transform`.
 */
export function binaryRain(
  column: HTMLElement,
  options: BinaryRainOptions = {},
): () => void {
  const {
    duration = 35_000,
    phase = 0,
    respectReducedMotion = true,
  } = options;

  const reduced =
    respectReducedMotion &&
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (reduced) {
    // Keep the column in view, no animation.
    column.style.transform = "translate3d(0, 0, 0)";
    return () => {};
  }

  let raf = 0;
  let start = 0;
  let cancelled = false;

  // Column slides from +100% (below view) to -100% (above view).
  // We use translate3d to nudge the browser onto a compositor layer.
  const tick = (now: number) => {
    if (cancelled) return;
    if (!start) start = now;
    const elapsed = now - start;
    const t = ((elapsed / duration) + phase) % 1;
    const yPct = 100 - t * 200; // 100 → -100
    column.style.transform = `translate3d(0, ${yPct}%, 0)`;
    raf = requestAnimationFrame(tick);
  };

  raf = requestAnimationFrame(tick);

  return () => {
    cancelled = true;
    if (raf) cancelAnimationFrame(raf);
  };
}

/**
 * Build a string of N space-separated random bits ("0" / "1").
 * Pure helper, useful when seeding a binaryRain column.
 */
export function makeBinaryGlyphs(count: number): string {
  let s = "";
  for (let i = 0; i < count; i++) {
    s += (Math.random() < 0.5 ? "0" : "1") + (i < count - 1 ? " " : "");
  }
  return s;
}
