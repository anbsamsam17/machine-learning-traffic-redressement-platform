"use client";

/**
 * ActiveSidebar — panneau lateral mode actif de /visualisation.
 *
 * Extrait verbatim de app/visualisation/page.tsx pour decharger la page :
 *  - Toggle Mode (TVr / DPL)
 *  - Filtres (min TVr + exclusion FC)
 *  - Couches (segments + capteurs TV/PL)
 *  - Recherche agregId
 *  - Legende editable (paliers de couleur)
 *
 * Le composant est volontairement "dumb" : tout l'etat vit dans la page,
 * passe via props. Aucune mutation d'etat MapLibre ici.
 */

import {
  Search,
  Crosshair,
  Filter as FilterIcon,
  Eye,
  EyeOff,
  Layers as LayersIcon,
} from "lucide-react";

import { TVR_PALETTE_NEON, DPL_PALETTE_NEON, type Stop } from "@/lib/map/palette";
import { cn } from "@/lib/utils";

export type Mode = "TVr" | "DPL";

const NF_FR = new Intl.NumberFormat("fr-FR");
const MONO = `ui-monospace, 'JetBrains Mono', 'SF Mono', Menlo, monospace`;
const FC_OPTIONS = [1, 2, 3, 4, 5] as const;

export interface ActiveSidebarProps {
  mode: Mode;
  onMode: (m: Mode) => void;
  minTvrInput: number;
  onMinTvrInput: (n: number) => void;
  excludedFc: Set<number>;
  onToggleFc: (fc: number) => void;
  showSegments: boolean;
  onShowSegments: () => void;
  showSensorsTv: boolean;
  onShowSensorsTv: () => void;
  showSensorsPl: boolean;
  onShowSensorsPl: () => void;
  hasSensors: boolean;
  searchValue: string;
  onSearchValue: (v: string) => void;
  onSearch: () => void;
  searchHint: string | null;
  tvrStops: Stop[];
  setTvrStops: React.Dispatch<React.SetStateAction<Stop[]>>;
  dplStops: Stop[];
  setDplStops: React.Dispatch<React.SetStateAction<Stop[]>>;
  onResetFilters: () => void;
}

export function ActiveSidebar({
  mode,
  onMode,
  minTvrInput,
  onMinTvrInput,
  excludedFc,
  onToggleFc,
  showSegments,
  onShowSegments,
  showSensorsTv,
  onShowSensorsTv,
  showSensorsPl,
  onShowSensorsPl,
  hasSensors,
  searchValue,
  onSearchValue,
  onSearch,
  searchHint,
  tvrStops,
  setTvrStops,
  dplStops,
  setDplStops,
  onResetFilters,
}: ActiveSidebarProps) {
  const stops = mode === "TVr" ? tvrStops : dplStops;
  const defaults = mode === "TVr" ? TVR_PALETTE_NEON : DPL_PALETTE_NEON;
  const setStops = mode === "TVr" ? setTvrStops : setDplStops;
  const unit = mode === "TVr" ? "v/j" : "PL/j";
  const updateMin = (idx: number, raw: string) => {
    const n = Number(raw);
    if (!isFinite(n) || n < 0) return;
    setStops((prev) => prev.map((s, i) => (i === idx ? { ...s, min: n } : s)));
  };
  const resetStops = () => setStops(defaults);
  const order = stops.map((_, i) => i).reverse();

  return (
    <>
      {/* Mode toggle */}
      <div className="rounded-lg border border-[#1f2740] bg-[rgba(13,17,23,.6)] p-3 space-y-2">
        <div className="flex items-center gap-2">
          <FilterIcon size={12} className="text-[#22d3ee]" />
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-[#e6edf3]">
            Mode
          </h4>
        </div>
        <div className="flex gap-1">
          {(["TVr", "DPL"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => onMode(m)}
              className={cn(
                "flex-1 px-3 py-1.5 rounded text-xs font-semibold transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22d3ee]",
                mode === m
                  ? "bg-[#22d3ee] text-[#0d1117]"
                  : "bg-[rgba(255,255,255,.03)] text-[#a0b0d8] hover:text-[#e6edf3] hover:bg-[rgba(255,255,255,.06)]",
              )}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {/* Filtres */}
      <div className="rounded-lg border border-[#1f2740] bg-[rgba(13,17,23,.6)] p-3 space-y-3">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-[#e6edf3]">
          Filtres
        </h4>
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label htmlFor="min-tvr" className="text-[11px] text-[#a0b0d8]">
              TVr min
            </label>
            <span className="text-[11px] font-mono tabular-nums text-[#22d3ee]">
              {NF_FR.format(minTvrInput)}
            </span>
          </div>
          <input
            id="min-tvr"
            type="range"
            min={0}
            max={20000}
            step={100}
            value={minTvrInput}
            onChange={(e) => onMinTvrInput(Number(e.target.value))}
            className="w-full accent-[#22d3ee] cursor-pointer"
          />
        </div>
        <div>
          <p className="text-[11px] text-[#a0b0d8] mb-1.5">
            Functional Class (decoche pour exclure)
          </p>
          <div className="flex flex-wrap gap-1.5">
            {FC_OPTIONS.map((fc) => {
              const excluded = excludedFc.has(fc);
              return (
                <button
                  key={fc}
                  type="button"
                  onClick={() => onToggleFc(fc)}
                  className={cn(
                    "px-2 py-0.5 rounded text-[11px] font-mono cursor-pointer border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22d3ee]",
                    excluded
                      ? "bg-transparent text-[#7d8aa8] border-[#1f2740] line-through"
                      : "bg-[rgba(34,211,238,.08)] text-[#22d3ee] border-[rgba(34,211,238,.3)]",
                  )}
                  title={excluded ? `Reinclure FC ${fc}` : `Exclure FC ${fc}`}
                >
                  FC {fc}
                </button>
              );
            })}
          </div>
        </div>
        <button
          type="button"
          onClick={onResetFilters}
          className="w-full text-[11px] text-[#a0b0d8] hover:text-[#e6edf3] py-1 cursor-pointer"
        >
          Reinitialiser
        </button>
      </div>

      {/* Couches */}
      <div className="rounded-lg border border-[#1f2740] bg-[rgba(13,17,23,.6)] p-3 space-y-2">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-[#e6edf3]">
          Couches
        </h4>
        {[
          {
            label: "Segments",
            on: showSegments,
            toggle: onShowSegments,
            color: "#22d3ee",
          },
          ...(hasSensors
            ? [
                {
                  label: "Capteurs TV",
                  on: showSensorsTv,
                  toggle: onShowSensorsTv,
                  color: "#22d3ee",
                },
                {
                  label: "Capteurs PL",
                  on: showSensorsPl,
                  toggle: onShowSensorsPl,
                  color: "#FF1744",
                },
              ]
            : []),
        ].map((row) => (
          <button
            key={row.label}
            type="button"
            onClick={row.toggle}
            className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded hover:bg-[rgba(255,255,255,.04)] cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22d3ee]"
          >
            <span className="flex items-center gap-2 min-w-0">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
                style={{ background: row.color }}
                aria-hidden
              />
              <span className="text-[11px] text-[#e6edf3]">{row.label}</span>
            </span>
            {row.on ? (
              <Eye size={13} className="text-[#22d3ee]" />
            ) : (
              <EyeOff size={13} className="text-[#7d8aa8]" />
            )}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="rounded-lg border border-[#1f2740] bg-[rgba(13,17,23,.6)] p-3 space-y-2">
        <div className="flex items-center gap-2">
          <Search size={12} className="text-[#22d3ee]" />
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-[#e6edf3]">
            Recherche agregId
          </h4>
        </div>
        <div className="flex gap-1.5">
          <input
            type="text"
            value={searchValue}
            onChange={(e) => onSearchValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onSearch();
            }}
            placeholder="ID complet ou partiel"
            className="flex-1 h-7 rounded border border-[#1f2740] bg-[rgba(13,17,23,.8)] px-2 text-[11px] text-[#e6edf3] outline-none focus:border-[#22d3ee]"
            aria-label="Identifiant agregId"
          />
          <button
            type="button"
            onClick={onSearch}
            disabled={!searchValue.trim()}
            className="inline-flex items-center justify-center w-7 h-7 rounded bg-[#22d3ee] text-[#0d1117] hover:bg-[#67e8f9] disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22d3ee]"
            aria-label="Lancer la recherche"
          >
            <Crosshair size={12} />
          </button>
        </div>
        {searchHint && (
          <p className="text-[10px] text-[#a0b0d8]">{searchHint}</p>
        )}
      </div>

      {/* Legende editable */}
      <div className="rounded-lg border border-[#1f2740] bg-[rgba(13,17,23,.6)] p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <LayersIcon size={12} className="text-[#22d3ee]" />
            <h4 className="text-[11px] font-semibold uppercase tracking-wide text-[#e6edf3]">
              Legende {mode} ({unit})
            </h4>
          </div>
          <button
            type="button"
            onClick={resetStops}
            className="text-[10px] text-[#a0b0d8] hover:text-[#22d3ee] cursor-pointer transition-colors underline-offset-2 hover:underline"
            title="Restaurer les seuils par defaut"
          >
            reset
          </button>
        </div>
        <p className="text-[10px] text-[#7a8ab0] -mt-1">
          Modifie les seuils (en {unit}) — premier palier fige a 0.
        </p>
        <ul className="space-y-1" role="list">
          {order.map((i) => {
            const stop = stops[i];
            const isFirst = i === 0;
            const isLast = i === stops.length - 1;
            return (
              <li
                key={i}
                className="flex items-center gap-2 text-[11px] text-[#a0b0d8]"
              >
                <span
                  aria-hidden
                  className="inline-block h-2.5 w-6 rounded-sm shrink-0"
                  style={{ background: stop.color }}
                />
                {isLast ? (
                  <span className="font-mono tabular-nums" style={{ fontFamily: MONO }}>
                    {"> "}
                  </span>
                ) : isFirst ? (
                  <span className="font-mono tabular-nums" style={{ fontFamily: MONO }}>
                    {"< "}
                  </span>
                ) : null}
                {isFirst ? (
                  <input
                    type="number"
                    value={stops[1]?.min ?? 0}
                    onChange={(e) => updateMin(1, e.target.value)}
                    min={0}
                    step={50}
                    className="w-20 px-1.5 py-0.5 rounded bg-[#0d1117] border border-[#1f2740] focus:border-[#22d3ee] outline-none text-[11px] font-mono tabular-nums text-[#e6edf3]"
                    style={{ fontFamily: MONO }}
                    aria-label={`Seuil superieur palier 1 (${unit})`}
                  />
                ) : (
                  <input
                    type="number"
                    value={stop.min}
                    onChange={(e) => updateMin(i, e.target.value)}
                    min={0}
                    step={50}
                    className="w-20 px-1.5 py-0.5 rounded bg-[#0d1117] border border-[#1f2740] focus:border-[#22d3ee] outline-none text-[11px] font-mono tabular-nums text-[#e6edf3]"
                    style={{ fontFamily: MONO }}
                    aria-label={`Seuil inferieur palier ${i + 1} (${unit})`}
                  />
                )}
                {!isFirst && !isLast && (
                  <>
                    <span className="text-[#7a8ab0]">–</span>
                    <span
                      className="font-mono tabular-nums text-[#7a8ab0]"
                      style={{ fontFamily: MONO }}
                    >
                      {NF_FR.format(stops[i + 1].min)}
                    </span>
                  </>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}
