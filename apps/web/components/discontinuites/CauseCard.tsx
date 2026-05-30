"use client";

/**
 * CauseCard / TopologyCard — boutons de filtrage pour les panneaux Causes
 * et Topologie de /discontinuites.
 *
 * Extrait du JSX inline de ReadySidebar pour DRY : chaque ligne (cause ou
 * topologie) etait dupliquee dans deux .map() identiques. Encapsuler la
 * presentation ici reduit ReadySidebar et facilite les ajustements futurs
 * (badge, tooltip, etc.).
 *
 * Le composant est volontairement minimal : pas d'etat interne, tout vient
 * des props. Differencie cause/topo via le style du pictogramme (rond plein
 * pour la cause, cercle au contour epais pour la topologie).
 */

import { cn } from "@/lib/utils";

const NF_FR = new Intl.NumberFormat("fr-FR");

export interface CauseCardProps {
  label: string;
  count: number;
  pct: string;
  color: string;
  active: boolean;
  onToggle: () => void;
  /**
   * "fill" (cause) : pastille pleine de la couleur.
   * "outline" (topologie) : anneau border de la couleur, fond transparent.
   */
  variant?: "fill" | "outline";
}

export function CauseCard({
  label,
  count,
  pct,
  color,
  active,
  onToggle,
  variant = "fill",
}: CauseCardProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        "w-full flex items-center gap-2 px-1.5 py-1 rounded text-[11.5px] transition-all text-left cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FFB000]",
        "hover:bg-[rgba(255,255,255,.04)]",
        !active && "opacity-40",
      )}
      aria-pressed={active}
    >
      <span
        className="w-3 h-3 rounded-full shrink-0"
        style={
          variant === "outline"
            ? {
                background: "transparent",
                border: `3px solid ${color}`,
              }
            : {
                background: color,
                border: "1px solid rgba(255,255,255,0.15)",
              }
        }
      />
      <span className="flex-1 text-[#e6edf3] truncate">{label}</span>
      <span className="text-[10px] text-[#7d8aa8] font-mono tabular-nums">
        {NF_FR.format(count)} ({pct}%)
      </span>
    </button>
  );
}
