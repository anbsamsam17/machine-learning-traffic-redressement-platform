"use client";

/**
 * LoginBg — animated full-bleed background for /login.
 *
 * Layers (z-stacked, deepest first):
 *   1. <next/image> fill priority — cartoon-style futuristic cityscape (/bg/login.jpg).
 *      A neon dark-blue CSS gradient sits beneath so the layer degrades gracefully
 *      if the image ever fails to load — keeps the page on-brand without a 400/404.
 *   2. Dark overlay gradient to preserve foreground readability.
 *   3. SVG layer with stylized "cars" (12x6 rounded rects + cyan/indigo/warm-white headlight glows)
 *      following hand-tuned Bézier paths that approximate the roads visible in the image.
 *
 * Animation: pure requestAnimationFrame + SVGPathElement.getPointAtLength().
 * No GSAP / MotionPath / Framer dependency — keeps the bundle lean and avoids
 * premium plugins. Transform-only updates (translate / rotate via setAttribute on
 * a <g> wrapper), so the browser stays on the compositor for 60fps.
 *
 * Side "data streams" of binary digits scroll vertically at low opacity to match
 * the cyber-city aesthetic.
 *
 * A11y / perf:
 *   - aria-hidden on the whole layer, pointer-events: none.
 *   - Respects (prefers-reduced-motion: reduce) → cars rendered statically at
 *     equidistant positions along each path, no rAF loop.
 *   - willChange: 'transform' only on the moving <g> wrappers.
 */

import Image from "next/image";
import { useEffect, useRef } from "react";

// --- Path definitions ----------------------------------------------------
// Coordinates are in the SVG viewBox (1404 x 789, matches the source image),
// hand-tuned to roughly follow the central highway + bridges + side ramps
// visible in the background art. Exactness doesn't matter — coherence does.
const ROAD_PATHS: ReadonlyArray<{ id: string; d: string }> = [
  // Central highway: sweeps from the bottom-left toward the vanishing point
  { id: "road-main-1", d: "M -60 720 C 280 660, 560 540, 702 430 S 980 300, 1180 200" },
  // Central highway return lane: mirror, slightly offset for parallax
  { id: "road-main-2", d: "M 1460 720 C 1120 670, 860 550, 720 440 S 460 310, 240 210" },
  // Right-side elevated bridge: curves in from mid-right toward the city core
  { id: "road-bridge-r", d: "M 1450 510 C 1240 470, 1080 440, 940 410 S 760 380, 600 380" },
  // Left-side elevated bridge: lower-left ramp climbing into the skyline
  { id: "road-bridge-l", d: "M -40 580 C 180 540, 360 500, 520 460 S 760 420, 880 410" },
  // Foreground service road: shallow curve along the lower third
  { id: "road-front", d: "M -40 760 C 320 740, 700 720, 1040 700 S 1380 690, 1500 685" },
];

// --- Car definitions -----------------------------------------------------
// Each car is bound to one path with its own duration / delay / palette so the
// scene reads as fluid traffic rather than a synchronized parade.
type CarSpec = {
  pathId: string;
  duration: number; // seconds for a full traversal
  delay: number; // seconds before the first frame
  color: string; // body fill
  glow: string; // headlight color
  scale: number; // overall size multiplier (perspective hint)
};

const CARS: ReadonlyArray<CarSpec> = [
  { pathId: "road-main-1", duration: 22, delay: 0, color: "#06b6d4", glow: "#67e8f9", scale: 1.0 },
  { pathId: "road-main-1", duration: 26, delay: 7, color: "#8b5cf6", glow: "#c4b5fd", scale: 0.9 },
  { pathId: "road-main-2", duration: 24, delay: 3, color: "#fef3c7", glow: "#fde68a", scale: 1.0 },
  { pathId: "road-main-2", duration: 28, delay: 12, color: "#06b6d4", glow: "#67e8f9", scale: 0.85 },
  { pathId: "road-bridge-r", duration: 20, delay: 2, color: "#8b5cf6", glow: "#c4b5fd", scale: 0.95 },
  { pathId: "road-bridge-l", duration: 23, delay: 9, color: "#fef3c7", glow: "#fde68a", scale: 0.95 },
  { pathId: "road-front", duration: 30, delay: 5, color: "#06b6d4", glow: "#67e8f9", scale: 1.1 },
  { pathId: "road-front", duration: 33, delay: 17, color: "#8b5cf6", glow: "#c4b5fd", scale: 1.05 },
];

export function LoginBg() {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const carRefs = useRef<Array<SVGGElement | null>>([]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    // Resolve each car's path once + cache total length to avoid repeated DOM hits.
    type Bound = {
      car: SVGGElement;
      path: SVGPathElement;
      length: number;
      duration: number;
      delay: number;
    };

    const bounds: Bound[] = [];
    CARS.forEach((spec, idx) => {
      const car = carRefs.current[idx];
      const path = svg.querySelector<SVGPathElement>(`#${spec.pathId}`);
      if (!car || !path) return;
      bounds.push({
        car,
        path,
        length: path.getTotalLength(),
        duration: spec.duration,
        delay: spec.delay,
      });
    });

    if (bounds.length === 0) return;

    // Respect user motion preferences: place cars statically along their paths
    // at evenly spaced positions and skip the rAF loop entirely.
    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const placeCar = (b: Bound, progress: number) => {
      const dist = progress * b.length;
      const point = b.path.getPointAtLength(dist);
      // Tangent for car orientation: sample a tiny step ahead.
      const aheadDist = Math.min(b.length, dist + 1);
      const ahead = b.path.getPointAtLength(aheadDist);
      const angle = (Math.atan2(ahead.y - point.y, ahead.x - point.x) * 180) / Math.PI;
      b.car.setAttribute("transform", `translate(${point.x} ${point.y}) rotate(${angle})`);
    };

    if (reduceMotion) {
      bounds.forEach((b, i) => {
        const progress = (i + 1) / (bounds.length + 1);
        placeCar(b, progress);
      });
      return;
    }

    let rafId = 0;
    const start = performance.now();

    const tick = (now: number) => {
      const elapsedSec = (now - start) / 1000;
      for (const b of bounds) {
        // (elapsed - delay) wrapped into [0, duration), then normalized to [0,1].
        const local = ((elapsedSec - b.delay) % b.duration + b.duration) % b.duration;
        const progress = local / b.duration;
        placeCar(b, progress);
      }
      rafId = requestAnimationFrame(tick);
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);

  return (
    <div
      aria-hidden="true"
      className="absolute inset-0 -z-10 pointer-events-none overflow-hidden"
      // CSS gradient acts as a brand-coherent fallback: if /bg/login.jpg
      // ever 404s (or Next/image rejects its profile), the layout still
      // reads as "cyber night" instead of a blank flash. Replaces the old
      // /bg-traffic-night.jpg reference, which was returning 400 from
      // /_next/image (see APP-P1-3 / QA_B5).
      style={{
        background:
          "linear-gradient(180deg, #0b1230 0%, #0a0e22 45%, #050714 100%)",
      }}
    >
      {/* Cartoon cityscape backdrop */}
      <Image
        src="/bg/login.jpg"
        alt=""
        fill
        priority
        sizes="100vw"
        className="object-cover object-center select-none"
      />

      {/* Readability overlay — strengthened so the cityscape never out-shouts
         foreground text. The angled gradient leans darker on the right where
         the LoginForm card sits, preserving WCAG AA contrast for body copy. */}
      <div className="absolute inset-0 bg-gradient-to-b from-zinc-950/65 via-zinc-950/55 to-zinc-950/75" />
      <div className="absolute inset-0 bg-gradient-to-r from-zinc-950/35 via-transparent to-zinc-950/45" />

      {/* Side data streams (decorative binary rain) */}
      <DataStream side="left" />
      <DataStream side="right" />

      {/* Animated traffic layer */}
      <svg
        ref={svgRef}
        viewBox="0 0 1404 789"
        preserveAspectRatio="xMidYMid slice"
        className="absolute inset-0 h-full w-full"
      >
        <defs>
          {/* Soft halo around each car's headlight */}
          <filter id="login-bg-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Hidden road paths (purely as motion guides). */}
        <g fill="none" stroke="none">
          {ROAD_PATHS.map((p) => (
            <path key={p.id} id={p.id} d={p.d} />
          ))}
        </g>

        {/* Car sprites — initial transform set inside the effect. */}
        <g>
          {CARS.map((spec, i) => (
            <g
              key={`${spec.pathId}-${i}`}
              ref={(el) => {
                carRefs.current[i] = el;
              }}
              style={{ willChange: "transform" }}
              filter="url(#login-bg-glow)"
            >
              {/* Body */}
              <rect
                x={-6 * spec.scale}
                y={-3 * spec.scale}
                width={12 * spec.scale}
                height={6 * spec.scale}
                rx={2 * spec.scale}
                fill={spec.color}
                opacity={0.85}
              />
              {/* Headlight cone (front of the car at +x) */}
              <circle
                cx={7 * spec.scale}
                cy={0}
                r={1.6 * spec.scale}
                fill={spec.glow}
                opacity={0.95}
              />
              {/* Trailing taillight */}
              <circle
                cx={-7 * spec.scale}
                cy={0}
                r={1.0 * spec.scale}
                fill="#f43f5e"
                opacity={0.7}
              />
            </g>
          ))}
        </g>
      </svg>
    </div>
  );
}

// --- Data stream side decoration ---------------------------------------
// Pure CSS-driven vertical loop; the keyframes live inline below. No JS clock.
const STREAM_CHARS = "10110100101010110100110101001010110010101101001010110100110100";

function DataStream({ side }: { side: "left" | "right" }) {
  const cols = side === "left" ? ["left-[3%]", "left-[7%]"] : ["right-[3%]", "right-[7%]"];
  return (
    <>
      <style>{`
        @keyframes login-bg-stream {
          0%   { transform: translateY(-50%); }
          100% { transform: translateY(0%); }
        }
        @media (prefers-reduced-motion: reduce) {
          .login-bg-stream { animation: none !important; }
        }
      `}</style>
      {cols.map((pos, i) => (
        <div
          key={pos}
          className={`absolute top-0 ${pos} h-[200%] font-mono text-[10px] leading-[14px] tracking-widest text-cyan-300/15 select-none login-bg-stream`}
          style={{
            animation: `login-bg-stream ${60 + i * 25}s linear infinite`,
            writingMode: "vertical-rl",
            willChange: "transform",
          }}
        >
          {STREAM_CHARS.repeat(8)}
        </div>
      ))}
    </>
  );
}
