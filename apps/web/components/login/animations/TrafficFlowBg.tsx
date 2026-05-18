"use client";

/**
 * Full-bleed animated background for /login.
 *
 * 4 stylised "highway" curves (Bezier paths) sit on a subtle radial gradient.
 * Each path has its own dasharray + dashoffset tween (different durations) so
 * the flow is desynced and reads as organic traffic.
 *
 * Performance:
 *  - Only `stroke-dashoffset` is tweened (no width/height/layout).
 *  - Single SVG, single root opacity → cheap composite.
 *  - `pointer-events-none` and `-z-10` keep it out of interaction tree.
 *  - Respects `prefers-reduced-motion` via gsap.matchMedia — paths visible but static.
 */

import { useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { dashFlow } from "@/lib/animations/traffic";

interface PathConfig {
  /** SVG `d` attribute. */
  d: string;
  /** stroke color (hex). */
  stroke: string;
  /** dasharray (length, gap) — controls the visual "chunk" pattern. */
  dasharray: string;
  /** Tween duration in seconds; longer = slower flow. */
  duration: number;
  /** Stroke width px. */
  width: number;
  /** Reverse the flow direction. */
  reverse?: boolean;
}

// 4 paths: 2 cyan (FCD/floating car data theme), 1 indigo (model lane),
// 1 amber (warning/calibration lane). Curves are wide and shallow to read
// as bird-eye highways without dominating the viewport.
const PATHS: PathConfig[] = [
  {
    // long sweeping cyan curve, top-left → bottom-right
    d: "M -50 200 C 300 100, 700 500, 1450 300",
    stroke: "#06b6d4",
    dasharray: "60 240",
    duration: 18,
    width: 1.5,
  },
  {
    // counter-curve cyan, mid-band
    d: "M -50 500 C 350 700, 750 350, 1450 600",
    stroke: "#06b6d4",
    dasharray: "40 200",
    duration: 14,
    width: 1.2,
    reverse: true,
  },
  {
    // indigo arc, bottom band
    d: "M -50 760 C 400 600, 900 900, 1450 720",
    stroke: "#6366f1",
    dasharray: "80 280",
    duration: 22,
    width: 1.8,
  },
  {
    // amber spur near top — shorter, faster — feels like a side road
    d: "M 1450 80 C 1100 180, 900 60, 600 220",
    stroke: "#f59e0b",
    dasharray: "30 160",
    duration: 12,
    width: 1,
    reverse: true,
  },
];

export function TrafficFlowBg(): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const pathRefs = useRef<Array<SVGPathElement | null>>([]);

  useGSAP(
    () => {
      pathRefs.current.forEach((path, i) => {
        if (!path) return;
        const cfg = PATHS[i];
        if (!cfg) return;
        dashFlow(path, {
          duration: cfg.duration,
          reverse: cfg.reverse,
          // Use the dash pattern length so the flow visibly cycles
          dashLength: 300,
        });
      });
    },
    { scope: containerRef }
  );

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 pointer-events-none -z-10 overflow-hidden"
      aria-hidden="true"
    >
      <svg
        className="absolute inset-0 w-full h-full"
        viewBox="0 0 1440 900"
        preserveAspectRatio="xMidYMid slice"
        style={{ opacity: 0.22 }}
      >
        <defs>
          {/* Very subtle ambient radial — fake glow behind the card */}
          <radialGradient id="tflow-ambient" cx="50%" cy="40%" r="60%">
            <stop offset="0%" stopColor="#1e1b4b" stopOpacity="0.6" />
            <stop offset="60%" stopColor="#0a0a0f" stopOpacity="0" />
            <stop offset="100%" stopColor="#0a0a0f" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Ambient background tile */}
        <rect width="1440" height="900" fill="url(#tflow-ambient)" />

        {/* Animated flow paths */}
        {PATHS.map((cfg, i) => (
          <path
            key={i}
            ref={(el) => {
              pathRefs.current[i] = el;
            }}
            d={cfg.d}
            fill="none"
            stroke={cfg.stroke}
            strokeWidth={cfg.width}
            strokeLinecap="round"
            strokeDasharray={cfg.dasharray}
            style={{
              // willChange hint, kept conservative (only on animated elements)
              willChange: "stroke-dashoffset",
            }}
          />
        ))}
      </svg>
    </div>
  );
}

export default TrafficFlowBg;
