"use client";

import { useState, useMemo } from "react";
import { Check, AlertCircle, Search, Star } from "lucide-react";
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
  initialMappings?: ColumnMapping[];
  onMappingsChange: (mappings: ColumnMapping[]) => void;
}

export function ColumnMapper({
  targetColumns,
  sourceColumns,
  criticalColumns = [],
  initialMappings,
  onMappingsChange,
}: ColumnMapperProps) {
  const [mappings, setMappings] = useState<ColumnMapping[]>(
    initialMappings ??
      targetColumns.map((t) => ({ target: t, source: null, confidence: 0 }))
  );
  const [search, setSearch] = useState("");

  const criticalSet = useMemo(() => new Set(criticalColumns), [criticalColumns]);

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

      {/* Mapping rows */}
      <div className="space-y-1 max-h-[420px] overflow-y-auto pr-1">
        {filteredMappings.map((mapping) => {
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
    </div>
  );
}
