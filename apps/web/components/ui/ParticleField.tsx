"use client";

/** Canvas plein ecran de particules connectees (style binaire 01/10). Performance RAF, max 60 noeuds, off si reduced-motion. */
import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

export type ParticleTone = "accent" | "cyan" | "amber" | "violet" | "neutral";

export interface ParticleFieldProps {
  /** Densite cible (auto-cap a `maxParticles`). Defaut 0.00009 noeuds par px2. */
  density?: number;
  maxParticles?: number;
  tone?: ParticleTone;
  /** Distance max pour tracer une liaison (px). Defaut 110. */
  linkDistance?: number;
  /** Affiche les caracteres 0 / 1 sur chaque noeud. Defaut false. */
  showBits?: boolean;
  className?: string;
}

const TONE: Record<ParticleTone, { dot: string; line: string }> = {
  accent: { dot: "99,102,241", line: "99,102,241" },
  cyan: { dot: "6,182,212", line: "6,182,212" },
  amber: { dot: "245,158,11", line: "245,158,11" },
  violet: { dot: "139,92,246", line: "139,92,246" },
  neutral: { dot: "161,161,170", line: "161,161,170" },
};

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  bit: 0 | 1;
  flipAt: number;
}

export function ParticleField({
  density = 0.00009,
  maxParticles = 60,
  tone = "accent",
  linkDistance = 110,
  showBits = false,
  className,
}: ParticleFieldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number | null>(null);
  const nodesRef = useRef<Node[]>([]);
  const sizeRef = useRef<{ w: number; h: number; dpr: number }>({ w: 0, h: 0, dpr: 1 });

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    const palette = TONE[tone];

    const resize = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      const rect = parent.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      sizeRef.current = { w: rect.width, h: rect.height, dpr };
      canvas.width = Math.floor(rect.width * dpr);
      canvas.height = Math.floor(rect.height * dpr);
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const count = Math.min(
        maxParticles,
        Math.max(12, Math.floor(rect.width * rect.height * density))
      );
      const now = performance.now();
      nodesRef.current = Array.from({ length: count }, () => ({
        x: Math.random() * rect.width,
        y: Math.random() * rect.height,
        vx: (Math.random() - 0.5) * 0.25,
        vy: (Math.random() - 0.5) * 0.25,
        bit: (Math.random() < 0.5 ? 0 : 1) as 0 | 1,
        flipAt: now + 800 + Math.random() * 2200,
      }));
    };

    resize();
    const ro = new ResizeObserver(resize);
    if (canvas.parentElement) ro.observe(canvas.parentElement);

    const draw = (t: number) => {
      const { w, h } = sizeRef.current;
      ctx.clearRect(0, 0, w, h);

      const nodes = nodesRef.current;
      // Update
      for (const n of nodes) {
        n.x += n.vx;
        n.y += n.vy;
        if (n.x < 0 || n.x > w) n.vx *= -1;
        if (n.y < 0 || n.y > h) n.vy *= -1;
        if (t > n.flipAt) {
          n.bit = (n.bit ^ 1) as 0 | 1;
          n.flipAt = t + 800 + Math.random() * 2200;
        }
      }

      // Links
      ctx.lineWidth = 1;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d = Math.hypot(dx, dy);
          if (d < linkDistance) {
            const alpha = (1 - d / linkDistance) * 0.18;
            ctx.strokeStyle = `rgba(${palette.line}, ${alpha.toFixed(3)})`;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }

      // Dots + optional bits
      for (const n of nodes) {
        ctx.fillStyle = `rgba(${palette.dot}, 0.85)`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, 1.4, 0, Math.PI * 2);
        ctx.fill();
        if (showBits) {
          ctx.fillStyle = `rgba(${palette.dot}, 0.55)`;
          ctx.font = "10px ui-monospace, monospace";
          ctx.fillText(String(n.bit), n.x + 4, n.y - 4);
        }
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);

    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      ro.disconnect();
    };
  }, [density, maxParticles, tone, linkDistance, showBits]);

  return (
    <div
      aria-hidden
      className={cn("pointer-events-none absolute inset-0 overflow-hidden", className)}
    >
      <canvas ref={canvasRef} className="block h-full w-full" />
    </div>
  );
}
