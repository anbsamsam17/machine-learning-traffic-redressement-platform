"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { GlowCard } from "@/components/ui/glow-card";

// ---------------------------------------------------------------------------
// YearMappingPanel — bloc dedie "Mapping de l'annee" pour la Carte
// ---------------------------------------------------------------------------
// Porte de app/(pipeline)/evaluation/page.tsx (~lignes 849-948). L'annee est
// derivee cote backend a partir d'UNE seule colonne source + une table
// annee->valeur encodee (ex: 2019->1 ... 2025->7). Cette UI remplace les
// anciennes lignes 'Annee'/'annee' du mapping regulier (cf. column-mapping.ts).
// Le composant est purement controle : tout l'etat vit dans la page.
// ---------------------------------------------------------------------------

export interface YearMappingRow {
  year: string;
  value: number;
}

export interface YearMappingPanelProps {
  /** Affiche le bloc uniquement si un modele requiert l'annee. */
  visible: boolean;
  /** Colonnes du fichier FCD uploade (sourceColumns). */
  sourceColumns: string[];
  /** Colonne source selectionnee (auto-detectee au depart). */
  yearSourceCol: string;
  onYearSourceColChange: (value: string) => void;
  /** Table editable annee -> valeur encodee. */
  yearMapping: YearMappingRow[];
  onYearMappingChange: (rows: YearMappingRow[]) => void;
  /** Vrai quand la colonne source + au moins une ligne valide sont presentes. */
  yearReady: boolean;
}

export function YearMappingPanel(props: YearMappingPanelProps) {
  const {
    visible,
    sourceColumns,
    yearSourceCol,
    onYearSourceColChange,
    yearMapping,
    onYearMappingChange,
    yearReady,
  } = props;

  const updateRow = (idx: number, patch: Partial<YearMappingRow>) => {
    onYearMappingChange(
      yearMapping.map((r, i) => (i === idx ? { ...r, ...patch } : r)),
    );
  };

  return (
    <AnimatePresence>
      {visible && sourceColumns.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
          <GlowCard glowColor="cyan">
            <div className="flex items-center gap-2 mb-2">
              <ArrowRight size={18} className="text-cyan-400" />
              <h3 className="text-sm font-semibold text-white">
                Mapping de l&apos;annee
                <span className={`ml-2 text-xs ${yearReady ? "text-emerald-400" : "text-amber-400"}`}>
                  ({yearReady ? "OK" : "a configurer"})
                </span>
              </h3>
            </div>
            <p className="text-xs text-slate-400 mb-3">
              Au moins un modele a ete entraine avec la feature{" "}
              <code className="text-cyan-300">year_mapped</code>. Choisissez la
              colonne <strong>source</strong> qui contient l&apos;annee dans
              votre fichier FCD, puis confirmez la table de correspondance
              <em> annee &rarr; valeur encodee</em> (auto-remplie depuis la config
              des modeles).
            </p>

            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <span className="text-xs font-mono w-[280px] shrink-0 text-slate-200">
                  Colonne source (annee)
                </span>
                <span className="text-slate-500 text-xs">&rarr;</span>
                <select
                  value={yearSourceCol}
                  onChange={(e) => onYearSourceColChange(e.target.value)}
                  className={`flex-1 rounded-lg border px-2 py-1.5 text-xs bg-slate-900/80 focus:outline-none focus:border-cyan-500/50 cursor-pointer ${
                    yearSourceCol ? "border-white/[0.08] text-slate-200" : "border-red-500/40 text-red-300"
                  }`}
                >
                  <option value="">-- Non mappe --</option>
                  {sourceColumns.map((fc) => (
                    <option key={fc} value={fc}>{fc}</option>
                  ))}
                </select>
              </div>

              <div className="border-t border-white/[0.06] pt-3">
                <p className="text-[11px] text-slate-400 mb-2 uppercase tracking-wide">
                  Table de correspondance
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-[260px] overflow-y-auto pr-1">
                  {yearMapping.map((row, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <input
                        type="text"
                        value={row.year}
                        onChange={(e) => updateRow(idx, { year: e.target.value })}
                        placeholder="2019"
                        className="w-20 rounded border border-white/[0.08] bg-slate-900/80 px-2 py-1 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500/50"
                      />
                      <span className="text-slate-500 text-xs">&rarr;</span>
                      <input
                        type="number"
                        step="0.01"
                        value={row.value}
                        onChange={(e) => updateRow(idx, { value: parseFloat(e.target.value) })}
                        className="w-24 rounded border border-white/[0.08] bg-slate-900/80 px-2 py-1 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500/50"
                      />
                      <button
                        type="button"
                        onClick={() => onYearMappingChange(yearMapping.filter((_, i) => i !== idx))}
                        className="text-xs text-slate-500 hover:text-red-400 px-1"
                        title="Supprimer la ligne"
                      >
                        &#10005;
                      </button>
                    </div>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={() =>
                    onYearMappingChange([...yearMapping, { year: "", value: yearMapping.length + 1 }])
                  }
                  className="mt-2 text-xs text-cyan-400 hover:text-cyan-300"
                >
                  + Ajouter une annee
                </button>
              </div>
            </div>
            {!yearReady && (
              <p className="text-xs text-amber-400 mt-3">
                Configurez la colonne source ET au moins une ligne du tableau.
              </p>
            )}
          </GlowCard>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
