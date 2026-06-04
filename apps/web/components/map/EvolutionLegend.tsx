"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Eye, EyeOff } from "lucide-react";
import {
  buildBuckets,
  EVOLUTION_NEUTRAL_COLOR,
  SIG_OPACITY,
  N_THRESHOLDS,
} from "@/lib/evolution-palette";

/**
 * EvolutionLegend — overlay bottom-right de la carte d'evolution (reference
 * COMPASS). Affiche la rampe divergente bleu<->orange centree sur 0 keyee sur
 * `dJOr` (veh/j), avec :
 *   - seuils EDITABLES (3 inputs numeriques) qui recolorent la carte,
 *   - categories CLIQUABLES (afficher/masquer la tranche),
 *   - icone OEIL : toggle de toute la couche,
 *   - convention d'attenuation des troncons non significatifs (sig=0).
 *
 * Composant CONTROLE : l'etat (seuils, visibilite, couche) est detenu par le
 * viewer, qui derive les expressions MapLibre (couleur/filtre/visibilite).
 */

export interface EvolutionLegendProps {
  /** Seuils courants [t0, t1, t2] (veh/j). */
  thresholds: number[];
  /** Maj des seuils (le viewer recolore la carte). */
  onThresholdsChange: (next: number[]) => void;
  /** Index des categories visibles (0..3). */
  visibleBuckets: ReadonlySet<number>;
  /** Toggle d'une categorie. */
  onToggleBucket: (index: number) => void;
  /** Affichage de la categorie neutre (dJOr absent). */
  showNeutral: boolean;
  onToggleNeutral: () => void;
  /** Couche globalement visible (oeil). */
  layerVisible: boolean;
  onToggleLayer: () => void;
  /** Compte par categorie (0..3) + neutre, pour afficher la valeur. */
  counts?: { buckets: number[]; neutral: number };
}

const NF = new Intl.NumberFormat("fr-FR");

export function EvolutionLegend({
  thresholds,
  onThresholdsChange,
  visibleBuckets,
  onToggleBucket,
  showNeutral,
  onToggleNeutral,
  layerVisible,
  onToggleLayer,
  counts,
}: EvolutionLegendProps) {
  const [collapsed, setCollapsed] = useState(false);

  const buckets = buildBuckets(thresholds);

  const setThreshold = (i: number, raw: string) => {
    const v = Number(raw);
    const next = thresholds.slice();
    next[i] = Number.isFinite(v) ? v : next[i];
    onThresholdsChange(next);
  };

  return (
    <div className="absolute bottom-4 right-4 z-10 w-72 rounded-xl border border-white/10 bg-[rgba(15,20,40,0.92)] backdrop-blur shadow-lg overflow-hidden">
      {/* Header : titre + sous-titre + oeil + collapse */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/5">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold text-slate-100 truncate">
            Évolution du TMJO en véh/j
          </p>
          <p className="text-[9px] text-slate-400">par sens</p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={onToggleLayer}
            className="p-1 rounded text-slate-300 hover:bg-white/10 cursor-pointer"
            aria-label={
              layerVisible ? "Masquer la couche" : "Afficher la couche"
            }
            aria-pressed={layerVisible}
            title="Afficher / masquer toute la couche"
          >
            {layerVisible ? <Eye size={14} /> : <EyeOff size={14} />}
          </button>
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            className="p-1 rounded text-slate-300 hover:bg-white/10 cursor-pointer"
            aria-expanded={!collapsed}
            aria-label={collapsed ? "Déplier la légende" : "Replier la légende"}
          >
            {collapsed ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="px-3 pb-3 pt-2 space-y-3">
          <p className="text-[9px] text-slate-400 leading-relaxed">
            Cliquez sur les catégories pour afficher/masquer
          </p>

          {/* Categories cliquables (du haut = hausse vers le bas = baisse) */}
          <ul className="space-y-1" role="list">
            {buckets
              .slice()
              .reverse()
              .map((b) => {
                const active = visibleBuckets.has(b.index);
                const count = counts?.buckets[b.index];
                return (
                  <li key={b.index}>
                    <button
                      type="button"
                      onClick={() => onToggleBucket(b.index)}
                      aria-pressed={active}
                      className={`w-full flex items-center gap-2 rounded px-1.5 py-1 text-left transition-colors hover:bg-white/5 cursor-pointer ${
                        active ? "opacity-100" : "opacity-40"
                      }`}
                    >
                      <span
                        aria-hidden
                        className="inline-block h-3 w-5 rounded-sm shrink-0 border border-white/20"
                        style={{ background: b.color }}
                      />
                      <span
                        className="flex-1 text-[11px] text-slate-200 font-mono tabular-nums truncate"
                        style={{
                          fontFamily:
                            'ui-monospace, "JetBrains Mono", "SF Mono", Menlo, monospace',
                        }}
                      >
                        {b.label}
                      </span>
                      {count != null && (
                        <span className="text-[10px] text-slate-400 tabular-nums shrink-0">
                          {NF.format(count)}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
          </ul>

          {/* Seuils editables */}
          <div className="pt-2 border-t border-white/5 space-y-1.5">
            <p className="text-[9px] uppercase tracking-wide text-slate-500">
              Seuils (véh/j)
            </p>
            <div className="grid grid-cols-3 gap-1.5">
              {Array.from({ length: N_THRESHOLDS }).map((_, i) => (
                <input
                  key={i}
                  type="number"
                  value={thresholds[i] ?? ""}
                  onChange={(e) => setThreshold(i, e.target.value)}
                  step={100}
                  className="h-7 w-full rounded border border-white/10 bg-[rgba(15,20,40,0.6)] px-1.5 text-[11px] text-slate-100 outline-none focus:border-accent tabular-nums"
                  aria-label={`Seuil ${i + 1} en véhicules par jour`}
                />
              ))}
            </div>
          </div>

          {/* Categorie neutre (dJOr absent) */}
          <div className="pt-2 border-t border-white/5">
            <button
              type="button"
              onClick={onToggleNeutral}
              aria-pressed={showNeutral}
              className={`w-full flex items-center gap-2 rounded px-1.5 py-1 text-left transition-colors hover:bg-white/5 cursor-pointer ${
                showNeutral ? "opacity-100" : "opacity-40"
              }`}
            >
              <span
                aria-hidden
                className="inline-block h-3 w-5 rounded-sm shrink-0 border border-white/20"
                style={{ background: EVOLUTION_NEUTRAL_COLOR }}
              />
              <span className="flex-1 text-[10px] text-slate-300">
                Non calculable (dJOr absent)
              </span>
              {counts?.neutral != null && (
                <span className="text-[10px] text-slate-400 tabular-nums shrink-0">
                  {NF.format(counts.neutral)}
                </span>
              )}
            </button>
          </div>

          {/* Attenuation sig */}
          <div className="pt-2 border-t border-white/5 space-y-1">
            <p className="text-[9px] uppercase tracking-wide text-slate-500">
              Significativité
            </p>
            <div className="flex items-center gap-2 text-[10px] text-slate-300">
              <span
                aria-hidden
                className="inline-block h-2.5 w-6 rounded-sm shrink-0 bg-orange-400"
                style={{ opacity: SIG_OPACITY.significant }}
              />
              <span>sig = 1 (IC disjoints, évolution réelle)</span>
            </div>
            <div className="flex items-center gap-2 text-[10px] text-slate-400">
              <span
                aria-hidden
                className="inline-block h-2.5 w-6 rounded-sm shrink-0 bg-orange-400"
                style={{ opacity: SIG_OPACITY.attenuated }}
              />
              <span>sig = 0 (dans la marge d&apos;erreur — atténué)</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
