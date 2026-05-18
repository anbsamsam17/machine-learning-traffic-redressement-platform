"use client";

import {
  Filter,
  SlidersHorizontal,
  Eye,
  EyeOff,
} from "lucide-react";

export interface MapControlsState {
  /** Local map-only filter: minimum TVr to display */
  minTvrFilter: number;
  /** Local map-only filter: hide motorways (FC=1) */
  excludeFc1: boolean;
}

export interface ControlPanelProps {
  state: MapControlsState;
  onChange: (next: MapControlsState) => void;
  /** Whether a carte has been generated (controls disabled if not) */
  hasData: boolean;
  /** Number of features currently loaded — purely informational */
  featureCount?: number | null;
  /** Optional summary stats line */
  meanTvr?: number | null;
  meanDpl?: number | null;
}

/**
 * ControlPanel — sidebar panel for map-local viewer controls.
 *
 * NOTE: The heavy controls (model uploads, FCD upload, column mapping,
 * generation, server-side filters) live in `page.tsx`. This panel only
 * surfaces *map viewer* concerns: visual filters that re-paint the layer
 * without re-running the API call.
 */
export function ControlPanel({
  state,
  onChange,
  hasData,
  featureCount,
  meanTvr,
  meanDpl,
}: ControlPanelProps) {
  const set = <K extends keyof MapControlsState>(k: K, v: MapControlsState[K]) =>
    onChange({ ...state, [k]: v });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <SlidersHorizontal size={14} className="text-violet-400" />
        <h4 className="text-xs font-semibold text-slate-100 uppercase tracking-wide">
          Affichage carte
        </h4>
      </div>

      {/* Stats block */}
      {hasData && (
        <div className="rounded-lg border border-white/10 bg-[rgba(15,20,40,0.6)] px-3 py-2.5 space-y-1.5">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-slate-400">Tronçons affichés</span>
            <span
              className="text-slate-100 font-semibold tabular-nums"
              style={{ fontFamily: 'ui-monospace, "JetBrains Mono", monospace' }}
            >
              {featureCount?.toLocaleString("fr-FR") ?? "—"}
            </span>
          </div>
          {meanTvr != null && (
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-slate-400">TVr moyen</span>
              <span
                className="text-slate-100 font-semibold tabular-nums"
                style={{ fontFamily: 'ui-monospace, "JetBrains Mono", monospace' }}
              >
                {Math.round(meanTvr).toLocaleString("fr-FR")} veh/j
              </span>
            </div>
          )}
          {meanDpl != null && (
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-slate-400">DPL moyen</span>
              <span
                className="text-slate-100 font-semibold tabular-nums"
                style={{ fontFamily: 'ui-monospace, "JetBrains Mono", monospace' }}
              >
                {Math.round(meanDpl).toLocaleString("fr-FR")} PL/j
              </span>
            </div>
          )}
        </div>
      )}

      {/* Min TVr filter */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label
            htmlFor="map-min-tvr"
            className="text-[11px] text-slate-200 flex items-center gap-1.5"
          >
            <Filter size={12} className="text-violet-400" />
            Seuil TVr minimum
          </label>
          <span
            className="text-[11px] text-indigo-300 font-semibold tabular-nums"
            style={{ fontFamily: 'ui-monospace, "JetBrains Mono", monospace' }}
          >
            {state.minTvrFilter.toLocaleString("fr-FR")} veh/j
          </span>
        </div>
        <input
          id="map-min-tvr"
          type="range"
          min={0}
          max={20000}
          step={100}
          value={state.minTvrFilter}
          onChange={(e) => set("minTvrFilter", Number(e.target.value))}
          disabled={!hasData}
          className="w-full h-1.5 rounded-full appearance-none bg-[rgba(255,255,255,0.08)] cursor-pointer accent-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-indigo-500"
          aria-label="Seuil TVr minimum"
        />
        <p className="text-[10px] text-slate-500">
          Masque les tronçons dont le débit TVr est inférieur au seuil.
        </p>
      </div>

      {/* Exclude FC=1 toggle */}
      <label className="flex items-start gap-2.5 cursor-pointer group">
        <input
          type="checkbox"
          checked={state.excludeFc1}
          onChange={(e) => set("excludeFc1", e.target.checked)}
          disabled={!hasData}
          className="mt-0.5 w-3.5 h-3.5 rounded border-white/20 bg-[rgba(15,20,40,0.6)] accent-indigo-500 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        />
        <div className="flex-1">
          <span className="text-[11px] font-medium text-slate-200 group-hover:text-indigo-300 transition-colors flex items-center gap-1.5">
            {state.excludeFc1 ? (
              <EyeOff size={12} className="text-violet-400" />
            ) : (
              <Eye size={12} className="text-slate-400" />
            )}
            Masquer les autoroutes (FC = 1)
          </span>
          <p className="text-[10px] text-slate-500 mt-0.5">
            Cache les tronçons de classe 1 (autoroutes principales).
          </p>
        </div>
      </label>
    </div>
  );
}
