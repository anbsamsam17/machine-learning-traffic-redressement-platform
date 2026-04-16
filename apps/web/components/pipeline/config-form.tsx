"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronDown,
  Layers,
  Zap,
  Settings2,
  Calendar,
  Pin,
  Brain,
  Scale,
  Plus,
  X,
  Hash,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { TagInput } from "@/components/ui/tag-input";
import { NeonButton } from "@/components/ui/neon-button";
import type { AppMode } from "@/lib/store";

// ─── Constants TV ───────────────────────────────────────────────────────────
const DEFAULT_INPUT_COLS_TV = [
  "TMJAFCDTV",
  "TMJAFCDPL",
  "car_average_distance_km",
  "car_average_speed_kmh",
  "truck_min_average_distance_km",
  "truck_average_speed_kmh",
];
const EXTRA_INPUT_COLS_TV = [
  "variabilite_FCD",
  "car_count",
  "truck_count",
  "TMJAVL",
];

// ─── Constants PL ───────────────────────────────────────────────────────────
const DEFAULT_INPUT_COLS_PL = [
  "TMJAFCDPL",
  "car_average_distance_km",
  "car_average_speed_kmh",
  "truck_min_average_distance_km",
  "truck_average_speed_kmh",
];
const EXTRA_INPUT_COLS_PL = [
  "TMJAFCDTV",
  "TMJAFCDVL",
  "variabilite_FCD",
  "truck_count",
  "car_count",
];

// ─── Shared constants ───────────────────────────────────────────────────────
const ALL_ACTIVATIONS = ["elu", "relu", "tanh", "sigmoid", "selu"] as const;
const ALL_LOSSES = ["mse", "huber", "mae"] as const;
const PREDEFINED_ARCHS = [
  "[1, 1]",
  "[2, 1]",
  "[2, 1, 0.5]",
  "[1, 1, 0.5]",
  "[1, 0.5]",
  "[0.5, 0.5]",
  "[3, 2, 1]",
  "[3, 2, 1, 0.5]",
] as const;

const ARCH_MAP: Record<string, number[]> = {
  "[1, 1]": [1.0, 1.0],
  "[2, 1]": [2.0, 1.0],
  "[2, 1, 0.5]": [2.0, 1.0, 0.5],
  "[1, 1, 0.5]": [1.0, 1.0, 0.5],
  "[1, 0.5]": [1.0, 0.5],
  "[0.5, 0.5]": [0.5, 0.5],
  "[3, 2, 1]": [3.0, 2.0, 1.0],
  "[3, 2, 1, 0.5]": [3.0, 2.0, 1.0, 0.5],
};

// ─── Types ──────────────────────────────────────────────────────────────────
export interface TrainingConfig {
  mode: "grid";
  model_type: "TV" | "PL";
  input_cols: string[];
  output_cols: string[];
  on_off_norm: boolean[];
  use_year_feature: boolean;
  year_column_name: string | null;
  year_value_mapping: Record<string, number>;
  year_normalization: boolean;
  mandatory_input_cols: string[];
  min_input_count: number;
  feature_subset_grid: boolean;
  activations: string[];
  learning_rates: number[];
  losses: string[];
  min_nb_epochs_list: number[];
  max_epochs: number;
  test_size: number;
  neurons_factors_list: number[][];
  use_batch_norm: boolean;
  dropouts: number[];
  batch_sizes: number[];
  use_flag_comptage_weighting: boolean;
  flag_comptage_col: string;
  flag_priority_weight: number;
  analysis_scope: string;
  seed: number;
}

interface ConfigFormProps {
  mode: AppMode;
  availableColumns?: string[];  // all columns from the mapped learning table
  onSubmit: (config: TrainingConfig) => void;
}

// ─── Accordion section ──────────────────────────────────────────────────────
function Section({
  title,
  icon,
  children,
  defaultOpen = true,
  badge,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
  badge?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-white/[0.06] bg-gradient-to-br from-slate-900/80 to-slate-950/80 backdrop-blur-xl overflow-hidden"
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 text-sm font-semibold text-slate-200 hover:bg-white/[0.03] transition-colors"
      >
        <span className="flex items-center gap-2.5">
          {icon}
          {title}
          {badge && (
            <span className="ml-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/20">
              {badge}
            </span>
          )}
        </span>
        <motion.div
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
        >
          <ChevronDown size={16} className="text-slate-500" />
        </motion.div>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-5 space-y-4">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ─── Chip toggle ────────────────────────────────────────────────────────────
function Chip({
  label,
  active,
  onClick,
  removable,
  onRemove,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  removable?: boolean;
  onRemove?: () => void;
}) {
  return (
    <motion.button
      type="button"
      whileHover={{ scale: 1.04 }}
      whileTap={{ scale: 0.96 }}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all duration-200",
        active
          ? "bg-indigo-500/15 text-indigo-300 border-indigo-500/30 shadow-[0_0_8px_rgba(99,102,241,0.15)]"
          : "bg-slate-800/50 text-slate-400 border-slate-700/50 hover:border-slate-600"
      )}
    >
      {label}
      {removable && onRemove && (
        <span
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="ml-0.5 hover:text-red-400 cursor-pointer"
        >
          <X size={12} />
        </span>
      )}
    </motion.button>
  );
}

// ─── Checkbox toggle ────────────────────────────────────────────────────────
function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2.5 cursor-pointer group">
      <div
        onClick={() => onChange(!checked)}
        className={cn(
          "w-8 h-[18px] rounded-full relative transition-colors duration-200 cursor-pointer",
          checked ? "bg-indigo-500" : "bg-slate-700"
        )}
      >
        <motion.div
          animate={{ x: checked ? 14 : 2 }}
          transition={{ type: "spring", stiffness: 500, damping: 30 }}
          className="absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white shadow-sm"
        />
      </div>
      <span className="text-xs text-slate-300 group-hover:text-slate-200 transition-colors">
        {label}
      </span>
    </label>
  );
}

// ─── Number input ───────────────────────────────────────────────────────────
function NumberInput({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  help,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  help?: string;
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-slate-400">{label}</label>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        className="w-full px-3 py-2 text-sm bg-slate-800/60 border border-slate-700/60 rounded-lg text-slate-200 outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/20 transition-all"
      />
      {help && <p className="text-[10px] text-slate-500">{help}</p>}
    </div>
  );
}

// ─── Slider with value display ──────────────────────────────────────────────
function SliderInput({
  label,
  value,
  onChange,
  min,
  max,
  step,
  help,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  help?: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-xs font-medium text-slate-400">{label}</label>
        <span className="text-xs font-mono text-indigo-300 bg-indigo-500/10 px-2 py-0.5 rounded">
          {value.toFixed(2)}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none bg-slate-700 cursor-pointer accent-indigo-500 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-indigo-400 [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-indigo-300 [&::-webkit-slider-thumb]:shadow-[0_0_6px_rgba(99,102,241,0.4)]"
      />
      {help && <p className="text-[10px] text-slate-500">{help}</p>}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// Main Form
// ═══════════════════════════════════════════════════════════════════════════
export function ConfigForm({ mode, availableColumns, onSubmit }: ConfigFormProps) {
  const isTv = mode !== "pl";

  // ── Section 1 : Colonnes d'entree/sortie ────────────────────────────────
  const defaultCols = isTv ? DEFAULT_INPUT_COLS_TV : DEFAULT_INPUT_COLS_PL;
  const fallbackExtras = isTv ? EXTRA_INPUT_COLS_TV : EXTRA_INPUT_COLS_PL;

  const [inputCols, setInputCols] = useState<string[]>([...defaultCols]);
  const [onOffNorm, setOnOffNorm] = useState<Record<string, boolean>>(
    () => Object.fromEntries(defaultCols.map((c) => [c, true]))
  );
  const [outputCol] = useState(isTv ? "TxPenTVRef" : "TxPenPLRef");

  // Available extras = all columns from the mapped table that are not already selected
  // If availableColumns is provided (from the learning table), use those; otherwise fallback
  const allCandidates = availableColumns && availableColumns.length > 0
    ? availableColumns
    : [...defaultCols, ...fallbackExtras];
  const availableExtras = allCandidates.filter((c) => !inputCols.includes(c));

  const toggleInputCol = useCallback(
    (col: string) => {
      setInputCols((prev) => {
        if (prev.includes(col)) {
          const next = prev.filter((c) => c !== col);
          setOnOffNorm((n) => {
            const copy = { ...n };
            delete copy[col];
            return copy;
          });
          return next;
        }
        setOnOffNorm((n) => ({ ...n, [col]: true }));
        return [...prev, col];
      });
    },
    []
  );

  const addExtraCol = useCallback(
    (col: string) => {
      if (!inputCols.includes(col)) {
        setInputCols((prev) => [...prev, col]);
        setOnOffNorm((n) => ({ ...n, [col]: true }));
      }
    },
    [inputCols]
  );

  const removeInputCol = useCallback((col: string) => {
    setInputCols((prev) => prev.filter((c) => c !== col));
    setOnOffNorm((n) => {
      const copy = { ...n };
      delete copy[col];
      return copy;
    });
  }, []);

  // ── Section 2 : Feature annee ───────────────────────────────────────────
  const [useYearFeature, setUseYearFeature] = useState(false);
  const [yearColumnName, setYearColumnName] = useState("Annee");
  const [yearNormalization, setYearNormalization] = useState(false);
  const [yearMapping, setYearMapping] = useState<
    { year: string; value: number }[]
  >([
    { year: "2023", value: 1 },
    { year: "2024", value: 2 },
    { year: "2025", value: 3 },
  ]);

  // ── Section 3 : Colonnes obligatoires ───────────────────────────────────
  const defaultMandatory = isTv
    ? ["TMJAFCDTV", "TMJAFCDPL"]
    : ["TMJAFCDPL"];
  const [mandatoryCols, setMandatoryCols] = useState<string[]>(
    defaultMandatory.filter((c) => defaultCols.includes(c))
  );
  const [minInputCount, setMinInputCount] = useState(isTv ? 3 : 2);

  // ── Section 4 : Hyperparametres ─────────────────────────────────────────
  const [activations, setActivations] = useState<string[]>(["elu"]);
  const [learningRates, setLearningRates] = useState<string[]>(["0.01"]);
  const [losses, setLosses] = useState<string[]>(["mse"]);
  const [minEpochs, setMinEpochs] = useState<string[]>(["500", "1000"]);
  const [maxEpochs, setMaxEpochs] = useState(2050);
  const [testSize, setTestSize] = useState(0.0);

  // ── Section 5 : Architecture ────────────────────────────────────────────
  const [selectedArchs, setSelectedArchs] = useState<string[]>(["[1, 1]"]);
  const [useBatchNorm, setUseBatchNorm] = useState(false);
  const [dropouts, setDropouts] = useState<string[]>(["0.05"]);
  const [batchSizes, setBatchSizes] = useState<string[]>(["256"]);

  // ── Section 6 : Ponderation ─────────────────────────────────────────────
  const [useWeighting, setUseWeighting] = useState(false);
  const [flagWeight, setFlagWeight] = useState(4.0);

  // ── Dropdown for extras ─────────────────────────────────────────────────
  const [showExtraDropdown, setShowExtraDropdown] = useState(false);

  // ── Compute combinations ──────────────────────────────────────────────────
  const combinationsCount = useMemo(() => {
    const optionalCols = inputCols.filter(
      (c) => !mandatoryCols.includes(c)
    );
    const minOptional = Math.max(0, minInputCount - mandatoryCols.length);

    // combinations(n, k)
    function comb(n: number, k: number): number {
      if (k > n || k < 0) return 0;
      if (k === 0 || k === n) return 1;
      let result = 1;
      for (let i = 0; i < Math.min(k, n - k); i++) {
        result = (result * (n - i)) / (i + 1);
      }
      return Math.round(result);
    }

    let featureSets = 0;
    for (let k = minOptional; k <= optionalCols.length; k++) {
      featureSets += comb(optionalCols.length, k);
    }
    featureSets = Math.max(featureSets, 1);

    const nActivations = Math.max(activations.length, 1);
    const nLr = Math.max(learningRates.length, 1);
    const nEpochs = Math.max(minEpochs.length, 1);
    const nLosses = Math.max(losses.length, 1);
    const nDropouts = Math.max(dropouts.length, 1);
    const nArchs = Math.max(selectedArchs.length, 1);
    const nBatch = Math.max(batchSizes.length, 1);

    return (
      featureSets *
      nActivations *
      nLr *
      nEpochs *
      nLosses *
      nDropouts *
      nArchs *
      nBatch
    );
  }, [
    inputCols,
    mandatoryCols,
    minInputCount,
    activations,
    learningRates,
    minEpochs,
    losses,
    dropouts,
    selectedArchs,
    batchSizes,
  ]);

  // ── Submit ────────────────────────────────────────────────────────────────
  const handleSubmit = useCallback(() => {
    const finalInputCols = [...inputCols];
    const finalOnOff = inputCols.map((c) => onOffNorm[c] ?? true);

    if (useYearFeature && yearColumnName) {
      if (!finalInputCols.includes("year_mapped")) {
        finalInputCols.push("year_mapped");
        finalOnOff.push(yearNormalization);
      }
    }

    const yearMappingObj: Record<string, number> = {};
    if (useYearFeature) {
      yearMapping.forEach(({ year, value }) => {
        if (year.trim()) yearMappingObj[year.trim()] = value;
      });
    }

    const config: TrainingConfig = {
      mode: "grid",
      model_type: isTv ? "TV" : "PL",
      input_cols: finalInputCols,
      output_cols: [outputCol],
      on_off_norm: finalOnOff,
      use_year_feature: useYearFeature,
      year_column_name: useYearFeature ? yearColumnName : null,
      year_value_mapping: useYearFeature ? yearMappingObj : {},
      year_normalization: useYearFeature ? yearNormalization : false,
      mandatory_input_cols: mandatoryCols,
      min_input_count: minInputCount,
      feature_subset_grid: true,
      activations,
      learning_rates: learningRates.map((v) => parseFloat(v)).filter((v) => !isNaN(v)),
      losses,
      min_nb_epochs_list: minEpochs.map((v) => parseInt(v, 10)).filter((v) => !isNaN(v)),
      max_epochs: maxEpochs,
      test_size: testSize,
      neurons_factors_list: selectedArchs.map(
        (k) => ARCH_MAP[k] ?? [1.0, 1.0]
      ),
      use_batch_norm: useBatchNorm,
      dropouts: dropouts.map((v) => parseFloat(v)).filter((v) => !isNaN(v)),
      batch_sizes: batchSizes.map((v) => parseInt(v, 10)).filter((v) => !isNaN(v)),
      use_flag_comptage_weighting: useWeighting,
      flag_comptage_col: "flag_comptage",
      flag_priority_weight: flagWeight,
      analysis_scope: "all",
      seed: 1750,
    };

    onSubmit(config);
  }, [
    inputCols,
    onOffNorm,
    outputCol,
    useYearFeature,
    yearColumnName,
    yearNormalization,
    yearMapping,
    mandatoryCols,
    minInputCount,
    activations,
    learningRates,
    losses,
    minEpochs,
    maxEpochs,
    testSize,
    selectedArchs,
    useBatchNorm,
    dropouts,
    batchSizes,
    useWeighting,
    flagWeight,
    isTv,
    onSubmit,
  ]);

  // Sync mandatory cols when input cols change
  useEffect(() => {
    setMandatoryCols((prev) => prev.filter((c) => inputCols.includes(c)));
  }, [inputCols]);

  return (
    <div className="space-y-4">
      {/* ═══════════ Section 1 : Colonnes d'entree / sortie ═══════════ */}
      <Section
        title="Colonnes d'entree et de sortie"
        icon={<Layers size={16} className="text-indigo-400" />}
        defaultOpen
      >
        {/* INPUT_COLS chips */}
        <div className="space-y-3">
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium text-slate-400">
                INPUT_COLS (colonnes d&apos;entree)
              </label>
              <span className="text-[10px] text-slate-500">
                {inputCols.length} selectionnees
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {inputCols.map((col) => (
                <Chip
                  key={col}
                  label={col}
                  active
                  onClick={() => toggleInputCol(col)}
                  removable
                  onRemove={() => removeInputCol(col)}
                />
              ))}
              {/* Bouton Ajouter */}
              <div className="relative">
                <motion.button
                  type="button"
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setShowExtraDropdown(!showExtraDropdown)}
                  disabled={availableExtras.length === 0}
                  className={cn(
                    "inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
                    availableExtras.length > 0
                      ? "bg-cyan-500/10 text-cyan-300 border-cyan-500/30 hover:bg-cyan-500/20"
                      : "bg-slate-800/30 text-slate-600 border-slate-700/30 cursor-not-allowed"
                  )}
                >
                  <Plus size={12} />
                  Ajouter
                </motion.button>
                <AnimatePresence>
                  {showExtraDropdown && availableExtras.length > 0 && (
                    <motion.div
                      initial={{ opacity: 0, y: -4, scale: 0.95 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: -4, scale: 0.95 }}
                      className="absolute z-20 top-full mt-1 left-0 min-w-[220px] max-h-[240px] overflow-y-auto py-1 rounded-lg border border-slate-700/60 bg-slate-900/95 backdrop-blur-lg shadow-xl"
                    >
                      {availableExtras.map((col) => (
                        <button
                          key={col}
                          type="button"
                          onClick={() => {
                            addExtraCol(col);
                            setShowExtraDropdown(false);
                          }}
                          className="w-full text-left px-3 py-1.5 text-xs text-slate-300 hover:bg-indigo-500/10 hover:text-indigo-300 transition-colors"
                        >
                          {col}
                        </button>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </div>
          </div>

          {/* OUTPUT_COLS */}
          <div>
            <label className="text-xs font-medium text-slate-400 mb-1 block">
              OUTPUT_COLS (colonne cible)
            </label>
            <div className="px-3 py-2 rounded-lg bg-slate-800/60 border border-slate-700/60 text-xs text-indigo-300 font-mono">
              {outputCol}
            </div>
          </div>

          {/* Normalisation ON/OFF */}
          <div>
            <label className="text-xs font-medium text-slate-400 mb-2 block">
              Normalisation ON/OFF par feature
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {inputCols.map((col) => (
                <label
                  key={col}
                  className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-slate-800/40 border border-slate-700/30 cursor-pointer hover:border-slate-600/50 transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={onOffNorm[col] ?? true}
                    onChange={(e) =>
                      setOnOffNorm((n) => ({
                        ...n,
                        [col]: e.target.checked,
                      }))
                    }
                    className="w-3.5 h-3.5 rounded accent-indigo-500"
                  />
                  <span className="text-[11px] text-slate-300 truncate">
                    {col}
                  </span>
                </label>
              ))}
            </div>
          </div>
        </div>
      </Section>

      {/* ═══════════ Section 2 : Feature annee ═══════════ */}
      <Section
        title="Feature annee (optionnel)"
        icon={<Calendar size={16} className="text-cyan-400" />}
        defaultOpen={false}
      >
        <Toggle
          label="Activer l'entree Annee"
          checked={useYearFeature}
          onChange={setUseYearFeature}
        />

        <AnimatePresence>
          {useYearFeature && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden space-y-3"
            >
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">
                    Colonne contenant l&apos;annee
                  </label>
                  <input
                    type="text"
                    value={yearColumnName}
                    onChange={(e) => setYearColumnName(e.target.value)}
                    placeholder="Annee"
                    className="w-full px-3 py-2 text-sm bg-slate-800/60 border border-slate-700/60 rounded-lg text-slate-200 outline-none focus:border-indigo-500/50 transition-all"
                  />
                </div>
                <div className="flex items-end pb-2">
                  <Toggle
                    label="Normalisation de l'annee"
                    checked={yearNormalization}
                    onChange={setYearNormalization}
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-slate-400 mb-2 block">
                  Mapping annee → valeur
                </label>
                <div className="space-y-2">
                  {yearMapping.map((entry, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <input
                        type="text"
                        value={entry.year}
                        onChange={(e) => {
                          const copy = [...yearMapping];
                          copy[idx] = { ...copy[idx], year: e.target.value };
                          setYearMapping(copy);
                        }}
                        placeholder="2023"
                        className="w-24 px-2.5 py-1.5 text-xs bg-slate-800/60 border border-slate-700/60 rounded-lg text-slate-200 outline-none focus:border-indigo-500/50"
                      />
                      <span className="text-slate-500 text-xs">→</span>
                      <input
                        type="number"
                        value={entry.value}
                        onChange={(e) => {
                          const copy = [...yearMapping];
                          copy[idx] = {
                            ...copy[idx],
                            value: parseInt(e.target.value) || 0,
                          };
                          setYearMapping(copy);
                        }}
                        className="w-20 px-2.5 py-1.5 text-xs bg-slate-800/60 border border-slate-700/60 rounded-lg text-slate-200 outline-none focus:border-indigo-500/50"
                      />
                      <button
                        type="button"
                        onClick={() =>
                          setYearMapping((m) =>
                            m.filter((_, i) => i !== idx)
                          )
                        }
                        className="text-slate-500 hover:text-red-400 transition-colors"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  ))}
                  <button
                    type="button"
                    onClick={() =>
                      setYearMapping((m) => [
                        ...m,
                        { year: "", value: m.length + 1 },
                      ])
                    }
                    className="inline-flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300 transition-colors"
                  >
                    <Plus size={12} /> Ajouter une annee
                  </button>
                </div>
              </div>

              <p className="text-[10px] text-slate-500 italic">
                La feature &quot;year_mapped&quot; sera automatiquement ajoutee aux colonnes
                d&apos;entree du modele.
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </Section>

      {/* ═══════════ Section 3 : Colonnes obligatoires ═══════════ */}
      <Section
        title="Colonnes obligatoires grid search"
        icon={<Pin size={16} className="text-violet-400" />}
        defaultOpen
      >
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-slate-400 mb-2 block">
              Colonnes obligatoires (toujours presentes dans chaque
              combinaison) — cliquez sur × pour retirer, utilisez le menu pour
              ajouter
            </label>
            {/* Active mandatory cols with remove button */}
            <div className="flex flex-wrap gap-1.5 mb-2">
              {[...new Set(mandatoryCols)].map((col) => (
                <span
                  key={`mandatory-${col}`}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-violet-500/20 text-violet-300 border border-violet-500/30"
                >
                  {col}
                  <button
                    type="button"
                    onClick={() =>
                      setMandatoryCols((prev) =>
                        prev.filter((c) => c !== col)
                      )
                    }
                    className="ml-0.5 hover:text-red-400 transition-colors"
                  >
                    ×
                  </button>
                </span>
              ))}
              {mandatoryCols.length === 0 && (
                <span className="text-xs text-slate-600 italic">
                  Aucune colonne obligatoire
                </span>
              )}
            </div>
            {/* Dropdown to add from input_cols */}
            {(() => {
              const available = inputCols.filter(
                (c) => !mandatoryCols.includes(c)
              );
              if (available.length === 0) return null;
              return (
                <div className="relative inline-block">
                  <select
                    className="px-3 py-1.5 rounded-lg text-xs bg-slate-800/80 border border-white/[0.08] text-cyan-300 focus:outline-none focus:border-indigo-500/50 cursor-pointer appearance-none pr-7"
                    value=""
                    onChange={(e) => {
                      const val = e.target.value;
                      if (val) {
                        setMandatoryCols((prev) =>
                          prev.includes(val) ? prev : [...prev, val]
                        );
                      }
                    }}
                  >
                    <option value="" disabled>
                      + Ajouter une colonne obligatoire
                    </option>
                    {available.map((col) => (
                      <option key={col} value={col}>
                        {col}
                      </option>
                    ))}
                  </select>
                </div>
              );
            })()}
          </div>

          <NumberInput
            label="Nombre minimum d'entrees (min_input_count)"
            value={minInputCount}
            onChange={setMinInputCount}
            min={0}
            max={inputCols.length || 10}
            help={`Defaut ${isTv ? "TV" : "PL"} : ${isTv ? 3 : 2}. Vous pouvez mettre 0.`}
          />
        </div>
      </Section>

      {/* ═══════════ Section 4 : Hyperparametres ═══════════ */}
      <Section
        title="Hyperparametres grid search"
        icon={<Settings2 size={16} className="text-cyan-400" />}
        defaultOpen
      >
        <div className="space-y-4">
          {/* Activations */}
          <div>
            <label className="text-xs font-medium text-slate-400 mb-2 block">
              Fonctions d&apos;activation
            </label>
            <div className="flex flex-wrap gap-1.5">
              {ALL_ACTIVATIONS.map((act) => {
                const active = activations.includes(act);
                return (
                  <Chip
                    key={act}
                    label={act}
                    active={active}
                    onClick={() =>
                      setActivations((prev) =>
                        active
                          ? prev.filter((a) => a !== act)
                          : [...prev, act]
                      )
                    }
                  />
                );
              })}
            </div>
          </div>

          {/* Learning rates */}
          <div>
            <label className="text-xs font-medium text-slate-400 mb-1 block">
              Learning rates
            </label>
            <TagInput
              values={learningRates}
              onChange={setLearningRates}
              placeholder="0.01, 0.001..."
            />
          </div>

          {/* Losses */}
          <div>
            <label className="text-xs font-medium text-slate-400 mb-2 block">
              Fonctions de perte (loss)
            </label>
            <div className="flex flex-wrap gap-1.5">
              {ALL_LOSSES.map((loss) => {
                const active = losses.includes(loss);
                return (
                  <Chip
                    key={loss}
                    label={loss}
                    active={active}
                    onClick={() =>
                      setLosses((prev) =>
                        active
                          ? prev.filter((l) => l !== loss)
                          : [...prev, loss]
                      )
                    }
                  />
                );
              })}
            </div>
          </div>

          {/* Min epochs */}
          <div>
            <label className="text-xs font-medium text-slate-400 mb-1 block">
              Min. epoques / start_from_epoch
            </label>
            <TagInput
              values={minEpochs}
              onChange={setMinEpochs}
              placeholder="500, 1000, 2000..."
            />
            <p className="text-[10px] text-slate-500 mt-0.5">
              EarlyStopping ne demarre qu&apos;apres cette epoque.
            </p>
          </div>

          {/* Max epochs + Test size */}
          <div className="grid grid-cols-2 gap-4">
            <NumberInput
              label="Max. epoques"
              value={maxEpochs}
              onChange={setMaxEpochs}
              min={100}
              step={50}
            />
            <SliderInput
              label="Test size (fraction)"
              value={testSize}
              onChange={setTestSize}
              min={0.0}
              max={0.4}
              step={0.05}
              help="0.0 = pas de split test. 0.2 = 20% reserves pour test."
            />
          </div>
        </div>
      </Section>

      {/* ═══════════ Section 5 : Architecture reseau ═══════════ */}
      <Section
        title="Architecture du reseau"
        icon={<Brain size={16} className="text-violet-400" />}
        defaultOpen
      >
        <div className="space-y-4">
          {/* Neurons factors */}
          <div>
            <label className="text-xs font-medium text-slate-400 mb-2 block">
              Architectures (neurons_factors) — facteurs multiplicateurs de N
            </label>
            <p className="text-[10px] text-slate-500 mb-2">
              Chaque facteur multiplie N (= nombre de features) pour definir
              le nombre de neurones par couche. Ex: [2, 1, 0.5] → couches de
              2N, 1N, 0.5N neurones.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {PREDEFINED_ARCHS.map((arch) => {
                const active = selectedArchs.includes(arch);
                return (
                  <Chip
                    key={arch}
                    label={arch}
                    active={active}
                    onClick={() =>
                      setSelectedArchs((prev) =>
                        active
                          ? prev.filter((a) => a !== arch)
                          : [...prev, arch]
                      )
                    }
                  />
                );
              })}
            </div>
          </div>

          {/* Batch norm */}
          <Toggle
            label="Batch Normalization (BatchNorm apres chaque couche cachee)"
            checked={useBatchNorm}
            onChange={setUseBatchNorm}
          />

          {/* Dropouts + Batch sizes */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-slate-400 mb-1 block">
                Dropout(s)
              </label>
              <TagInput
                values={dropouts}
                onChange={setDropouts}
                placeholder="0.05, 0.1..."
              />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-400 mb-1 block">
                Batch size(s)
              </label>
              <TagInput
                values={batchSizes}
                onChange={setBatchSizes}
                placeholder="256, 128..."
              />
            </div>
          </div>
        </div>
      </Section>

      {/* ═══════════ Section 6 : Ponderation ═══════════ */}
      <Section
        title="Ponderation (optionnel)"
        icon={<Scale size={16} className="text-amber-400" />}
        defaultOpen={false}
      >
        <Toggle
          label="Activer ponderation flag_comptage"
          checked={useWeighting}
          onChange={setUseWeighting}
        />
        <AnimatePresence>
          {useWeighting && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <NumberInput
                label="Poids des capteurs permanents (flag=1)"
                value={flagWeight}
                onChange={setFlagWeight}
                min={0}
                step={0.5}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </Section>

      {/* ═══════════ Footer : compteur + bouton ═══════════ */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between pt-2"
      >
        <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 backdrop-blur-sm px-5 py-3 flex items-center gap-3">
          <Hash size={16} className="text-indigo-400" />
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wide">
              Total configurations
            </p>
            <motion.p
              key={combinationsCount}
              initial={{ scale: 1.2, color: "#818cf8" }}
              animate={{ scale: 1, color: "#c7d2fe" }}
              className="text-lg font-bold font-mono text-indigo-200"
            >
              {combinationsCount.toLocaleString("fr-FR")}
            </motion.p>
          </div>
        </div>

        <NeonButton
          type="button"
          icon={<Zap size={16} />}
          onClick={handleSubmit}
        >
          Sauvegarder &amp; Lancer l&apos;entrainement
        </NeonButton>
      </motion.div>
    </div>
  );
}
