/**
 * Sam Cutout — GSAP animation helpers for the detoured (transparent PNG) Sam avatar.
 *
 * All helpers are wrapped in `gsap.matchMedia('(prefers-reduced-motion: no-preference)')`
 * so users who opted out of motion receive a still avatar. Each helper returns the
 * `MatchMedia` instance so callers can call `.revert()` to fully clean up (kills any
 * tweens it produced and restores inline styles).
 *
 * Design notes:
 *  - Sam is a single transparent image — no skeleton — so we animate the whole node
 *    via transform + opacity only (60fps cheap).
 *  - Pivots are configured via `transformOrigin` per-helper so rotations feel natural
 *    (e.g. wave pivots around the bottom-center, not the geometric center).
 *  - Nothing here triggers layout / paint other than the cheap transform/opacity loop.
 *  - All animations are SSR-safe at the *module* level: gsap is imported lazily inside
 *    each helper via a top-level import, but no DOM/window access occurs until the
 *    helper is called by a client component.
 */

import { gsap } from "gsap";

/** Public target type: any GSAP-acceptable target (Element, ref.current, selector). */
export type SamTarget = gsap.TweenTarget;

/**
 * Discriminated union of supported moods. Kept in sync with `apps/web/lib/sam/moods.ts`
 * but redeclared here so this module has no cross-dep on Sam state.
 */
export type SamMood = "welcome" | "based" | "working" | "goodjob" | "error";

/** Return value of every helper. Caller may `.revert()` to kill + restore inline styles. */
export type SamAnim = gsap.MatchMedia;

/* -------------------------------------------------------------------------- */
/* Internal utilities                                                         */
/* -------------------------------------------------------------------------- */

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: no-preference)";

/**
 * Run `build(ctx)` only when motion is allowed. The returned `MatchMedia` is the cleanup
 * handle. Always set `transformOrigin` and (optionally) `willChange` inside `build`.
 */
function withMotion(build: (ctx: gsap.Context) => void): SamAnim {
  const mm = gsap.matchMedia();
  mm.add(REDUCED_MOTION_QUERY, (context) => {
    build(context);
    // `mm.revert()` will call ctx.revert() and undo any inline styles GSAP set.
  });
  return mm;
}

/* -------------------------------------------------------------------------- */
/* 1. samWave — Welcome greeting                                               */
/* -------------------------------------------------------------------------- */

/**
 * `samWave` — playful greeting animation for the **welcome** mood.
 *
 * Combines a subtle vertical "lift" with two rotational wobbles (±6deg) and a tiny
 * opacity pulse. Pivot is bottom-center so Sam appears to nod hello from his feet
 * rather than spinning around his middle. Plays once (~1.6s total).
 *
 * @param el  GSAP target (element, ref.current, or selector inside a scoped context)
 * @returns   MatchMedia handle — call `.revert()` on unmount
 */
export function samWave(el: SamTarget): SamAnim {
  return withMotion(() => {
    const tl = gsap.timeline({
      defaults: { ease: "sine.inOut", transformOrigin: "50% 100%" },
    });
    tl.set(el, { willChange: "transform, opacity", transformOrigin: "50% 100%" })
      // Lift + slight scale (Sam "raises" to greet)
      .to(el, { y: -6, scale: 1.03, duration: 0.32, ease: "power2.out" })
      // Wave 1
      .to(el, { rotate: 6, duration: 0.18 })
      .to(el, { rotate: -6, duration: 0.22 })
      // Wave 2 (smaller, decay)
      .to(el, { rotate: 4, duration: 0.18 })
      .to(el, { rotate: -3, duration: 0.18 })
      // Settle
      .to(el, { rotate: 0, y: 0, scale: 1, duration: 0.36, ease: "power2.inOut" })
      .set(el, { willChange: "auto" });
  });
}

/* -------------------------------------------------------------------------- */
/* 2. samFloat — Idle bounce loop                                              */
/* -------------------------------------------------------------------------- */

/**
 * `samFloat` — gentle infinite idle bobbing.
 *
 * ±4px vertical translation, 3s per cycle, sine.inOut, yoyo + repeat -1. Cheap loop,
 * intended as Sam's "default" state when no other mood animation is playing.
 *
 * @param el  GSAP target
 * @returns   MatchMedia handle — call `.revert()` to stop and reset
 */
export function samFloat(el: SamTarget): SamAnim {
  return withMotion(() => {
    gsap.to(el, {
      y: -4,
      duration: 1.5,
      ease: "sine.inOut",
      yoyo: true,
      repeat: -1,
    });
  });
}

/* -------------------------------------------------------------------------- */
/* 3. samBounce — Goodjob celebration                                          */
/* -------------------------------------------------------------------------- */

/**
 * `samBounce` — bouncy celebration animation for the **goodjob** mood.
 *
 * Combines an upward leap (-8px) with squash-and-stretch scale (1 → 1.1 → 0.95 → 1)
 * over ~600ms, finishing with `back.out(2)` for cartoon-y settle. Plays once.
 *
 * @param el  GSAP target
 * @returns   MatchMedia handle
 */
export function samBounce(el: SamTarget): SamAnim {
  return withMotion(() => {
    const tl = gsap.timeline({
      defaults: { transformOrigin: "50% 100%" },
    });
    tl.set(el, { willChange: "transform", transformOrigin: "50% 100%" })
      .to(el, { y: -8, scaleY: 1.1, scaleX: 0.95, duration: 0.22, ease: "power2.out" })
      .to(el, { y: 0, scaleY: 0.95, scaleX: 1.05, duration: 0.18, ease: "power1.in" })
      .to(el, { scaleY: 1, scaleX: 1, duration: 0.22, ease: "back.out(2)" })
      .set(el, { willChange: "auto" });
  });
}

/* -------------------------------------------------------------------------- */
/* 4. samShake — Error horizontal shake                                        */
/* -------------------------------------------------------------------------- */

/**
 * `samShake` — sharp horizontal shake for the **error** mood.
 *
 * 7-keyframe X translation (0 → -8 → 8 → -6 → 6 → -3 → 3 → 0) over ~400ms with
 * `power2.inOut`. Pivot stays centered. Plays once.
 *
 * @param el  GSAP target
 * @returns   MatchMedia handle
 */
export function samShake(el: SamTarget): SamAnim {
  return withMotion(() => {
    const tl = gsap.timeline({ defaults: { ease: "power2.inOut" } });
    tl.set(el, { willChange: "transform" })
      .to(el, { x: -8, duration: 0.055 })
      .to(el, { x: 8, duration: 0.06 })
      .to(el, { x: -6, duration: 0.06 })
      .to(el, { x: 6, duration: 0.06 })
      .to(el, { x: -3, duration: 0.055 })
      .to(el, { x: 3, duration: 0.055 })
      .to(el, { x: 0, duration: 0.06 })
      .set(el, { willChange: "auto" });
  });
}

/* -------------------------------------------------------------------------- */
/* 7. samCleanup — Kill all tweens on a target                                 */
/* -------------------------------------------------------------------------- */

/**
 * `samCleanup` — kill every active tween/timeline touching `el` and clear any
 * willChange residue. Use on unmount or before re-triggering a mood animation
 * when you don't have a reference to the `MatchMedia` handle.
 *
 * Note: This **kills** tweens but does NOT revert inline styles. For full revert
 * including style restoration, hold the `SamAnim` handle returned by each helper
 * and call `.revert()` on it.
 */
export function samCleanup(el: SamTarget): void {
  gsap.killTweensOf(el);
  // Best-effort: clear willChange + transform when target is a single element.
  if (typeof el === "object" && el !== null && "style" in (el as HTMLElement)) {
    const node = el as HTMLElement;
    node.style.willChange = "auto";
  }
}
