"use client";

/**
 * LandingBg
 * --------------------------------------------------------------
 * Full-bleed animated background for the post-login landing page.
 *
 * Layers, back-to-front:
 *   1. /bg/landing.jpg (next/image, fill+priority, object-cover)
 *   2. Strong dark gradient overlay  — tames the bright source
 *      image so the landing content (cards, stats) stays readable.
 *   3. Subtle radial vignette        — pulls the eye to centre.
 *   4. SVG "data streams"            — 4 Bézier paths + travelling
 *      neon dots (cyan / indigo / magenta), animated via rAF.
 *   5. Two binary "0 1 0 1..." rain columns on the outer edges.
 *
 * The whole component is `pointer-events-none` and sits at `-z-10`
 * so it never intercepts content interactions.
 *
 * No props are required — the component is fully self-contained
 * and intended to be dropped into `app/page.tsx` once.
 */

import Image from "next/image";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import {
  binaryRain,
  makeBinaryGlyphs,
  streamFlow,
} from "@/lib/animations/data-stream";

type LandingBgProps = {
  /** Override classes for the wrapper. */
  className?: string;
};

// ----------------------------------------------------------------
// Stream definitions
//
// SVG viewBox is 1400x789 to roughly match the source image.
// Paths are loosely traced over the binary arcs visible in the
// skyline so the animated dots feel anchored to the scene.
// ----------------------------------------------------------------

type StreamDef = {
  id: string;
  d: string;
  color: string;
  duration: number;
  delay: number;
};

const STREAMS: ReadonlyArray<StreamDef> = [
  {
    id: "s1",
    d: "M 80 220 C 320 80, 620 80, 880 240 S 1280 420, 1340 300",
    color: "#22d3ee", // cyan-400
    duration: 11_000,
    delay: 0,
  },
  {
    id: "s2",
    d: "M 60 540 C 280 380, 540 380, 760 480 S 1180 620, 1360 500",
    color: "#a78bfa", // violet-400
    duration: 13_500,
    delay: 1_800,
  },
  {
    id: "s3",
    d: "M 200 720 C 360 540, 620 540, 760 660 S 1080 760, 1240 640",
    color: "#f472b6", // pink-400 / magenta
    duration: 9_500,
    delay: 600,
  },
  {
    id: "s4",
    d: "M 40 380 C 260 220, 540 260, 700 360 S 1080 460, 1360 360",
    color: "#67e8f9", // cyan-300
    duration: 14_500,
    delay: 3_200,
  },
];

// Vertical binary columns (left + right gutters).
const BINARY_COLUMNS: ReadonlyArray<{
  side: "left" | "right";
  offset: string;
  duration: number;
  phase: number;
}> = [
  { side: "left", offset: "2%", duration: 38_000, phase: 0 },
  { side: "right", offset: "2%", duration: 42_000, phase: 0.45 },
];

const GLYPH_COUNT = 60;

export function LandingBg({ className }: LandingBgProps): React.JSX.Element {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const leftColRef = useRef<HTMLDivElement | null>(null);
  const rightColRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const cleanups: Array<() => void> = [];

    // ---- Data streams ----
    const svg = svgRef.current;
    if (svg) {
      for (const def of STREAMS) {
        const path = svg.querySelector<SVGPathElement>(
          `#path-${def.id}`,
        );
        const dot = svg.querySelector<SVGGraphicsElement>(
          `#dot-${def.id}`,
        );
        if (!path || !dot) continue;
        cleanups.push(
          streamFlow(dot, path, {
            duration: def.duration,
            delay: def.delay,
          }),
        );
      }
    }

    // ---- Binary rain columns ----
    const left = leftColRef.current;
    if (left) {
      cleanups.push(
        binaryRain(left, {
          duration: BINARY_COLUMNS[0].duration,
          phase: BINARY_COLUMNS[0].phase,
        }),
      );
    }
    const right = rightColRef.current;
    if (right) {
      cleanups.push(
        binaryRain(right, {
          duration: BINARY_COLUMNS[1].duration,
          phase: BINARY_COLUMNS[1].phase,
        }),
      );
    }

    return () => {
      for (const c of cleanups) c();
    };
  }, []);

  // Pre-build glyph strings once per mount (stable across renders).
  // useState's lazy initialiser guarantees a single evaluation and
  // — unlike a ref — is safe to read during render.
  const [leftGlyphs] = useState(() => makeBinaryGlyphs(GLYPH_COUNT));
  const [rightGlyphs] = useState(() => makeBinaryGlyphs(GLYPH_COUNT));

  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-0 -z-10 overflow-hidden",
        className,
      )}
    >
      {/* 1. Source image ------------------------------------------------ */}
      <Image
        src="/bg/landing.jpg"
        alt=""
        aria-hidden
        fill
        priority
        sizes="100vw"
        className="object-cover object-center"
      />

      {/* 2. Dark gradient overlay -------------------------------------- */}
      <div
        className={cn(
          "absolute inset-0",
          "bg-gradient-to-b from-zinc-950/60 via-zinc-950/70 to-zinc-950/80",
        )}
      />

      {/* 3. Vignette ---------------------------------------------------- */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(ellipse at center, transparent 0%, rgba(9, 9, 11, 0.4) 70%, rgba(9, 9, 11, 0.7) 100%)",
        }}
      />

      {/* 4. SVG data streams ------------------------------------------- */}
      <svg
        ref={svgRef}
        className="absolute inset-0 h-full w-full opacity-50 [mix-blend-mode:screen]"
        viewBox="0 0 1400 789"
        preserveAspectRatio="xMidYMid slice"
        fill="none"
      >
        <defs>
          {STREAMS.map((s) => (
            <radialGradient
              key={`grad-${s.id}`}
              id={`grad-${s.id}`}
              cx="50%"
              cy="50%"
              r="50%"
            >
              <stop offset="0%" stopColor={s.color} stopOpacity="1" />
              <stop offset="60%" stopColor={s.color} stopOpacity="0.55" />
              <stop offset="100%" stopColor={s.color} stopOpacity="0" />
            </radialGradient>
          ))}
        </defs>

        {STREAMS.map((s) => (
          <g key={s.id}>
            {/* Invisible reference path the dot follows. */}
            <path
              id={`path-${s.id}`}
              d={s.d}
              stroke={s.color}
              strokeOpacity="0.08"
              strokeWidth="1"
            />
            {/* The moving "data packet". */}
            <g id={`dot-${s.id}`} style={{ willChange: "transform, opacity" }}>
              <circle r="14" fill={`url(#grad-${s.id})`} />
              <circle r="3" fill={s.color} />
            </g>
          </g>
        ))}
      </svg>

      {/* 5. Binary rain columns ---------------------------------------- */}
      <div className="absolute inset-y-0 left-0 w-[6%] overflow-hidden">
        <div
          ref={leftColRef}
          className="absolute inset-x-0 top-0 flex flex-col items-center font-mono text-[10px] leading-[1.6] tracking-widest text-cyan-300/30 [writing-mode:vertical-rl] sm:text-xs"
          style={{
            transform: "translate3d(0, 100%, 0)",
            willChange: "transform",
          }}
        >
          <span className="whitespace-nowrap">{leftGlyphs}</span>
          <span className="whitespace-nowrap">{leftGlyphs}</span>
        </div>
      </div>

      <div className="absolute inset-y-0 right-0 w-[6%] overflow-hidden">
        <div
          ref={rightColRef}
          className="absolute inset-x-0 top-0 flex flex-col items-center font-mono text-[10px] leading-[1.6] tracking-widest text-fuchsia-300/25 [writing-mode:vertical-rl] sm:text-xs"
          style={{
            transform: "translate3d(0, 100%, 0)",
            willChange: "transform",
          }}
        >
          <span className="whitespace-nowrap">{rightGlyphs}</span>
          <span className="whitespace-nowrap">{rightGlyphs}</span>
        </div>
      </div>
    </div>
  );
}

export default LandingBg;
