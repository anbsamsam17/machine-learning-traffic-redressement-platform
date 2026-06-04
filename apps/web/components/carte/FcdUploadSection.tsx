"use client";

import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Layers, Loader2 } from "lucide-react";
import { DropZone } from "@/components/upload/drop-zone";
import { GlowCard } from "@/components/ui/glow-card";
import type {
  CarteModelUploadResponse,
  ColumnDef,
} from "@/lib/carte/types";

// ---------------------------------------------------------------------------
// FcdUploadSection — upload FCD + affichage du mapping de colonnes
// ---------------------------------------------------------------------------
// Le mapping reel est calcule cote parent (depend de tvModelInfo, plModelInfo
// etc.) et passe en props. Le composant ne fait que rendre l'UI + dispatcher
// les selects vers updateMapping.
// ---------------------------------------------------------------------------

export interface FcdUploadSectionProps {
  // Upload state
  fcdFile: File | null;
  uploading: boolean;
  sessionId: string | null;
  rowCount: number;
  sourceColumns: string[];
  onFcdUpload: (file: File) => void;
  onFcdClear: () => void;

  // Mapping state
  columnMapping: Record<string, string | null>;
  updateMapping: (key: string, value: string | null) => void;
  dynamicRequiredColumns: ColumnDef[];
  mappedRequiredCount: number;
  requiredTargetsCount: number;
  requiredMapped: boolean;

  // Models (utilises pour decider d'afficher le mapping)
  tvModelInfo: CarteModelUploadResponse | null;
  plModelInfo: CarteModelUploadResponse | null;
}

export function FcdUploadSection(props: FcdUploadSectionProps) {
  const {
    fcdFile,
    uploading,
    sessionId,
    rowCount,
    sourceColumns,
    onFcdUpload,
    onFcdClear,
    columnMapping,
    updateMapping,
    dynamicRequiredColumns,
    mappedRequiredCount,
    requiredTargetsCount,
    requiredMapped,
    tvModelInfo,
    plModelInfo,
  } = props;

  return (
    <GlowCard glowColor="cyan">
      <div className="flex items-center gap-2 mb-5">
        <div className="w-7 h-7 rounded-lg bg-cyan/20 flex items-center justify-center text-cyan text-xs font-bold">
          1
        </div>
        <h3 className="text-sm font-semibold text-white">Donnees FCD</h3>
      </div>

      <DropZone
        file={fcdFile}
        onFile={onFcdUpload}
        onClear={onFcdClear}
        accept={{
          "application/json": [".geojson", ".json"],
          "application/geo+json": [".geojson"],
          // Parquet — backend /api/upload accepts it (lines 89-104 of
          // routers/upload.py). MIME varies by OS so we also allow the
          // generic application/octet-stream fallback that browsers use
          // when they don't recognise the extension.
          "application/octet-stream": [".parquet"],
          "application/vnd.apache.parquet": [".parquet"],
        }}
        label="Deposez votre fichier FCD (geojson, json ou parquet)"
        description=".geojson, .json ou .parquet"
      />

      {uploading && (
        <div className="flex items-center gap-2 mt-3 text-xs text-slate-400">
          <Loader2 size={14} className="animate-spin" />
          <span>Chargement et analyse du fichier...</span>
        </div>
      )}

      {sessionId && rowCount > 0 && (
        <div className="mt-3 text-xs text-emerald-400">
          {rowCount} troncons routiers charges
        </div>
      )}

      {/* Hint: mapping form will appear after the TV model is loaded.
          PL is optional, so we gate only on the mandatory TV model. Avoids
          exposing the legacy fallback REQUIRED_COLUMNS list when no
          training_config is available yet (would confuse the user into
          mapping columns the new models don't even need). */}
      {sessionId &&
        rowCount > 0 &&
        !tvModelInfo?.training_config && (
          <div className="mt-3 flex items-start gap-2 px-3 py-2 rounded-lg bg-cyan/5 border border-cyan/20 text-cyan text-xs">
            <Layers size={14} className="mt-0.5 flex-shrink-0" />
            <span>
              Importez maintenant le modele TV (Etape 2) pour configurer le
              mapping des colonnes en fonction des entrees attendues. Le modele
              PL est optionnel et ajoute ses propres colonnes au mapping s&apos;il
              est charge.
            </span>
          </div>
        )}

      {/* Column Mapping — appears as soon as the mandatory TV model is loaded.
          PL is optional : if loaded, computeDynamicRequiredColumns merges its
          input columns into the list; if not, the form shows the TV-only set. */}
      <AnimatePresence>
        {sourceColumns.length > 0 &&
          dynamicRequiredColumns.length > 0 &&
          tvModelInfo && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-6 space-y-4"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <Layers size={16} className="text-cyan" />
                <span className="text-xs font-semibold text-white">
                  Mapping des colonnes
                </span>
                <span className="text-[10px] text-slate-400 ml-2">
                  ({mappedRequiredCount}/{requiredTargetsCount} obligatoires
                  mappees)
                </span>
                {tvModelInfo?.training_config &&
                (!plModelInfo || plModelInfo.training_config) ? (
                  <span className="text-[10px] text-cyan/80 bg-cyan/10 px-1.5 py-0.5 rounded">
                    Champs derives du training_config des modeles
                  </span>
                ) : (
                  <span className="text-[10px] text-slate-400 bg-surface-light px-1.5 py-0.5 rounded">
                    Mode compatibilite (modele sans training_config)
                  </span>
                )}
              </div>

              {/* Progress bar */}
              <div className="h-1 rounded-full bg-surface-light overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{
                    width: `${
                      requiredTargetsCount === 0
                        ? 0
                        : (mappedRequiredCount / requiredTargetsCount) * 100
                    }%`,
                  }}
                  className="h-full rounded-full bg-gradient-to-r from-accent to-cyan"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {dynamicRequiredColumns.map((col) => (
                  <div
                    key={col.key}
                    className={`flex items-center gap-3 p-2.5 rounded-lg transition-colors ${
                      columnMapping[col.key]
                        ? "bg-accent/5 border border-accent/10"
                        : col.required
                          ? "bg-red-500/5 border border-red-500/20"
                          : "bg-surface-light/50 border border-transparent"
                    }`}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-mono text-slate-200 truncate">
                          {col.key}
                        </span>
                        {!col.required && (
                          <span className="text-[9px] text-slate-400 bg-surface-light px-1.5 py-0.5 rounded">
                            optionnel
                          </span>
                        )}
                      </div>
                      <p className="text-[10px] text-slate-400 mt-0.5 truncate">
                        {col.description}
                      </p>
                    </div>
                    <span className="text-slate-500 text-xs flex-shrink-0">
                      &larr;
                    </span>
                    <select
                      value={columnMapping[col.key] ?? ""}
                      onChange={(e) =>
                        updateMapping(col.key, e.target.value || null)
                      }
                      className={`text-xs bg-surface border rounded-lg px-2 py-1.5 text-slate-200 outline-none focus:border-accent/40 cursor-pointer w-44 truncate ${
                        !columnMapping[col.key] && col.required
                          ? "border-red-500/40"
                          : "border-border"
                      }`}
                    >
                      <option value="">
                        {col.required ? "-- Selectionner --" : "-- Ignorer --"}
                      </option>
                      {sourceColumns.map((sc) => (
                        <option key={sc} value={sc}>
                          {sc}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>

              {requiredMapped && (
                <div className="flex items-center gap-1.5 text-emerald-400 text-xs">
                  <CheckCircle2 size={14} />
                  <span>Toutes les colonnes obligatoires sont mappees</span>
                </div>
              )}
            </motion.div>
          )}
      </AnimatePresence>
    </GlowCard>
  );
}
