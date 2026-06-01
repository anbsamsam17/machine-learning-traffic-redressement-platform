"use client";

/**
 * TrafficVideoBg
 * --------------------------------------------------------------
 * Full-bleed animated background combining a looped traffic video
 * with an SVG "smart infrastructure" overlay (nodes, packets,
 * transmissions). Faithful React + GSAP port of the validated
 * prototype `prototypes/landing-traffic-video-bg.html` (v2).
 *
 * Layers (back -> front, all `pointer-events-none`):
 *   1. <video> — /video/traffic-bg.mp4 looped, muted, object-cover
 *   2. <div .bg-darken>  — linear gradient that darkens the bottom
 *      so foreground text stays legible.
 *   3. <div .bg-tint>    — radial indigo/cyan tint, mix-blend screen.
 *   4. <svg .overlay>    — viewBox 1920x1080, two nodes + 12 packets
 *      + 12 transmissions pool, all driven by GSAP.
 *   5. <div .vignette>   — radial vignette to focus the center.
 *
 * SSR-safe : the SVG markup is rendered server-side but all DOM
 * mutations (packet pool creation, tweens) happen inside useGSAP
 * which only runs on the client. We never touch window/document
 * at module top-level.
 *
 * Reduced motion : a `gsap.matchMedia` query disables packet
 * emission + halo respiration ; the video remains visible but
 * static is acceptable since `<video>` itself loops at the
 * browser level and we don't control its playback rate.
 */

import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import { useRef } from "react";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// Scene constants — vehicle spots + smart nodes (viewBox 1920x1080)
// Coordinates inspected on the source video frames at t=4s / t=12s.
// ─────────────────────────────────────────────────────────────────────────────

type Spot = { id: string; x: number; y: number; kind: "car" | "truck" };
type Node = { id: string; x: number; y: number };

const SPOTS: ReadonlyArray<Spot> = [
  // Top-left diagonal highway (SW->NE) — upper west exit
  { id: "S1", x: 220, y: 170, kind: "car" },
  { id: "S2", x: 440, y: 230, kind: "truck" }, // long-haul on outer ring
  // Mid-band east-west viaduct (left of node-01)
  { id: "S3", x: 660, y: 280, kind: "car" },
  { id: "S4", x: 1060, y: 230, kind: "car" },
  // Right diagonal highway going N->S (south-east branch)
  { id: "S5", x: 1430, y: 460, kind: "car" },
  { id: "S6", x: 1670, y: 560, kind: "truck" }, // large vehicle on outer ring
  // Bottom horizontal highway
  { id: "S7", x: 1200, y: 980, kind: "car" },
  { id: "S8", x: 1620, y: 880, kind: "car" },
];

const NODES: ReadonlyArray<Node> = [
  { id: "N1", x: 900, y: 480 },
  { id: "N2", x: 540, y: 760 },
];

const SVG_NS = "http://www.w3.org/2000/svg";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const rand = (a: number, b: number) => a + Math.random() * (b - a);
const choice = <T,>(arr: ReadonlyArray<T>): T =>
  arr[Math.floor(Math.random() * arr.length)];

type Pt = { x: number; y: number };

function bezierPoint(t: number, p0: Pt, ctrl: Pt, p1: Pt): Pt {
  const u = 1 - t;
  return {
    x: u * u * p0.x + 2 * u * t * ctrl.x + t * t * p1.x,
    y: u * u * p0.y + 2 * u * t * ctrl.y + t * t * p1.y,
  };
}
function bezierPath(p0: Pt, ctrl: Pt, p1: Pt): string {
  return `M ${p0.x.toFixed(2)} ${p0.y.toFixed(2)} Q ${ctrl.x.toFixed(2)} ${ctrl.y.toFixed(2)} ${p1.x.toFixed(2)} ${p1.y.toFixed(2)}`;
}
function dist(a: Pt, b: Pt): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

// ─────────────────────────────────────────────────────────────────────────────
// Pool types
// ─────────────────────────────────────────────────────────────────────────────

type Packet = {
  g: SVGGElement;
  kind: "cyan" | "indigo";
  active: boolean;
  tween: gsap.core.Tween | null;
};
type Transmission = {
  path: SVGPathElement;
  active: boolean;
};
type SpotPulse = {
  c: SVGCircleElement;
  active: boolean;
};

interface TrafficVideoBgProps {
  /** Override classes on the root wrapper (optional). */
  className?: string;
}

export function TrafficVideoBg({ className }: TrafficVideoBgProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const layerPacketsRef = useRef<SVGGElement>(null);
  const layerTransmissionsRef = useRef<SVGGElement>(null);

  useGSAP(
    () => {
      const layerPackets = layerPacketsRef.current;
      const layerTransmissions = layerTransmissionsRef.current;
      const root = rootRef.current;
      if (!layerPackets || !layerTransmissions || !root) return;

      // ----------------------------------------------------------------------
      // POOL ALLOCATION — once, recycled for the lifetime of the component.
      // 12 packets (8 cyan + 4 indigo), 12 transmissions, 24 spot pulses.
      // ----------------------------------------------------------------------
      const PACKETS: Packet[] = [];
      const TRANSMISSIONS: Transmission[] = [];
      const SPOT_PULSES: SpotPulse[] = [];

      function createPacket(kind: "cyan" | "indigo"): Packet {
        const g = document.createElementNS(SVG_NS, "g") as SVGGElement;
        g.setAttribute("class", `packet packet-${kind}`);
        g.setAttribute("opacity", "0");

        const halo = document.createElementNS(SVG_NS, "circle");
        halo.setAttribute("r", "6");
        halo.setAttribute(
          "fill",
          kind === "cyan" ? "url(#tvb-packet-cyan)" : "url(#tvb-packet-indigo)",
        );
        g.appendChild(halo);

        const core = document.createElementNS(SVG_NS, "circle");
        core.setAttribute("r", "1.5");
        core.setAttribute("fill", kind === "cyan" ? "#22d3ee" : "#6366f1");
        g.appendChild(core);

        layerPackets!.appendChild(g);
        return { g, kind, active: false, tween: null };
      }
      function createTransmission(): Transmission {
        const path = document.createElementNS(SVG_NS, "path");
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", "#22d3ee");
        path.setAttribute("stroke-width", "0.6");
        path.setAttribute("stroke-dasharray", "2,4");
        path.setAttribute("opacity", "0");
        layerTransmissions!.appendChild(path);
        return { path, active: false };
      }
      function createSpotPulse(): SpotPulse {
        const c = document.createElementNS(SVG_NS, "circle");
        c.setAttribute("r", "0");
        c.setAttribute("cx", "0");
        c.setAttribute("cy", "0");
        c.setAttribute("fill", "url(#tvb-pulse-white)");
        c.setAttribute("opacity", "0");
        layerPackets!.appendChild(c);
        return { c, active: false };
      }

      for (let i = 0; i < 8; i++) PACKETS.push(createPacket("cyan"));
      for (let i = 0; i < 4; i++) PACKETS.push(createPacket("indigo"));
      for (let i = 0; i < 12; i++) TRANSMISSIONS.push(createTransmission());
      for (let i = 0; i < 24; i++) SPOT_PULSES.push(createSpotPulse());

      function getFreePacket(kind: "cyan" | "indigo"): Packet | null {
        for (const p of PACKETS) if (!p.active && p.kind === kind) return p;
        for (const p of PACKETS) if (!p.active) return p;
        return null;
      }
      function getFreeTransmission(): Transmission | null {
        for (const t of TRANSMISSIONS) if (!t.active) return t;
        return null;
      }
      function getFreePulse(): SpotPulse | null {
        for (const p of SPOT_PULSES) if (!p.active) return p;
        return null;
      }

      function closestNode(origin: Pt): Node {
        let best = NODES[0];
        let bestD = Infinity;
        for (const n of NODES) {
          const d = dist(origin, n);
          if (d < bestD) {
            bestD = d;
            best = n;
          }
        }
        return best;
      }

      function flashPulse(pos: Pt, color: string) {
        const p = getFreePulse();
        if (!p) return;
        p.active = true;
        p.c.setAttribute("cx", String(pos.x));
        p.c.setAttribute("cy", String(pos.y));
        p.c.setAttribute("r", "0");
        p.c.setAttribute("opacity", "0.9");
        if (color === "#ffffff") {
          p.c.setAttribute("fill", "url(#tvb-pulse-white)");
        } else {
          p.c.setAttribute("fill", color);
        }
        gsap.fromTo(
          p.c,
          { attr: { r: 0 }, opacity: 0.9 },
          {
            attr: { r: 4 },
            opacity: 0,
            duration: 0.2,
            ease: "expo.out",
            onComplete: () => {
              p.active = false;
            },
          },
        );
      }

      // --------------------------------------------------------------------
      // Packet emission between two targets
      // --------------------------------------------------------------------
      function spawnFlow() {
        // 70% cyan, 30% indigo
        const kind: "cyan" | "indigo" =
          Math.random() < 0.7 ? "cyan" : "indigo";
        const packet = getFreePacket(kind);
        if (!packet) return;

        const origin = choice(SPOTS);

        // 35% chance the destination is a node (V2I), 65% another spot (V2V)
        let target: Pt;
        if (Math.random() < 0.35) {
          target =
            Math.random() < 0.6
              ? (closestNode(origin) as Pt)
              : (choice(NODES) as Pt);
        } else {
          let attempts = 0;
          let candidate: Spot;
          do {
            candidate = choice(SPOTS);
            attempts++;
          } while (
            (candidate.id === origin.id || dist(origin, candidate) < 250) &&
            attempts < 6
          );
          target = candidate;
        }

        const p0: Pt = { x: origin.x, y: origin.y };
        const p1: Pt = { x: target.x, y: target.y };
        const d = dist(p0, p1);

        // perpendicular control point
        const mid: Pt = { x: (p0.x + p1.x) / 2, y: (p0.y + p1.y) / 2 };
        const dx = p1.x - p0.x;
        const dy = p1.y - p0.y;
        const len = Math.sqrt(dx * dx + dy * dy) || 1;
        const offset = Math.max(30, Math.min(50, d * 0.1));
        const sign = Math.random() < 0.5 ? 1 : -1;
        const ctrl: Pt = {
          x: mid.x + (-dy / len) * offset * sign,
          y: mid.y + (dx / len) * offset * sign,
        };

        // Transmission line — short-lived dashed bezier
        const tx = getFreeTransmission();
        if (tx) {
          tx.active = true;
          tx.path.setAttribute("d", bezierPath(p0, ctrl, p1));
          tx.path.setAttribute("opacity", "0");
          gsap
            .timeline()
            .to(tx.path, { opacity: 0.55, duration: 0.1, ease: "power1.out" })
            .to(tx.path, { opacity: 0.55, duration: 0.4 })
            .to(tx.path, {
              opacity: 0,
              duration: 0.2,
              ease: "power1.in",
              onComplete: () => {
                tx.active = false;
              },
            });
        }

        // Departure pulse at origin
        flashPulse(p0, "#ffffff");

        // Packet flight
        packet.active = true;
        gsap.set(packet.g, {
          opacity: 0,
          attr: { transform: `translate(${p0.x} ${p0.y})` },
        });
        gsap.to(packet.g, { opacity: 1, duration: 0.1, ease: "power1.out" });

        const tObj = { v: 0 };
        packet.tween = gsap.to(tObj, {
          v: 1,
          duration: 0.6,
          ease: "power2.inOut",
          onUpdate: () => {
            const p = bezierPoint(tObj.v, p0, ctrl, p1);
            packet.g.setAttribute(
              "transform",
              `translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`,
            );
          },
          onComplete: () => {
            flashPulse(p1, kind === "cyan" ? "#22d3ee" : "#6366f1");
            gsap.to(packet.g, {
              opacity: 0,
              duration: 0.15,
              ease: "power1.in",
              onComplete: () => {
                packet.active = false;
              },
            });
          },
        });
      }

      // --------------------------------------------------------------------
      // Scheduler — keep <=7 active packets, irregular interval feel
      // --------------------------------------------------------------------
      let emitTimer: ReturnType<typeof setTimeout> | null = null;
      let stopped = false;

      function startEmission() {
        stopEmission();
        const schedule = () => {
          if (stopped) return;
          const activeCount = PACKETS.reduce(
            (s, p) => s + (p.active ? 1 : 0),
            0,
          );
          if (activeCount < 7) spawnFlow();
          emitTimer = setTimeout(schedule, rand(130, 320));
        };
        schedule();
      }
      function stopEmission() {
        if (emitTimer) {
          clearTimeout(emitTimer);
          emitTimer = null;
        }
      }

      // --------------------------------------------------------------------
      // Ambient — node halo + ring respiration
      // --------------------------------------------------------------------
      function setupAmbient() {
        const nodes = root!.querySelectorAll<SVGGElement>(".tvb-node");
        nodes.forEach((node, i) => {
          const halo = node.querySelector<SVGCircleElement>(".tvb-node-halo");
          const ring = node.querySelector<SVGCircleElement>(".tvb-node-ring");
          const label = node.querySelector<SVGTextElement>(".tvb-node-label");

          if (halo) {
            gsap.fromTo(
              halo,
              { opacity: 0.4, attr: { r: 60 } },
              {
                opacity: 0.8,
                attr: { r: 70 },
                duration: 3.8,
                ease: "sine.inOut",
                repeat: -1,
                yoyo: true,
                delay: i * 1.2,
              },
            );
          }
          if (ring) {
            gsap.fromTo(
              ring,
              { opacity: 0.35 },
              {
                opacity: 0.75,
                duration: 3.8,
                ease: "sine.inOut",
                repeat: -1,
                yoyo: true,
                delay: i * 1.2,
              },
            );
          }
          if (label) gsap.set(label, { opacity: 0.5 });
        });
      }

      // --------------------------------------------------------------------
      // matchMedia : disable emission + ambient under prefers-reduced-motion
      // --------------------------------------------------------------------
      const mm = gsap.matchMedia();

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        setupAmbient();
        startEmission();
        return () => {
          stopped = true;
          stopEmission();
        };
      });

      mm.add("(prefers-reduced-motion: reduce)", () => {
        // Static snapshot : show halos dimmed, no packet flow.
        const halos = root!.querySelectorAll<SVGCircleElement>(
          ".tvb-node-halo",
        );
        halos.forEach((h) => {
          h.setAttribute("opacity", "0.4");
          h.setAttribute("r", "60");
        });
        const rings = root!.querySelectorAll<SVGCircleElement>(
          ".tvb-node-ring",
        );
        rings.forEach((r) => r.setAttribute("opacity", "0.55"));
        return () => {
          // nothing scheduled, nothing to revert
        };
      });

      // useGSAP cleanup handles all child tweens via scope.
      // We additionally clear the emission timer in matchMedia revert above.
    },
    { scope: rootRef },
  );

  return (
    <div
      ref={rootRef}
      aria-hidden
      className={cn(
        // z-0 (et NON -z-10) : le body de l'app a un fond opaque bg-bg
        // (#09090b) qui couvrirait toute couche en z-index negatif. On
        // reste en z=0 pour rester DERRIERE le contenu (qui est en z-10)
        // tout en passant DEVANT le fond du body. pointer-events-none
        // garantit qu'aucun clic n'est intercepte.
        "pointer-events-none fixed inset-0 z-0 overflow-hidden",
        className,
      )}
    >
      {/* 1. Background video.
          Pour la production : transcoder traffic-bg.mp4 (~20 MB) en H.264
          CRF 28 (~3-5 MB) et generer une variante WebM VP9 (~2-3 MB) +
          un poster JPG (premier frame), puis re-activer les <source> WebM
          + poster ci-dessous. La MP4 reste fallback universel.
          Note : on n'inclut PAS le <source> WebM ni le `poster` tant que les
          fichiers ne sont pas crees, sinon le browser logue des 404 inutiles. */}
      <video
        className="absolute inset-0 h-full w-full object-cover [will-change:transform]"
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
        src="/video/traffic-bg.mp4"
      />
      {/* Future production sources (decommentez quand WebM + poster genere) :
          <video poster="/video/traffic-bg-poster.jpg" ...>
            <source src="/video/traffic-bg.webm" type="video/webm" />
            <source src="/video/traffic-bg.mp4" type="video/mp4" />
          </video> */}

      {/* 2. Bottom darken — keeps cards legible above the video */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(180deg, rgba(9,9,11,0.10) 0%, rgba(9,9,11,0.20) 35%, rgba(9,9,11,0.35) 75%, rgba(9,9,11,0.50) 100%)",
        }}
      />

      {/* 3. Cyan/indigo tint, mix-blend-screen */}
      <div
        className="absolute inset-0 mix-blend-screen"
        style={{
          background:
            "radial-gradient(ellipse at 50% 45%, rgba(99,102,241,0.05) 0%, rgba(34,211,238,0.03) 40%, rgba(9,9,11,0.30) 100%)",
        }}
      />

      {/* 4. SVG overlay — nodes + dynamic packets/transmissions */}
      <svg
        className="absolute inset-0 h-full w-full"
        viewBox="0 0 1920 1080"
        preserveAspectRatio="xMidYMid slice"
        aria-hidden
      >
        <defs>
          <radialGradient id="tvb-halo-cyan" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.45" />
            <stop offset="55%" stopColor="#22d3ee" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="tvb-packet-cyan" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="1" />
            <stop offset="35%" stopColor="#22d3ee" stopOpacity="0.50" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="tvb-packet-indigo" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#a5b4fc" stopOpacity="1" />
            <stop offset="35%" stopColor="#6366f1" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#6366f1" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="tvb-pulse-white" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.95" />
            <stop offset="60%" stopColor="#ffffff" stopOpacity="0.30" />
            <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Smart infrastructure nodes — static markup, GSAP only tweens attributes */}
        <g className="tvb-layer-nodes">
          {NODES.map((n, i) => (
            <g
              key={n.id}
              className="tvb-node"
              transform={`translate(${n.x} ${n.y})`}
            >
              <circle
                className="tvb-node-halo"
                r={60}
                fill="url(#tvb-halo-cyan)"
                opacity={0.6}
              />
              <circle
                className="tvb-node-ring"
                r={18}
                fill="none"
                stroke="#22d3ee"
                strokeWidth={1}
                opacity={0.55}
              />
              <circle className="tvb-node-core" r={2} fill="#22d3ee" />
              <text
                className="tvb-node-label"
                x={24}
                y={-14}
                style={{
                  fontFamily:
                    'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
                  fontSize: 9,
                  fill: "#22d3ee",
                  letterSpacing: "0.05em",
                }}
              >
                NODE-{String(i + 1).padStart(2, "0")}
              </text>
            </g>
          ))}
        </g>

        {/* Pool layers — populated dynamically by useGSAP. */}
        <g ref={layerTransmissionsRef} className="tvb-layer-transmissions" />
        <g ref={layerPacketsRef} className="tvb-layer-packets" />
      </svg>

      {/* 5. Radial vignette — focus center */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at center, rgba(9,9,11,0) 30%, rgba(9,9,11,0.25) 70%, rgba(9,9,11,0.55) 100%)",
        }}
      />
    </div>
  );
}

export default TrafficVideoBg;
