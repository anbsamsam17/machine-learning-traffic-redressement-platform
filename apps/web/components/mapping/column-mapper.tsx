"use client";

import { useState, useMemo } from "react";
import { Check, AlertCircle, Search, Star, Plus } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ColumnMapping {
  target: string;
  source: string | null;
  confidence: number;
}

interface ColumnMapperProps {
  targetColumns: string[];
  sourceColumns: string[];
  criticalColumns?: string[];
  /** Optional grouping: category name → list of target column names (in order). */
  groups?: Record<string, string[]>;
  /** Source columns NOT auto-mapped — proposed as free additional variables. */
  extraCandidates?: string[];
  /** Currently selected extra columns to include in the learning_df. */
  selectedExtras?: string[];
  initialMappings?: ColumnMapping[];
  onMappingsChange: (mappings: ColumnMapping[]) => void;
  onExtrasChange?: (extras: string[]) => void;
}

// Emojis per group, requested explicitly in the brief. Kept in a single
// constant so the rest of the app can stay emoji-free.
const GROUP_EMOJIS: Record<string, string> = {
  "Identification": "🆔",
  "Comptage capteur": "🚗",
  "FCD HERE": "📡",
  "Taux de penetration": "📊",
  "Mapping & qualite": "🗺️",
  "Reseau HERE": "🛣️",
  "Vitesses FCD": "🏎️",
  "Distances VL": "📏",
  "Distances PL": "🚛",
  "Geometrie": "🌐",
};

// Friendly suffix added to some group names (matches Etape1_MDL_TV.txt).
const GROUP_HINTS: Record<string, string> = {
  "Comptage capteur": "BC = Boucle Comptage",
};

export function ColumnMapper({
  targetColumns,
  sourceColumns,
  criticalColumns = [],
  groups,
  extraCandidates = [],
  selectedExtras = [],
  initialMappings,
  onMappingsChange,
  onExtrasChange,
}: ColumnMapperProps) {
  const [mappings, setMappings] = useState<ColumnMapping[]>(
    initialMappings ??
      targetColumns.map((t) => ({ target: t, source: null, confidence: 0 }))
  );
  const [search, setSearch] = useState("");
  const [localExtras, setLocalExtras] = useState<string[]>(selectedExtras);
  const [extrasOpen, setExtrasOpen] = useState(extraCandidates.length > 0);

  const criticalSet = useMemo(() => new Set(criticalColumns), [criticalColumns]);
  const extrasSet = useMemo(() => new Set(localExtras), [localExtras]);

  const mappedCount = useMemo(
    () => mappings.filter((m) => m.source !== null).length,
    [mappings]
  );

  const mappedCriticalCount = useMemo(
    () =>
      mappings.filter((m) => m.source !== null && criticalSet.has(m.target))
        .length,
    [mappings, criticalSet]
  );

  const avgConfidence = useMemo(() => {
    const mapped = mappings.filter((m) => m.source !== null);
    if (mapped.length === 0) return 0;
    return Math.round(
      mapped.reduce((s, m) => s + m.confidence, 0) / mapped.length
    );
  }, [mappings]);

  const filteredMappings = useMemo(() => {
    if (!search) return mappings;
    const q = search.toLowerCase();
    return mappings.filter(
      (m) =>
        m.target.toLowerCase().includes(q) ||
        (m.source && m.source.toLowerCase().includes(q))
    );
  }, [mappings, search]);

  // Build ordered list of (groupName | null, mapping) rows so we can interleave
  // category headers between target rows. When `groups` is not provided we fall
  // back to a single flat list (legacy mode).
  const rowsWithHeaders = useMemo(() => {
    if (!groups) {
      return filteredMappings.map((m) => ({ kind: "row" as const, mapping: m }));
    }
    const seen = new Set<string>();
    const rows: Array<
      | { kind: "header"; group: string }
      | { kind: "row"; mapping: ColumnMapping }
    > = [];
    for (const [group, targets] of Object.entries(groups)) {
      const inGroup = filteredMappings.filter((m) => targets.includes(m.target));
      if (inGroup.length === 0) continue;
      rows.push({ kind: "header", group });
      for (const m of inGroup) {
        rows.push({ kind: "row", mapping: m });
        seen.add(m.target);
      }
    }
    // Tail: any filteredMappings not covered by any group
    const orphaned = filteredMappings.filter((m) => !seen.has(m.target));
    if (orphaned.length > 0) {
      rows.push({ kind: "header", group: "Autres" });
      for (const m of orphaned) rows.push({ kind: "row", mapping: m });
    }
    return rows;
  }, [filteredMappings, groups]);

  const progressPct =
    targetColumns.length > 0
      ? Math.round((mappedCount / targetColumns.length) * 100)
      : 0;

  function updateMapping(target: string, source: string | null) {
    const next = mappings.map((m) =>
      m.target === target
        ? { ...m, source, confidence: source ? 100 : 0 }
        : m
    );
    setMappings(next);
    onMappingsChange(next);
  }

  function toggleExtra(col: string) {
    const next = extrasSet.has(col)
      ? localExtras.filter((c) => c !== col)
      : [...localExtras, col];
    setLocalExtras(next);
    onExtrasChange?.(next);
  }

  return (
    <div className="space-y-4">
      {/* Header stats */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <div className="bg-bg-elevated border border-border px-2.5 py-1 rounded text-xs font-medium">
            <span className="text-accent font-mono tabular-nums">
              {mappedCount}
            </span>
            <span className="text-text-muted">
              {" "}
              / {targetColumns.length} mappees
            </span>
            {criticalColumns.length > 0 && (
              <span className="text-text-muted">
                {" "}
                (dont{" "}
                <span
                  className={cn(
                    "font-mono tabular-nums font-semibold",
                    mappedCriticalCount === criticalColumns.length
                      ? "text-success"
                      : "text-warning"
                  )}
                >
                  {mappedCriticalCount}/{criticalColumns.length}
                </span>{" "}
                critiques)
              </span>
            )}
          </div>
          <div className="bg-bg-elevated border border-border px-2.5 py-1 rounded text-xs font-medium">
            <span className="text-accent font-mono tabular-nums">
              {avgConfidence}%
            </span>
            <span className="text-text-muted"> confiance</span>
          </div>
          {localExtras.length > 0 && (
            <div className="bg-bg-elevated border border-accent/40 px-2.5 py-1 rounded text-xs font-medium">
              <span className="text-accent font-mono tabular-nums">
                +{localExtras.length}
              </span>
              <span className="text-text-muted"> colonnes additionnelles</span>
            </div>
          )}
        </div>
        <div className="relative">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
            aria-hidden="true"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher..."
            className="pl-8 pr-3 h-8 text-xs bg-bg-elevated border border-border rounded text-text placeholder:text-text-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent w-48"
          />
        </div>
      </div>

      {/* Progress bar */}
      <div
        className="h-1 rounded-full bg-bg-subtle overflow-hidden"
        role="progressbar"
        aria-valuenow={progressPct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full bg-accent transition-[width] duration-300"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Mapping rows (grouped by category if `groups` is provided) */}
      <div className="space-y-1 max-h-[420px] overflow-y-auto pr-1">
        {rowsWithHeaders.map((entry) => {
          if (entry.kind === "header") {
            const emoji = GROUP_EMOJIS[entry.group] ?? "";
            const hint = GROUP_HINTS[entry.group];
            return (
              <div
                key={`hdr-${entry.group}`}
                className="sticky top-0 z-10 bg-bg/95 backdrop-blur-sm border-b border-border/60 px-2 py-1.5 mt-2 first:mt-0 flex items-center gap-2"
              >
                <span className="text-base leading-none" aria-hidden="true">
                  {emoji}
                </span>
                <span className="text-[11px] font-semibold uppercase tracking-wide text-text">
                  {entry.group}
                </span>
                {hint && (
                  <span className="text-[10px] text-text-muted normal-case">
                    ({hint})
                  </span>
                )}
              </div>
            );
          }

          const mapping = entry.mapping;
          const isCritical = criticalSet.has(mapping.target);
          const isCriticalUnmapped = isCritical && !mapping.source;

          return (
            <div
              key={mapping.target}
              className={cn(
                "grid grid-cols-[1fr_auto_1fr] items-center gap-3 p-2 rounded border transition-colors",
                isCriticalUnmapped
                  ? "bg-danger/5 border-danger/30"
                  : mapping.source
                    ? "bg-bg-elevated border-border"
                    : "bg-bg-elevated/50 border-transparent"
              )}
            >
              <div className="flex items-center gap-2 min-w-0">
                <div
                  className={cn(
                    "w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0",
                    mapping.source
                      ? "bg-success/15 text-success"
                      : isCritical
                        ? "bg-danger/15 text-danger"
                        : "bg-bg-subtle text-text-muted"
                  )}
                >
                  {mapping.source ? (
                    <Check size={10} aria-hidden="true" />
                  ) : (
                    <AlertCircle size={10} aria-hidden="true" />
                  )}
                </div>
                <span
                  className={cn(
                    "text-xs font-mono truncate",
                    isCriticalUnmapped
                      ? "text-danger font-semibold"
                      : "text-text"
                  )}
                >
                  {mapping.target}
                </span>
                {isCritical && (
                  <Star
                    size={11}
                    className={cn(
                      "flex-shrink-0",
                      mapping.source
                        ? "text-warning fill-warning"
                        : "text-danger fill-danger"
                    )}
                    aria-hidden="true"
                  />
                )}
              </div>

              <span className="text-text-subtle text-xs">&larr;</span>

              <select
                value={mapping.source ?? ""}
                onChange={(e) =>
                  updateMapping(mapping.target, e.target.value || null)
                }
                className={cn(
                  "text-xs h-8 bg-bg-elevated border rounded px-2 text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent cursor-pointer truncate font-mono",
                  isCriticalUnmapped ? "border-danger/40" : "border-border"
                )}
                aria-label={`Source pour ${mapping.target}`}
              >
                <option value="">-- Non mappe --</option>
                {sourceColumns.map((col) => (
                  <option key={col} value={col}>
                    {col}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
      </div>

      {/* Extras section: add free columns from the source DataFrame */}
      {extraCandidates.length > 0 && (
        <div className="border-t border-border pt-4">
          <button
            type="button"
            onClick={() => setExtrasOpen((v) => !v)}
            className="flex w-full items-center justify-between text-left mb-2"
          >
            <div className="flex items-center gap-2">
              <Plus size={14} className="text-accent" aria-hidden="true" />
              <span className="text-[11px] font-semibold uppercase tracking-wide text-text">
                Colonnes additionnelles
              </span>
              <span className="text-[10px] text-text-muted normal-case">
                ({extraCandidates.length} dispo, {localExtras.length} selectionnees)
              </span>
            </div>
            <span className="text-text-muted text-xs">{extrasOpen ? "−" : "+"}</span>
          </button>
          {extrasOpen && (
            <>
              <p className="text-[11px] text-text-muted mb-3">
                Selectionnez les colonnes additionnelles a embarquer dans la
                table d&apos;apprentissage en plus des colonnes standardisees.
                Elles seront disponibles comme variables d&apos;entree dans la
                configuration du grid search.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
                {extraCandidates.map((col) => {
                  const checked = extrasSet.has(col);
                  return (
                    <label
                      key={col}
                      className={cn(
                        "flex items-center gap-2 p-2 rounded border cursor-pointer transition-colors text-xs",
                        checked
                          ? "bg-accent/10 border-accent/40"
                          : "bg-bg-elevated/50 border-border hover:border-border-strong"
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleExtra(col)}
                        className="size-3.5 accent-accent cursor-pointer"
                      />
                      <span
                        className={cn(
                          "font-mono truncate",
                          checked ? "text-text" : "text-text-muted"
                        )}
                      >
                        {col}
                      </span>
                    </label>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
