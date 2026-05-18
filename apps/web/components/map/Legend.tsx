"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { TVR_STOPS } from "@/lib/map-palette";

/**
 * Legend — interactive overlay shown bottom-right of the map.
 * Currently displays the TVr palette scale; foldable to free up real estate.
 */
export function Legend({
  visible = true,
  onToggleVisible,
}: {
  visible?: boolean;
  onToggleVisible?: (next: boolean) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);

  if (!visible) {
    return (
      <div className="absolute bottom-4 right-4 z-10">
        <button
          type="button"
          onClick={() => onToggleVisible?.(true)}
          className="rounded-lg border border-white/10 bg-[rgba(15,20,40,0.85)] backdrop-blur px-3 py-1.5 text-[11px] text-slate-200 hover:bg-[rgba(20,28,55,0.95)]"
        >
          Afficher la légende
        </button>
      </div>
    );
  }

  return (
    <div className="absolute bottom-4 right-4 z-10 w-56 rounded-xl border border-white/10 bg-[rgba(15,20,40,0.92)] backdrop-blur shadow-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-slate-200 hover:bg-white/5"
        aria-expanded={!collapsed}
      >
        <span>Trafic TVr (veh/j)</span>
        {collapsed ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {!collapsed && (
        <ul className="px-3 pb-3 space-y-1.5" role="list">
          {TVR_STOPS.slice().reverse().map((stop) => (
            <li key={stop.min} className="flex items-center gap-2 text-[11px] text-slate-200">
              <span
                aria-hidden
                className="inline-block h-2.5 w-6 rounded-sm shrink-0"
                style={{ background: stop.color }}
              />
              <span className="font-mono tabular-nums" style={{ fontFamily: 'ui-monospace, "JetBrains Mono", "SF Mono", Menlo, monospace' }}>
                {stop.label}
              </span>
            </li>
          ))}
        </ul>
      )}

      {!collapsed && onToggleVisible && (
        <button
          type="button"
          onClick={() => onToggleVisible(false)}
          className="w-full px-3 py-1.5 text-[10px] text-slate-400 hover:text-slate-200 hover:bg-white/5 border-t border-white/5"
        >
          Masquer
        </button>
      )}
    </div>
  );
}
