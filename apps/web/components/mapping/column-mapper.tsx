"use client";

import { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
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
        <div className="flex items-center gap-3">
          <div className="glass-light px-3 py-1.5 rounded-lg text-xs font-medium">
            <span className="text-accent">{mappedCount}</span>
            <span className="text-muted">
              {" "}/ {targetColumns.length} mappees
            </span>
            {criticalColumns.length > 0 && (
              <span className="text-muted">
                {" "}(dont{" "}
                <span
                  className={cn(
                    "font-semibold",
                    mappedCriticalCount === criticalColumns.length
                      ? "text-emerald-400"
                      : "text-amber-400"
                  )}
                >
                  {mappedCriticalCount}/{criticalColumns.length}
                </span>{" "}
                critiques)
              </span>
            )}
          </div>
          <div className="glass-light px-3 py-1.5 rounded-lg text-xs font-medium">
            <span className="text-cyan">{avgConfidence}%</span>
            <span className="text-muted"> confiance</span>
          </div>
        </div>
        <div className="relative">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher..."
            className="pl-8 pr-3 py-1.5 text-xs bg-surface-light border border-border rounded-lg text-foreground placeholder:text-muted outline-none focus:border-accent/40 w-48"
          />
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 rounded-full bg-surface-light overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{
            width: `${(mappedCount / targetColumns.length) * 100}%`,
          }}
          className="h-full rounded-full bg-gradient-to-r from-accent to-cyan"
        />
      </div>

      {/* Mapping rows */}
      <div className="space-y-1.5 max-h-[400px] overflow-y-auto pr-1">
        <AnimatePresence>
          {filteredMappings.map((mapping, idx) => {
            const isCritical = criticalSet.has(mapping.target);
            const isCriticalUnmapped = isCritical && !mapping.source;

            return (
              <motion.div
                key={mapping.target}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.02 }}
                className={cn(
                  "grid grid-cols-[1fr_auto_1fr] items-center gap-3 p-2.5 rounded-lg transition-colors",
                  isCriticalUnmapped
                    ? "bg-red-500/5 border border-red-500/30"
                    : mapping.source
                      ? "bg-accent/5 border border-accent/10"
                      : "bg-surface-light/50 border border-transparent"
                )}
              >
                {/* Target column */}
                <div className="flex items-center gap-2 min-w-0">
                  <div
                    className={cn(
                      "w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0",
                      mapping.source
                        ? "bg-emerald-500/20 text-emerald-400"
                        : isCritical
                          ? "bg-red-500/20 text-red-400"
                          : "bg-surface-light text-muted"
                    )}
                  >
                    {mapping.source ? (
                      <Check size={10} />
                    ) : (
                      <AlertCircle size={10} />
                    )}
                  </div>
                  <span
                    className={cn(
                      "text-xs font-mono truncate",
                      isCriticalUnmapped
                        ? "text-red-400 font-semibold"
                        : "text-foreground"
                    )}
                  >
                    {mapping.target}
                  </span>
                  {isCritical && (
                    <Star
                      size={12}
                      className={cn(
                        "flex-shrink-0",
                        mapping.source
                          ? "text-amber-400 fill-amber-400"
                          : "text-red-400 fill-red-400"
                      )}
                    />
                  )}
                </div>

                {/* Arrow */}
                <span className="text-muted text-xs">&larr;</span>

                {/* Source dropdown */}
                <select
                  value={mapping.source ?? ""}
                  onChange={(e) =>
                    updateMapping(
                      mapping.target,
                      e.target.value || null
                    )
                  }
                  className={cn(
                    "text-xs bg-surface border rounded-lg px-2 py-1.5 text-foreground outline-none focus:border-accent/40 cursor-pointer truncate",
                    isCriticalUnmapped
                      ? "border-red-500/40"
                      : "border-border"
                  )}
                >
                  <option value="">-- Non mappe --</option>
                  {sourceColumns.map((col) => (
                    <option key={col} value={col}>
                      {col}
                    </option>
                  ))}
                </select>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}
