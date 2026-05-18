"use client";

/**
 * Small stylised neural-network graph (200×120) with pulsing nodes and 2
 * "data flow" edges. Responsive: scales to container width, max 200px wide.
 *
 * Layout: 3 layers — 2 left, 3 middle, 2 right, plus 1 "input bias" node.
 * Each node pulses opacity 0.6 → 1 → 0.6 over 2s, with 200ms stagger between
 * nodes so they shimmer rather than blink in unison.
 *
 * Two edges (input-1 → mid-2 and mid-2 → out-2) carry an animated dash
 * "packet" effect to suggest data flow.
 *
 * Reduced motion: nodes static at opacity 0.8, no edge flow.
 */

import { useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { pulse, dashFlow } from "@/lib/animations/traffic";

interface Node {
  id: string;
  x: number;
  y: number;
}

const NODES: Node[] = [
  // Input layer (left)
  { id: "in-1", x: 25, y: 35 },
  { id: "in-2", x: 25, y: 85 },
  // Hidden layer (middle)
  { id: "mid-1", x: 100, y: 25 },
  { id: "mid-2", x: 100, y: 60 },
  { id: "mid-3", x: 100, y: 95 },
  // Output layer (right)
  { id: "out-1", x: 175, y: 40 },
  { id: "out-2", x: 175, y: 80 },
];

// Edges: fully-connect input→mid and mid→out (2*3 + 3*2 = 12 edges)
const EDGES: Array<[number, number]> = [];
for (let i = 0; i < 2; i++) {
  for (let j = 2; j < 5; j++) EDGES.push([i, j]);
}
for (let i = 2; i < 5; i++) {
  for (let j = 5; j < 7; j++) EDGES.push([i, j]);
}

// Indices of edges that get the animated "data flow" treatment
const FLOW_EDGE_INDICES: number[] = [3, 9]; // in-2→mid-2 and mid-2→out-2

interface NetworkGraphProps {
  className?: string;
}

export function NetworkGraph({ className }: NetworkGraphProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef<Array<SVGCircleElement | null>>([]);
  const flowEdgeRefs = useRef<Array<SVGLineElement | null>>([]);

  useGSAP(
    () => {
      // Stagger pulse across all nodes — 200ms apart
      const nodes = nodeRefs.current.filter(Boolean) as SVGCircleElement[];
      if (nodes.length) {
        pulse(nodes, {
          duration: 1, // half-cycle (0.6 → 1), full yoyo cycle = 2s
          min: 0.6,
          stagger: { each: 0.2, from: "start" },
        });
      }

      // Animate flow edges (data packet effect via stroke-dashoffset)
      flowEdgeRefs.current.forEach((line, idx) => {
        if (!line) return;
        // SVGLineElement does have getTotalLength()
        const flowPath = line as unknown as SVGPathElement;
        dashFlow(flowPath, {
          duration: 2.5,
          dashLength: 80,
          delay: idx * 0.4,
        });
      });
    },
    { scope: containerRef }
  );

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width: "100%", maxWidth: 200 }}
      aria-hidden="true"
    >
      <svg
        viewBox="0 0 200 120"
        width="100%"
        height="auto"
        style={{ display: "block" }}
      >
        {/* Static edges (low-opacity indigo lattice) */}
        {EDGES.map(([fromIdx, toIdx], i) => {
          const isFlow = FLOW_EDGE_INDICES.includes(i);
          const from = NODES[fromIdx]!;
          const to = NODES[toIdx]!;
          if (isFlow) return null; // rendered separately below
          return (
            <line
              key={`e-${i}`}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke="#6366f1"
              strokeOpacity={0.35}
              strokeWidth={0.6}
            />
          );
        })}

        {/* Flow edges (animated stroke-dashoffset) */}
        {FLOW_EDGE_INDICES.map((edgeIdx, slot) => {
          const [fromIdx, toIdx] = EDGES[edgeIdx]!;
          const from = NODES[fromIdx]!;
          const to = NODES[toIdx]!;
          return (
            <line
              key={`fe-${edgeIdx}`}
              ref={(el) => {
                flowEdgeRefs.current[slot] = el;
              }}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke="#6366f1"
              strokeOpacity={0.9}
              strokeWidth={0.9}
              strokeLinecap="round"
              strokeDasharray="6 74"
              style={{ willChange: "stroke-dashoffset" }}
            />
          );
        })}

        {/* Nodes */}
        {NODES.map((node, i) => (
          <circle
            key={node.id}
            ref={(el) => {
              nodeRefs.current[i] = el;
            }}
            cx={node.x}
            cy={node.y}
            r={4}
            fill="#6366f1"
            opacity={0.8}
            style={{ willChange: "opacity" }}
          />
        ))}
      </svg>
    </div>
  );
}

export default NetworkGraph;
