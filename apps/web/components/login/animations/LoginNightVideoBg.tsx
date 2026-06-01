"use client";

/**
 * LoginNightVideoBg
 * --------------------------------------------------------------
 * Full-bleed cinematic background for the /login page.
 *
 * Faithful React + GSAP port of the validated prototype
 * `prototypes/login-night-video-bg.html` (v1).
 *
 * Visual recipe:
 *   1. <video> — /video/login-night-bg.mp4 (top-down nighttime intersection)
 *   2. Vertical darken gradient (0.20 -> 0.70) keeps card legible
 *   3. Cyan/indigo radial tint, mix-blend-overlay
 *   4. SVG drift layer — 24 flat circles (18 cyan + 6 indigo) drifting
 *      downward at 38-72 px/s with a micro horizontal sway. No filters,
 *      no halos: only flat fills, so the night reads quiet and secure.
 *   5. Closed radial vignette (0 -> 0.75) focuses the center.
 *
 * SSR-safe : DOM/window access happens exclusively inside useGSAP /
 * useEffect. The 24 <circle> elements are pre-rendered server-side so
 * the layout is already correct on first paint ; GSAP only tweens
 * their attributes after hydration.
 *
 * Reduced motion : a gsap.matchMedia() query distributes the particles
 * statically (random cx/cy within the viewBox) and skips every tween.
 * The video itself loops at the browser level (we don't control its
 * playback rate, but the user has already opted-in by allowing autoplay
 * with prefers-reduced-motion ; HTMLMediaElement honours that signal
 * transparently across modern browsers).
 *
 * Z-index : 0 (NOT -10). The root body has an opaque bg-bg (#09090b)
 * that would cover any negative z-index. We sit at z=0, behind the
 * page content (z=10) and ahead of the body fill.
 */

import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import { useRef } from "react";
import { cn } from "@/lib/utils";

const VB_W = 1920;
const VB_H = 1080;
const PARTICLE_COUNT = 24;
const CYAN_COUNT = 18;

const rand = (a: number, b: number) => a + Math.random() * (b - a);

// Pre-computed deterministic seeds so the SSR markup matches the first
// client render and we avoid a hydration mismatch. After hydration we
// re-randomize cx/cy/opacity in useGSAP for an organic feel.
const PARTICLES_SEED = Array.from({ length: PARTICLE_COUNT }, (_, i) => {
  const kind: "cyan" | "indigo" = i < CYAN_COUNT ? "cyan" : "indigo";
  return {
    id: `p${i}`,
    kind,
    color: kind === "cyan" ? "#22d3ee" : "#6366f1",
  };
});

type ParticleState = {
  el: SVGCircleElement;
  kind: "cyan" | "indigo";
  cx: number;
  cy: number;
  r: number;
  opacity: number;
  speedYPerSec: number;
  driftXAmp: number;
  driftXPeriod: number;
  yTween: gsap.core.Tween | null;
  xTween: gsap.core.Tween | null;
};

interface LoginNightVideoBgProps {
  /** Override classes on the root wrapper (optional). */
  className?: string;
}

export function LoginNightVideoBg({ className }: LoginNightVideoBgProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const layerParticlesRef = useRef<SVGGElement>(null);

  useGSAP(
    () => {
      const layer = layerParticlesRef.current;
      if (!layer) return;

      // ------------------------------------------------------------------
      // Particle pool — recycle the 24 <circle> elements that React
      // server-rendered. We assign random initial state on the client
      // (avoids a hydration mismatch by leaving the SSR attributes
      // untouched until after mount).
      // ------------------------------------------------------------------
      const circles = Array.from(
        layer.querySelectorAll<SVGCircleElement>("circle"),
      );
      if (circles.length === 0) return;

      const particles: ParticleState[] = circles.map((el, i) => {
        const kind: "cyan" | "indigo" = i < CYAN_COUNT ? "cyan" : "indigo";
        const r = rand(1.2, 2.4);
        const opacity = rand(0.15, 0.35);
        const cx = rand(0, VB_W);
        const cy = rand(-50, VB_H);
        el.setAttribute("r", r.toFixed(2));
        el.setAttribute("cx", cx.toFixed(2));
        el.setAttribute("cy", cy.toFixed(2));
        el.setAttribute("opacity", opacity.toFixed(3));
        return {
          el,
          kind,
          cx,
          cy,
          r,
          opacity,
          speedYPerSec: rand(38, 72),
          driftXAmp: rand(0, 8),
          driftXPeriod: rand(6, 14),
          yTween: null,
          xTween: null,
        };
      });

      function restartXSway(p: ParticleState) {
        if (p.xTween) {
          p.xTween.kill();
          p.xTween = null;
        }
        if (p.driftXAmp < 0.1) return;
        const phase = { v: 0 };
        const base = p.cx;
        const amp = p.driftXAmp;
        p.xTween = gsap.to(phase, {
          v: Math.PI * 2,
          duration: p.driftXPeriod,
          ease: "sine.inOut",
          repeat: -1,
          onUpdate: () => {
            const offset = Math.sin(phase.v) * amp;
            p.el.setAttribute("cx", (base + offset).toFixed(2));
          },
        });
      }

      function startParticle(p: ParticleState) {
        const distance = 1130; // -50 -> 1080+50
        const duration = distance / p.speedYPerSec;

        p.el.setAttribute("cx", p.cx.toFixed(2));
        p.el.setAttribute("cy", p.cy.toFixed(2));
        p.el.setAttribute("opacity", p.opacity.toFixed(3));

        p.yTween = gsap.to(p.el, {
          attr: { cy: VB_H + 50 },
          duration,
          ease: "none",
          repeat: -1,
          delay: rand(0, 8),
          onRepeat: () => {
            // Re-randomize on each wrap for organic motion
            const newCx = rand(0, VB_W);
            const newCy = -50;
            const newOpac = rand(0.15, 0.35);
            const newSpeed = rand(38, 72);
            p.cx = newCx;
            p.cy = newCy;
            p.opacity = newOpac;
            p.speedYPerSec = newSpeed;

            p.el.setAttribute("cx", newCx.toFixed(2));
            p.el.setAttribute("cy", newCy.toFixed(2));
            p.el.setAttribute("opacity", newOpac.toFixed(3));

            if (p.yTween) {
              p.yTween.duration(distance / newSpeed);
              p.yTween.invalidate();
            }
            restartXSway(p);
          },
        });

        restartXSway(p);
      }

      function stopParticle(p: ParticleState) {
        if (p.yTween) {
          p.yTween.kill();
          p.yTween = null;
        }
        if (p.xTween) {
          p.xTween.kill();
          p.xTween = null;
        }
      }

      const mm = gsap.matchMedia();

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        particles.forEach(startParticle);
        return () => {
          particles.forEach(stopParticle);
        };
      });

      mm.add("(prefers-reduced-motion: reduce)", () => {
        // Static snapshot — distribute particles vertically without motion
        particles.forEach((p) => {
          const staticCy = rand(100, 980);
          const staticCx = rand(0, VB_W);
          p.cx = staticCx;
          p.cy = staticCy;
          p.el.setAttribute("cx", staticCx.toFixed(2));
          p.el.setAttribute("cy", staticCy.toFixed(2));
          p.el.setAttribute("opacity", p.opacity.toFixed(3));
        });
        return () => {
          // nothing to revert: no tween was created
        };
      });

      // useGSAP scope cleans up all tweens automatically; the matchMedia
      // revert handlers above kill any in-flight tween explicitly.
    },
    { scope: rootRef },
  );

  return (
    <div
      ref={rootRef}
      aria-hidden
      className={cn(
        // z-0 (NOT -z-10): body has an opaque background that would cover
        // negative z-indexes. We stay at 0, behind the page content (z-10)
        // and in front of the body fill.
        "pointer-events-none fixed inset-0 z-0 overflow-hidden",
        className,
      )}
    >
      {/* 1. Background video — top-down nighttime intersection.
          Production TODO : transcode login-night-bg.mp4 (~23 MB) into
          H.264 CRF 28 + WebM VP9 + JPG poster, then add <source> tags
          + poster below. Until those assets exist we keep the single
          mp4 source so the browser doesn't log 404s. */}
      <video
        className="absolute inset-0 h-full w-full object-cover [will-change:transform]"
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
        src="/video/login-night-bg.mp4"
      />

      {/* 2. Vertical darken — keeps the glass card legible above the video */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(180deg, rgba(9,9,11,0.20) 0%, rgba(9,9,11,0.35) 35%, rgba(9,9,11,0.55) 75%, rgba(9,9,11,0.70) 100%)",
        }}
      />

      {/* 3. Cyan/indigo radial tint, mix-blend-overlay */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at 50% 40%, rgba(34,211,238,0.06) 0%, rgba(99,102,241,0.04) 40%, rgba(9,9,11,0.20) 100%)",
          mixBlendMode: "overlay",
        }}
      />

      {/* 4. SVG drift particles — flat fills, no filter, no halo.
             24 circles pre-rendered server-side; GSAP only animates
             their attributes after hydration. */}
      <svg
        className="absolute inset-0 h-full w-full"
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        preserveAspectRatio="xMidYMid slice"
        aria-hidden
      >
        <g ref={layerParticlesRef} className="lnvb-layer-particles">
          {PARTICLES_SEED.map((p) => (
            <circle
              key={p.id}
              cx={0}
              cy={-100}
              r={0}
              fill={p.color}
              opacity={0}
            />
          ))}
        </g>
      </svg>

      {/* 5. Closed radial vignette — focus the center */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at center, rgba(9,9,11,0) 25%, rgba(9,9,11,0.35) 70%, rgba(9,9,11,0.75) 100%)",
        }}
      />
    </div>
  );
}

export default LoginNightVideoBg;
