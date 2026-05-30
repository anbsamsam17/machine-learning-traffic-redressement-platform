"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  Filter,
  Sparkles,
  SlidersHorizontal,
  Sunrise,
  Sunset,
} from "lucide-react";

// ---------------------------------------------------------------------------
// FiltersSection — Filtres JOr/FC + tranches IC (D2 + PM + PS) + arrondi
// ---------------------------------------------------------------------------
// Le panel saturation PL/HPM/HPS reste dans la page car il a une dependance
// forte sur les capteurs SIREDO uploades. Ici on couvre uniquement la partie
// "filtres + intervalles de confiance + arrondi".
// ---------------------------------------------------------------------------

export interface FiltersSectionProps {
  // Filtres
  filterTvrEnabled: boolean;
  setFilterTvrEnabled: (v: boolean) => void;
  filterTvrValue: number;
  setFilterTvrValue: (v: number) => void;
  filterFcEnabled: boolean;
  setFilterFcEnabled: (v: boolean) => void;

  // Tranches IC v/j (D2)
  err01000: number;
  setErr01000: (v: number) => void;
  err10002000: number;
  setErr10002000: (v: number) => void;
  err20004000: number;
  setErr20004000: (v: number) => void;
  err4000plus: number;
  setErr4000plus: (v: number) => void;

  // Tranches IC v/h PM (visibles si hpmValid)
  hpmValid: boolean | null;
  errPm0100: number;
  setErrPm0100: (v: number) => void;
  errPm100300: number;
  setErrPm100300: (v: number) => void;
  errPm300600: number;
  setErrPm300600: (v: number) => void;
  errPm600plus: number;
  setErrPm600plus: (v: number) => void;

  // Tranches IC v/h PS (visibles si hpsValid)
  hpsValid: boolean | null;
  errPs0100: number;
  setErrPs0100: (v: number) => void;
  errPs100300: number;
  setErrPs100300: (v: number) => void;
  errPs300600: number;
  setErrPs300600: (v: number) => void;
  errPs600plus: number;
  setErrPs600plus: (v: number) => void;
}

export function FiltersSection(props: FiltersSectionProps) {
  const {
    filterTvrEnabled,
    setFilterTvrEnabled,
    filterTvrValue,
    setFilterTvrValue,
    filterFcEnabled,
    setFilterFcEnabled,
    err01000,
    setErr01000,
    err10002000,
    setErr10002000,
    err20004000,
    setErr20004000,
    err4000plus,
    setErr4000plus,
    hpmValid,
    errPm0100,
    setErrPm0100,
    errPm100300,
    setErrPm100300,
    errPm300600,
    setErrPm300600,
    errPm600plus,
    setErrPm600plus,
    hpsValid,
    errPs0100,
    setErrPs0100,
    errPs100300,
    setErrPs100300,
    errPs300600,
    setErrPs300600,
    errPs600plus,
    setErrPs600plus,
  } = props;

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Left — Filters */}
        <div className="space-y-5">
          <div className="flex items-center gap-2 mb-3">
            <Filter size={14} className="text-violet" />
            <span className="text-xs font-medium text-slate-200">
              Filtres sur les donnees
            </span>
          </div>

          {/* Filter JOr */}
          <label className="flex items-start gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={filterTvrEnabled}
              onChange={(e) => setFilterTvrEnabled(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-border bg-surface accent-accent cursor-pointer"
            />
            <div className="flex-1">
              <span className="text-xs font-medium text-slate-200 group-hover:text-accent transition-colors">
                Filtrer les troncons par seuil JOr
              </span>
              <p className="text-[10px] text-slate-400 mt-0.5">
                Exclure les troncons avec JOr en-dessous du seuil
              </p>
              {filterTvrEnabled && (
                <div className="mt-2 flex items-center gap-2">
                  <span className="text-[10px] text-slate-400">Seuil :</span>
                  <input
                    type="number"
                    value={filterTvrValue}
                    onChange={(e) => setFilterTvrValue(Number(e.target.value))}
                    min={0}
                    max={1000}
                    step={10}
                    className="w-20 h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none focus:border-accent/50"
                  />
                  <span className="text-[10px] text-slate-400">veh/j</span>
                </div>
              )}
            </div>
          </label>

          {/* Filter FC */}
          <label className="flex items-start gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={filterFcEnabled}
              onChange={(e) => setFilterFcEnabled(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-border bg-surface accent-accent cursor-pointer"
            />
            <div>
              <span className="text-xs font-medium text-slate-200 group-hover:text-accent transition-colors">
                Exclure les troncons FC = 1
              </span>
              <p className="text-[10px] text-slate-400 mt-0.5">
                Les autoroutes principales (Functional Class 1) seront exclues
              </p>
            </div>
          </label>
        </div>

        {/* Right — Error thresholds */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 mb-3">
            <SlidersHorizontal size={14} className="text-violet" />
            <span className="text-xs font-medium text-slate-200">
              Intervalles de confiance
            </span>
          </div>
          <p className="text-[10px] text-slate-400 -mt-2 mb-3">
            Pourcentage d&apos;erreur selon les tranches de debit JOr
          </p>

          {[
            { label: "Debits < 1 000 veh/j", value: err01000, setter: setErr01000 },
            {
              label: "Debits 1 000 - 2 000 veh/j",
              value: err10002000,
              setter: setErr10002000,
            },
            {
              label: "Debits 2 000 - 4 000 veh/j",
              value: err20004000,
              setter: setErr20004000,
            },
            {
              label: "Debits > 4 000 veh/j",
              value: err4000plus,
              setter: setErr4000plus,
            },
          ].map((item) => (
            <div key={item.label} className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-200">{item.label}</span>
                <span className="text-xs font-mono text-accent font-semibold">
                  {item.value}%
                </span>
              </div>
              <input
                type="range"
                min={5}
                max={50}
                step={1}
                value={item.value}
                onChange={(e) => item.setter(Number(e.target.value))}
                className="w-full h-1.5 rounded-full appearance-none bg-surface-light cursor-pointer accent-accent [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-accent/50 [&::-webkit-slider-thumb]:shadow-[0_0_6px_rgba(99,102,241,0.4)]"
              />
            </div>
          ))}
        </div>
      </div>

      {/* --- v/h tranches PM (visible only when HPM model loaded) --- */}
      <AnimatePresence>
        {hpmValid === true && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-8 pt-6 border-t border-white/[0.06]"
          >
            <div className="flex items-center gap-2 mb-3">
              <Sunrise size={14} className="text-pink-400" />
              <span className="text-xs font-medium text-slate-200">
                Tranches IC PM heure de pointe matin (v/h)
              </span>
            </div>
            <p className="text-[10px] text-slate-400 -mt-2 mb-3">
              Pourcentage d&apos;erreur selon les tranches du debit PM (v/h)
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
              {[
                { label: "Debits < 100 v/h", value: errPm0100, setter: setErrPm0100 },
                {
                  label: "Debits 100 - 300 v/h",
                  value: errPm100300,
                  setter: setErrPm100300,
                },
                {
                  label: "Debits 300 - 600 v/h",
                  value: errPm300600,
                  setter: setErrPm300600,
                },
                {
                  label: "Debits > 600 v/h",
                  value: errPm600plus,
                  setter: setErrPm600plus,
                },
              ].map((item) => (
                <div key={item.label} className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-slate-200">
                      {item.label}
                    </span>
                    <span className="text-xs font-mono text-pink-400 font-semibold">
                      {item.value}%
                    </span>
                  </div>
                  <input
                    type="range"
                    min={5}
                    max={50}
                    step={1}
                    value={item.value}
                    onChange={(e) => item.setter(Number(e.target.value))}
                    className="w-full h-1.5 rounded-full appearance-none bg-surface-light cursor-pointer accent-pink-500 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-pink-400 [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-pink-400/50 [&::-webkit-slider-thumb]:shadow-[0_0_6px_rgba(244,114,182,0.4)]"
                  />
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* --- v/h tranches PS (visible only when HPS model loaded) --- */}
      <AnimatePresence>
        {hpsValid === true && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-8 pt-6 border-t border-white/[0.06]"
          >
            <div className="flex items-center gap-2 mb-3">
              <Sunset size={14} className="text-violet-400" />
              <span className="text-xs font-medium text-slate-200">
                Tranches IC PS heure de pointe soir (v/h)
              </span>
            </div>
            <p className="text-[10px] text-slate-400 -mt-2 mb-3">
              Pourcentage d&apos;erreur selon les tranches du debit PS (v/h)
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
              {[
                { label: "Debits < 100 v/h", value: errPs0100, setter: setErrPs0100 },
                {
                  label: "Debits 100 - 300 v/h",
                  value: errPs100300,
                  setter: setErrPs100300,
                },
                {
                  label: "Debits 300 - 600 v/h",
                  value: errPs300600,
                  setter: setErrPs300600,
                },
                {
                  label: "Debits > 600 v/h",
                  value: errPs600plus,
                  setter: setErrPs600plus,
                },
              ].map((item) => (
                <div key={item.label} className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-slate-200">
                      {item.label}
                    </span>
                    <span className="text-xs font-mono text-violet-400 font-semibold">
                      {item.value}%
                    </span>
                  </div>
                  <input
                    type="range"
                    min={5}
                    max={50}
                    step={1}
                    value={item.value}
                    onChange={(e) => item.setter(Number(e.target.value))}
                    className="w-full h-1.5 rounded-full appearance-none bg-surface-light cursor-pointer accent-violet-500 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-violet-400 [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-violet-400/50 [&::-webkit-slider-thumb]:shadow-[0_0_6px_rgba(167,139,250,0.4)]"
                  />
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

// ---------------------------------------------------------------------------
// ArrondiToggleCard — bloc "Arrondi progressif" (extrait de la section 3)
// ---------------------------------------------------------------------------

export interface ArrondiToggleCardProps {
  arrondiEnabled: boolean;
  setArrondiEnabled: (v: boolean) => void;
}

export function ArrondiToggleCard({
  arrondiEnabled,
  setArrondiEnabled,
}: ArrondiToggleCardProps) {
  return (
    <div className="mt-8 pt-6 border-t border-white/[0.06]">
      <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/[0.04] p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-cyan-400" />
            <span className="font-semibold text-cyan-300">
              Arrondi progressif
            </span>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={arrondiEnabled}
            onClick={() => setArrondiEnabled(!arrondiEnabled)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-cyan-400/50 ${
              arrondiEnabled
                ? "bg-cyan-500/70 shadow-[0_0_8px_rgba(34,211,238,0.4)]"
                : "bg-slate-700"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                arrondiEnabled ? "translate-x-5" : "translate-x-1"
              }`}
            />
          </button>
        </div>
        <p className="text-xs text-slate-400 leading-relaxed">
          Arrondit progressivement les valeurs pour ameliorer la lisibilite
          cartographique :
          <br />
          <span className="font-mono text-cyan-300">
            v &lt; 100 -&gt; multiple de 5
          </span>
          <br />
          <span className="font-mono text-cyan-300">
            100 &le; v &lt; 1000 -&gt; multiple de 10
          </span>
          <br />
          <span className="font-mono text-cyan-300">
            v &ge; 1000 -&gt; multiple de 100
          </span>
          <br />
          <span className="text-slate-500 italic mt-1 block">
            Applique sur JOr, DPL, PM, PS (+ leurs IC min/max). Precision
            relative ~5% (coherent incertitude modele).
          </span>
        </p>
        {!arrondiEnabled && (
          <div className="mt-2 px-2 py-1.5 rounded bg-amber-500/10 border border-amber-500/30 text-xs text-amber-200">
            Valeurs a l&apos;unite conservees &mdash; lisibilite reduite pour
            gros debits
          </div>
        )}
      </div>
    </div>
  );
}
