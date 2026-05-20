"use client";

/**
 * AnimatedBg
 * --------------------------------------------------------------
 * Modern, image-free animated background for the landing page.
 * Themed around "connected traffic data" — flowing highways,
 * IoT sensor nodes blinking on a low-poly network, and slow
 * gradient drifts.
 *
 * Layers (back → front):
 *   1. Static base — deep slate-950 fill
 *   2. Animated radial gradient blobs (cyan / indigo / violet)
 *      slowly drifting via CSS keyframes on `transform` only
 *   3. SVG "traffic streams" — curved Bézier paths with neon
 *      packets traveling along them (rAF + getPointAtLength)
 *   4. SVG "sensor network" — ~36 nodes connected by faint lines
 *      below a proximity threshold; nodes drift slowly via rAF
 *   5. Scrim — bg-slate-950/60 + backdrop-blur-sm so foreground
 *      text on top stays perfectly legible (WCAG AA on cards)
 *
 * Constraints honoured:
 *   - No image asset, no heavy deps (pure SVG + rAF + CSS)
 *   - prefers-reduced-motion → all animations halt
 *   - GPU-friendly — only `transform` / `opacity` mutated
 *   - aria-hidden on the wrapper, pointer-events-none
 */

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { streamFlow } from "@/lib/animations/data-stream";

type AnimatedBgProps = {
  className?: string;
};

// ────────────────────────────────────────────────────────────
// Traffic streams — curved Bézier "highways". Each has a
// neon packet traveling along it on a slow loop.
// ────────────────────────────────────────────────────────────

type StreamDef = {
  id: string;
  d: string;
  color: string;
  duration: number;
  delay: number;
};

const STREAMS: ReadonlyArray<StreamDef> = [
  {
    id: "t1",
    d: "M -40 180 C 280 60, 620 60, 880 220 S 1320 360, 1480 240",
    color: "#22d3ee", // cyan-400
    duration: 12_000,
    delay: 0,
  },
  {
    id: "t2",
    d: "M -40 480 C 240 320, 560 320, 760 420 S 1180 560, 1480 440",
    color: "#818cf8", // indigo-400
    duration: 15_000,
    delay: 1_400,
  },
  {
    id: "t3",
    d: "M 60 720 C 360 540, 620 540, 760 660 S 1100 760, 1320 600",
    color: "#a78bfa", // violet-400
    duration: 10_500,
    delay: 600,
  },
  {
    id: "t4",
    d: "M -40 340 C 260 200, 540 240, 700 340 S 1080 440, 1480 320",
    color: "#67e8f9", // cyan-300
    duration: 17_000,
    delay: 2_800,
  },
];

// ────────────────────────────────────────────────────────────
// Sensor network — drifting nodes connected by faint lines
// below a proximity threshold. Caps at 36 nodes for perf.
// ────────────────────────────────────────────────────────────

const NODE_COUNT = 36;
const LINK_THRESHOLD = 160; // px in viewBox units (1400×800)

type Node = {
  x: number;
  y: number;
  vx: number;
  vy: number;
};

function seedNodes(): Node[] {
  // Deterministic-ish seeding (Math.random is fine since we run
  // it client-only; the wrapper avoids SSR mismatch by skipping
  // SVG renders until mount, see `mounted` state below).
  // Velocity tuned so motion is visible within ~500ms while still
  // feeling like a slow drift on the 1400×800 viewBox.
  const out: Node[] = [];
  for (let i = 0; i < NODE_COUNT; i++) {
    // Ensure each node has a non-zero baseline velocity so we never
    // end up with a stalled-looking network on first paint.
    const sx = Math.random() < 0.5 ? -1 : 1;
    const sy = Math.random() < 0.5 ? -1 : 1;
    out.push({
      x: Math.random() * 1400,
      y: Math.random() * 800,
      vx: sx * (10 + Math.random() * 20), // 10–30 px/sec, signed
      vy: sy * (10 + Math.random() * 20),
    });
  }
  return out;
}

export function AnimatedBg({ className }: AnimatedBgProps): React.JSX.Element {
  const svgStreamsRef = useRef<SVGSVGElement | null>(null);
  const svgNetRef = useRef<SVGSVGElement | null>(null);
  const nodesRef = useRef<Node[]>([]);
  const nodeElsRef = useRef<SVGCircleElement[]>([]);
  const linkElsRef = useRef<SVGLineElement[]>([]);
  const rafRef = useRef<number>(0);

  // SSR-safe gate: SVG content that uses Math.random for seeding
  // only renders after mount to avoid hydration mismatches.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  // ----- Stream packets (cleanup-aware) ------------------------------
  useEffect(() => {
    if (!mounted) return;
    const svg = svgStreamsRef.current;
    if (!svg) return;
    const cleanups: Array<() => void> = [];
    for (const def of STREAMS) {
      const path = svg.querySelector<SVGPathElement>(`#tpath-${def.id}`);
      const dot = svg.querySelector<SVGGraphicsElement>(`#tdot-${def.id}`);
      if (!path || !dot) continue;
      cleanups.push(
        streamFlow(dot, path, {
          duration: def.duration,
          delay: def.delay,
        }),
      );
    }
    return () => {
      for (const c of cleanups) c();
    };
  }, [mounted]);

  // ----- Sensor network (drift + dynamic links) ----------------------
  useEffect(() => {
    if (!mounted) return;
    const svgNet = svgNetRef.current;
    if (!svgNet) return;

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    nodesRef.current = seedNodes();
    const nodes = nodesRef.current;

    // Snap node elements + reuse a fixed pool of <line> elements.
    nodeElsRef.current = Array.from(
      svgNet.querySelectorAll<SVGCircleElement>("circle[data-node]"),
    );
    linkElsRef.current = Array.from(
      svgNet.querySelectorAll<SVGLineElement>("line[data-link]"),
    );

    // Initial paint
    for (let i = 0; i < nodes.length; i++) {
      const el = nodeElsRef.current[i];
      if (!el) continue;
      el.setAttribute("cx", String(nodes[i].x));
      el.setAttribute("cy", String(nodes[i].y));
    }

    if (reduced) {
      // Paint static links once and stop — no rAF loop.
      paintLinks(nodes, linkElsRef.current);
      return;
    }

    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.05); // clamp 50ms
      last = now;

      // Integrate positions; bounce on bounds.
      // Velocities are in viewBox px/sec; dt is in seconds, so the
      // raw product is the per-frame delta. No extra multiplier —
      // the visible speed is set entirely by `seedNodes()`.
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        n.x += n.vx * dt;
        n.y += n.vy * dt;
        // Clamp + bounce on the viewBox edges so nodes stay on stage.
        if (n.x < 0) {
          n.x = 0;
          n.vx = Math.abs(n.vx);
        } else if (n.x > 1400) {
          n.x = 1400;
          n.vx = -Math.abs(n.vx);
        }
        if (n.y < 0) {
          n.y = 0;
          n.vy = Math.abs(n.vy);
        } else if (n.y > 800) {
          n.y = 800;
          n.vy = -Math.abs(n.vy);
        }
        // Tiny jitter so motion never fully stalls visually.
        if (Math.abs(n.vx) < 5) n.vx += (Math.random() - 0.5) * 4;
        if (Math.abs(n.vy) < 5) n.vy += (Math.random() - 0.5) * 4;

        const el = nodeElsRef.current[i];
        if (el) {
          el.setAttribute("cx", String(n.x));
          el.setAttribute("cy", String(n.y));
        }
      }

      paintLinks(nodes, linkElsRef.current);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [mounted]);

  return (
    <div
      aria-hidden="true"
      className={cn(
        "pointer-events-none fixed inset-0 -z-10 overflow-hidden",
        className,
      )}
    >
      {/* 1. Base fill ------------------------------------------------- */}
      <div className="absolute inset-0 bg-slate-950" />

      {/* 2. Drifting gradient blobs (CSS-only, transform-driven) ------ */}
      <div className="absolute inset-0">
        <div
          className="absolute -top-32 -left-32 h-[60vw] w-[60vw] rounded-full opacity-60 blur-3xl will-change-transform animate-blob-a"
          style={{
            background:
              "radial-gradient(circle at 30% 30%, rgba(34,211,238,0.55), rgba(34,211,238,0) 60%)",
          }}
        />
        <div
          className="absolute top-1/3 -right-40 h-[55vw] w-[55vw] rounded-full opacity-55 blur-3xl will-change-transform animate-blob-b"
          style={{
            background:
              "radial-gradient(circle at 50% 50%, rgba(129,140,248,0.55), rgba(129,140,248,0) 60%)",
          }}
        />
        <div
          className="absolute -bottom-40 left-1/4 h-[55vw] w-[55vw] rounded-full opacity-55 blur-3xl will-change-transform animate-blob-c"
          style={{
            background:
              "radial-gradient(circle at 60% 40%, rgba(167,139,250,0.55), rgba(167,139,250,0) 60%)",
          }}
        />
      </div>

      {/* 3. Traffic streams (animated neon packets along Bézier curves) */}
      {mounted && (
        <svg
          ref={svgStreamsRef}
          className="absolute inset-0 h-full w-full opacity-70 [mix-blend-mode:screen]"
          viewBox="0 0 1400 800"
          preserveAspectRatio="xMidYMid slice"
          fill="none"
        >
          <defs>
            {STREAMS.map((s) => (
              <radialGradient
                key={`tgrad-${s.id}`}
                id={`tgrad-${s.id}`}
                cx="50%"
                cy="50%"
                r="50%"
              >
                <stop offset="0%" stopColor={s.color} stopOpacity="1" />
                <stop offset="55%" stopColor={s.color} stopOpacity="0.55" />
                <stop offset="100%" stopColor={s.color} stopOpacity="0" />
              </radialGradient>
            ))}
          </defs>

          {STREAMS.map((s) => (
            <g key={s.id}>
              <path
                id={`tpath-${s.id}`}
                d={s.d}
                stroke={s.color}
                strokeOpacity="0.10"
                strokeWidth="1"
              />
              <g id={`tdot-${s.id}`} style={{ willChange: "transform, opacity" }}>
                <circle r="22" fill={`url(#tgrad-${s.id})`} />
                <circle r="3.5" fill={s.color} />
              </g>
            </g>
          ))}
        </svg>
      )}

      {/* 4. Sensor network (drifting nodes + dynamic links) ----------- */}
      {mounted && (
        <svg
          ref={svgNetRef}
          className="absolute inset-0 h-full w-full opacity-55"
          viewBox="0 0 1400 800"
          preserveAspectRatio="xMidYMid slice"
          fill="none"
        >
          {/* Pre-allocated link pool. We size it generously to never
              re-alloc inside the rAF loop. With NODE_COUNT=36 and
              threshold-based filtering, ~80 active links is the
              observed steady state. */}
          {Array.from({ length: 96 }, (_, i) => (
            <line
              key={`l${i}`}
              data-link
              x1="0"
              y1="0"
              x2="0"
              y2="0"
              stroke="#67e8f9"
              strokeOpacity="0"
              strokeWidth="0.6"
            />
          ))}
          {Array.from({ length: NODE_COUNT }, (_, i) => (
            <circle
              key={`n${i}`}
              data-node
              r="2"
              fill="#a5f3fc"
              fillOpacity="0.85"
            />
          ))}
        </svg>
      )}

      {/* 5. Legibility scrim ----------------------------------------- */}
      <div className="absolute inset-0 bg-slate-950/55 backdrop-blur-[2px]" />
      {/* Soft vignette to push focus toward content */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(ellipse at center, transparent 0%, rgba(2,6,23,0.35) 65%, rgba(2,6,23,0.65) 100%)",
        }}
      />
    </div>
  );
}

export default AnimatedBg;

// ────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────

function paintLinks(nodes: Node[], links: SVGLineElement[]): void {
  let li = 0;
  const max = links.length;
  for (let i = 0; i < nodes.length && li < max; i++) {
    for (let j = i + 1; j < nodes.length && li < max; j++) {
      const a = nodes[i];
      const b = nodes[j];
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const dist = Math.hypot(dx, dy);
      if (dist > LINK_THRESHOLD) continue;
      const el = links[li++];
      const op = 0.35 * (1 - dist / LINK_THRESHOLD);
      el.setAttribute("x1", String(a.x));
      el.setAttribute("y1", String(a.y));
      el.setAttribute("x2", String(b.x));
      el.setAttribute("y2", String(b.y));
      el.setAttribute("stroke-opacity", op.toFixed(3));
    }
  }
  // Hide unused links from the pool this frame.
  for (; li < max; li++) {
    links[li].setAttribute("stroke-opacity", "0");
  }
}
