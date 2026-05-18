"use client";

/**
 * GSAP animation helpers for the Sam avatar system.
 *
 * Every helper is wrapped in `gsap.matchMedia('(prefers-reduced-motion: no-preference)')`
 * so it only animates when the user has not asked for reduced motion. The
 * `else` branch (reduced motion) applies the final state synchronously via
 * `gsap.set` so layouts never look broken.
 *
 * All helpers return a cleanup function. Components should call it inside
 * the `useGSAP` cleanup or a `useEffect` return.
 */

import gsap from "gsap";

const PREFERENCE = "(prefers-reduced-motion: no-preference)";

type Target = gsap.TweenTarget | null | undefined;

/** Subtle idle float on the y-axis — repeats forever until cleanup. */
export function samIdleFloat(el: Target): () => void {
  if (!el) return () => {};
  const mm = gsap.matchMedia();

  mm.add(PREFERENCE, () => {
    const tween = gsap.to(el, {
      y: -3,
      duration: 3,
      ease: "sine.inOut",
      repeat: -1,
      yoyo: true,
    });
    return () => {
      tween.kill();
      gsap.set(el, { clearProps: "y,transform" });
    };
  });

  // Reduced-motion users get a flat resting position.
  if (typeof window !== "undefined" && !window.matchMedia(PREFERENCE).matches) {
    gsap.set(el, { y: 0 });
  }

  return () => mm.revert();
}

/**
 * Crossfade between two stacked `<img>` elements during a mood change.
 * `oldImg` fades out and shrinks slightly, `newImg` fades in and zooms back
 * to scale 1 with a soft ease. Both elements must be absolutely positioned
 * inside the same parent so the layout does not jump.
 */
export function samMoodTransition(oldImg: Target, newImg: Target): () => void {
  if (!newImg) return () => {};
  const mm = gsap.matchMedia();

  mm.add(PREFERENCE, () => {
    const tl = gsap.timeline();
    if (oldImg) {
      tl.to(
        oldImg,
        { opacity: 0, scale: 0.95, duration: 0.3, ease: "power2.out" },
        0
      );
    }
    tl.fromTo(
      newImg,
      { opacity: 0, scale: 1.05 },
      { opacity: 1, scale: 1, duration: 0.3, ease: "power2.out" },
      0
    );
    return () => {
      tl.kill();
    };
  });

  if (typeof window !== "undefined" && !window.matchMedia(PREFERENCE).matches) {
    if (oldImg) gsap.set(oldImg, { opacity: 0 });
    gsap.set(newImg, { opacity: 1, scale: 1 });
  }

  return () => mm.revert();
}

/** Slide-in entrance for `placement="card"` / `"fixed-corner"`. */
export function samWelcomeEntrance(el: Target): () => void {
  if (!el) return () => {};
  const mm = gsap.matchMedia();

  mm.add(PREFERENCE, () => {
    const tween = gsap.fromTo(
      el,
      { x: 24, opacity: 0, scale: 0.9 },
      { x: 0, opacity: 1, scale: 1, duration: 0.6, ease: "back.out(1.4)" }
    );
    return () => {
      tween.kill();
      gsap.set(el, { clearProps: "x,opacity,scale,transform" });
    };
  });

  if (typeof window !== "undefined" && !window.matchMedia(PREFERENCE).matches) {
    gsap.set(el, { x: 0, opacity: 1, scale: 1 });
  }

  return () => mm.revert();
}

/**
 * Quick attention pulse on the avatar ring. Used when a new mood/message
 * arrives via the store and the avatar is mounted as `fixed-corner` — the
 * pulse helps draw the user's eye without being noisy.
 */
export function samAttentionPulse(el: Target): () => void {
  if (!el) return () => {};
  const mm = gsap.matchMedia();

  mm.add(PREFERENCE, () => {
    const tl = gsap.timeline({ repeat: 1 });
    tl.to(el, {
      boxShadow: "0 0 0 6px rgba(6,182,212,0.35)",
      duration: 0.2,
      ease: "power2.out",
    }).to(el, {
      boxShadow: "0 0 0 0 rgba(6,182,212,0)",
      duration: 0.3,
      ease: "power2.in",
    });
    return () => {
      tl.kill();
      gsap.set(el, { clearProps: "boxShadow" });
    };
  });

  return () => mm.revert();
}

/** True when the user prefers reduced motion (SSR-safe). */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return !window.matchMedia(PREFERENCE).matches;
}
