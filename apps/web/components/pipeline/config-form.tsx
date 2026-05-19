"use client";

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import {
  ChevronDown,
  Layers,
  Settings2,
  Calendar,
  Pin,
  Brain,
  Scale,
  Plus,
  X,
  Hash,
  Zap,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { TagInput } from "@/components/ui/tag-input";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import type { AppMode } from "@/lib/store";

// ─── Constants TV (Etape1_MDL_TV refonte FCD HERE) ─────────────────────────
const DEFAULT_INPUT_COLS_TV = [
  "TMJOFCDTV",
  "TMJOFCDPL",
  "avg_distance_m",
  "avg_speed_kmh",
  "truck_avg_min_distance_m",
  "truck_avg_speed_kmh",
  "functional_class",
];
const EXTRA_INPUT_COLS_TV = [
  "TMJOBCTV_HPM",
  "TMJOBCTV_HPS",
  "avg_distance_before_m",
  "avg_distance_after_m",
  "avg_min_distance_m",
  "truck_avg_distance_m",
  "truck_avg_distance_before_m",
  "truck_avg_distance_after_m",
];

// ─── Constants PL ───────────────────────────────────────────────────────────
const DEFAULT_INPUT_COLS_PL = [
  "TMJOFCDPL",
  "avg_distance_m",
  "avg_speed_kmh",
  "truck_avg_min_distance_m",
  "truck_avg_speed_kmh",
  "functional_class",
];
const EXTRA_INPUT_COLS_PL = [
  "TMJOFCDTV",
  "avg_distance_before_m",
  "avg_distance_after_m",
  "truck_avg_distance_m",
  "truck_avg_distance_before_m",
  "truck_avg_distance_after_m",
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

// Rough average seconds per combination — used for the duration estimate in the
// resume panel. Calibrated against typical grid runs; purely indicative.
const SECONDS_PER_COMBINATION = 35;

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
  availableColumns?: string[];
  onSubmit: (config: TrainingConfig) => void;
}

// ─── Accordion section (custom, no radix) ────────────────────────────────
// Animates height via `auto` on open, using a measured inner ref.
function Section({
  id,
  title,
  icon,
  children,
  defaultOpen = true,
  badge,
}: {
  id: string;
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
  badge?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = `section-panel-${id}`;
  const btnId = `section-trigger-${id}`;
  return (
    <div className="surface-elevated overflow-hidden">
      <h3 className="m-0">
        <button
          id={btnId}
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((v) => !v)}
          className={cn(
            "w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-text",
            "hover:bg-bg-subtle/60 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          )}
        >
          <span className="flex items-center gap-2.5">
            <span className="text-accent [&_svg]:size-4">{icon}</span>
            {title}
            {badge && (
              <span className="ml-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-accent-subtle text-accent border border-accent/20 tabular-nums">
                {badge}
              </span>
            )}
          </span>
          <ChevronDown
            size={14}
            className={cn(
              "text-text-subtle transition-transform duration-200",
              open && "rotate-180"
            )}
            aria-hidden="true"
          />
        </button>
      </h3>
      <div
        id={panelId}
        role="region"
        aria-labelledby={btnId}
        hidden={!open}
        className={cn(
          "border-t border-border",
          open ? "block" : "hidden"
        )}
      >
        <div className="px-4 py-4 space-y-4">{children}</div>
      </div>
    </div>
  );
}

// ─── Chip toggle (sober) ────────────────────────────────────────────────────
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
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 h-7 rounded text-xs font-medium border transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        active
          ? "bg-accent-subtle text-accent border-accent/40"
          : "bg-bg-elevated text-text-muted border-border hover:border-border-strong hover:text-text"
      )}
    >
      {label}
      {removable && onRemove && (
        <span
          role="button"
          tabIndex={-1}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="ml-0.5 inline-flex items-center text-text-muted hover:text-danger cursor-pointer"
          aria-label={`Retirer ${label}`}
        >
          <X size={12} aria-hidden="true" />
        </span>
      )}
    </button>
  );
}

// ─── Toggle (switch) ────────────────────────────────────────────────────────
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
    <label className="flex items-center gap-2.5 cursor-pointer group select-none">
      <span className="relative inline-flex">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="sr-only peer"
        />
        <span className="w-8 h-[18px] rounded-full bg-bg-subtle peer-checked:bg-accent transition-colors" />
        <span
          className={cn(
            "absolute top-[2px] left-[2px] w-[14px] h-[14px] rounded-full bg-white shadow-sm transition-transform duration-200",
            checked && "translate-x-[14px]"
          )}
        />
      </span>
      <span className="text-xs text-text-muted group-hover:text-text transition-colors">
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
      <label className="text-xs font-medium text-text-muted">{label}</label>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        className={cn(
          "w-full px-3 h-9 text-sm bg-bg-elevated border border-border rounded text-text",
          "font-mono tabular-nums",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        )}
      />
      {help && <p className="text-[10px] text-text-subtle">{help}</p>}
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
        <label className="text-xs font-medium text-text-muted">{label}</label>
        <span className="text-xs font-mono tabular-nums text-accent bg-accent-subtle px-2 py-0.5 rounded">
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
        className="w-full h-1 rounded-full appearance-none bg-bg-subtle cursor-pointer accent-accent"
      />
      {help && <p className="text-[10px] text-text-subtle">{help}</p>}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// Main Form — 4 accordion sections + sticky resume panel
// ═══════════════════════════════════════════════════════════════════════════
export function ConfigForm({ mode, availableColumns, onSubmit }: ConfigFormProps) {
  const isTv = mode !== "pl";

  // ── Colonnes d'entree/sortie ─────────────────────────────────────────────
  const defaultCols = isTv ? DEFAULT_INPUT_COLS_TV : DEFAULT_INPUT_COLS_PL;
  const fallbackExtras = isTv ? EXTRA_INPUT_COLS_TV : EXTRA_INPUT_COLS_PL;

  const [inputCols, setInputCols] = useState<string[]>([...defaultCols]);
  const [onOffNorm, setOnOffNorm] = useState<Record<string, boolean>>(
    () => Object.fromEntries(defaultCols.map((c) => [c, true]))
  );
  const OUTPUT_OPTIONS = isTv
    ? ["TxPen", "TMJOBCTV"]
    : ["TxPenPL", "TMJOBCPL"];
  const [outputCols, setOutputCols] = useState<string[]>(
    isTv ? ["TxPen"] : ["TxPenPL"]
  );

  const allCandidates = availableColumns && availableColumns.length > 0
    ? availableColumns
    : [...defaultCols, ...fallbackExtras];
  const availableExtras = allCandidates.filter((c) => !inputCols.includes(c));

  const toggleInputCol = useCallback((col: string) => {
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
  }, []);

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

  // ── Feature annee ─────────────────────────────────────────────────────────
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

  // ── Colonnes obligatoires ────────────────────────────────────────────────
  const defaultMandatory = isTv
    ? ["TMJOFCDTV", "TMJOFCDPL"]
    : ["TMJOFCDPL"];
  const [mandatoryCols, setMandatoryCols] = useState<string[]>(
    defaultMandatory.filter((c) => defaultCols.includes(c))
  );
  const [minInputCount, setMinInputCount] = useState(isTv ? 3 : 2);

  // ── Hyperparametres (training) ───────────────────────────────────────────
  const [activations, setActivations] = useState<string[]>(["elu"]);
  const [learningRates, setLearningRates] = useState<string[]>(["0.01"]);
  const [losses, setLosses] = useState<string[]>(["mse"]);
  const [minEpochs, setMinEpochs] = useState<string[]>(["100", "200"]);
  const [maxEpochs, setMaxEpochs] = useState(500);
  const [testSize, setTestSize] = useState(0.0);

  // ── Architecture ─────────────────────────────────────────────────────────
  const [selectedArchs, setSelectedArchs] = useState<string[]>(["[1, 1]"]);
  const [useBatchNorm, setUseBatchNorm] = useState(false);
  const [dropouts, setDropouts] = useState<string[]>(["0.05"]);
  const [batchSizes, setBatchSizes] = useState<string[]>(["256"]);

  // ── Avance (seed, ponderation) ───────────────────────────────────────────
  const [seed, setSeed] = useState(1750);
  const [useWeighting, setUseWeighting] = useState(false);
  const [flagWeight, setFlagWeight] = useState(4.0);

  // ── Dropdown for extras ──────────────────────────────────────────────────
  const [showExtraDropdown, setShowExtraDropdown] = useState(false);
  const extraDropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    if (!showExtraDropdown) return;
    function onDocClick(e: MouseEvent) {
      if (
        extraDropdownRef.current &&
        !extraDropdownRef.current.contains(e.target as Node)
      ) {
        setShowExtraDropdown(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [showExtraDropdown]);

  // ── Compute combinations ─────────────────────────────────────────────────
  // Returns the breakdown so the resume panel can explain WHERE the total
  // comes from (feature_subsets × hyperparams) — avoids the "I configured 2
  // combos but got 8" surprise reported on Lyon.
  const combinationsBreakdown = useMemo(() => {
    const optionalCols = inputCols.filter((c) => !mandatoryCols.includes(c));
    const minOptional = Math.max(0, minInputCount - mandatoryCols.length);

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

    const nActivations = activations.length || 1;
    const nLr = learningRates.filter((v) => !isNaN(parseFloat(v))).length || 1;
    const nEpochs = minEpochs.filter((v) => !isNaN(parseInt(v, 10))).length || 1;
    const nLosses = losses.length || 1;
    const nDropouts = dropouts.filter((v) => !isNaN(parseFloat(v))).length || 1;
    const nArchs = selectedArchs.length || 1;
    const nBatch = batchSizes.filter((v) => !isNaN(parseInt(v, 10))).length || 1;

    const hyperparams =
      nActivations * nLr * nEpochs * nLosses * nDropouts * nArchs * nBatch;

    return {
      total: featureSets * hyperparams,
      featureSets,
      hyperparams,
    };
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

  const combinationsCount = combinationsBreakdown.total;

  // Estimated duration: combinations * SECONDS_PER_COMBINATION, formatted.
  const estimatedDuration = useMemo(() => {
    const totalSeconds = combinationsCount * SECONDS_PER_COMBINATION;
    if (totalSeconds < 60) return `~${totalSeconds}s`;
    const minutes = Math.round(totalSeconds / 60);
    if (minutes < 60) return `~${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const remMin = minutes % 60;
    return `~${hours}h${remMin > 0 ? ` ${remMin}min` : ""}`;
  }, [combinationsCount]);

  // ── Submit ───────────────────────────────────────────────────────────────
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

    const lrs = learningRates.map((v) => parseFloat(v)).filter((v) => !isNaN(v));
    const parsedLosses = losses.length > 0 ? losses : ["mse"];
    const eps = minEpochs.map((v) => parseInt(v, 10)).filter((v) => !isNaN(v));
    const drps = dropouts.map((v) => parseFloat(v)).filter((v) => !isNaN(v));
    const bss = batchSizes.map((v) => parseInt(v, 10)).filter((v) => !isNaN(v));
    const archs = selectedArchs.map((k) => ARCH_MAP[k] ?? [1.0, 1.0]);
    const parsedActivations = activations.length > 0 ? activations : ["elu"];

    const finalLrs = lrs.length > 0 ? lrs : [0.01];
    const finalEps = eps.length > 0 ? eps : [500];
    const finalDrps = drps.length > 0 ? drps : [0.05];
    const finalBss = bss.length > 0 ? bss : [256];
    const finalArchs = archs.length > 0 ? archs : [[1.0, 1.0]];

    const usedDefaults =
      lrs.length === 0 ||
      losses.length === 0 ||
      eps.length === 0 ||
      drps.length === 0 ||
      bss.length === 0 ||
      archs.length === 0 ||
      activations.length === 0;

    if (usedDefaults) {
      toast.warning("Certains champs vides ont ete completes avec les valeurs par defaut");
    }

    const config: TrainingConfig = {
      mode: "grid",
      model_type: isTv ? "TV" : "PL",
      input_cols: finalInputCols,
      output_cols: outputCols,
      on_off_norm: finalOnOff,
      use_year_feature: useYearFeature,
      year_column_name: useYearFeature ? yearColumnName : null,
      year_value_mapping: useYearFeature ? yearMappingObj : {},
      year_normalization: useYearFeature ? yearNormalization : false,
      mandatory_input_cols: mandatoryCols,
      min_input_count: minInputCount,
      feature_subset_grid: true,
      activations: parsedActivations,
      learning_rates: finalLrs,
      losses: parsedLosses,
      min_nb_epochs_list: finalEps,
      max_epochs: maxEpochs,
      test_size: testSize,
      neurons_factors_list: finalArchs,
      use_batch_norm: useBatchNorm,
      dropouts: finalDrps,
      batch_sizes: finalBss,
      use_flag_comptage_weighting: useWeighting,
      flag_comptage_col: "flag_comptage",
      flag_priority_weight: flagWeight,
      analysis_scope: "all",
      seed,
    };

    onSubmit(config);
  }, [
    inputCols,
    onOffNorm,
    outputCols,
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
    seed,
    isTv,
    onSubmit,
  ]);

  // Sync mandatory cols when input cols change
  useEffect(() => {
    setMandatoryCols((prev) => prev.filter((c) => inputCols.includes(c)));
  }, [inputCols]);

  // Auto-adjust minInputCount so it never goes below mandatoryCols.length
  useEffect(() => {
    const floor = mandatoryCols.length || 1;
    setMinInputCount((prev) => Math.max(prev, floor));
  }, [mandatoryCols]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
      {/* ═══════════ Left column — Accordion sections ═══════════ */}
      <div className="space-y-3 min-w-0">
        {/* ───── 1. Architecture ───── */}
        <Section
          id="architecture"
          title="Architecture"
          icon={<Brain />}
          defaultOpen
          badge={`${selectedArchs.length}`}
        >
          <div>
            <label className="text-xs font-medium text-text-muted mb-2 block">
              Architectures (neurons_factors) — facteurs multiplicateurs de N
            </label>
            <p className="text-[11px] text-text-subtle mb-2">
              Chaque facteur multiplie N (= nombre de features) pour definir le nombre
              de neurones par couche. Ex: [2, 1, 0.5] → couches de 2N, 1N, 0.5N neurones.
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
                        active ? prev.filter((a) => a !== arch) : [...prev, arch]
                      )
                    }
                  />
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-muted mb-2 block">
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
                          active ? prev.filter((a) => a !== act) : [...prev, act]
                        )
                      }
                    />
                  );
                })}
              </div>
            </div>

            <Toggle
              label="Batch Normalization (apres chaque couche cachee)"
              checked={useBatchNorm}
              onChange={setUseBatchNorm}
            />
          </div>

          <div>
            <label className="text-xs font-medium text-text-muted mb-1 block">
              Dropout(s)
            </label>
            <TagInput
              values={dropouts}
              onChange={setDropouts}
              placeholder="0.05, 0.1..."
            />
          </div>
        </Section>

        {/* ───── 2. Training ───── */}
        <Section
          id="training"
          title="Training"
          icon={<Settings2 />}
          defaultOpen
        >
          <div>
            <label className="text-xs font-medium text-text-muted mb-2 block">
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
                        active ? prev.filter((l) => l !== loss) : [...prev, loss]
                      )
                    }
                  />
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-muted mb-1 block">
                Learning rates
              </label>
              <TagInput
                values={learningRates}
                onChange={setLearningRates}
                placeholder="0.01, 0.001..."
              />
            </div>
            <div>
              <label className="text-xs font-medium text-text-muted mb-1 block">
                Batch size(s)
              </label>
              <TagInput
                values={batchSizes}
                onChange={setBatchSizes}
                placeholder="256, 128..."
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-text-muted mb-1 block">
              Min. epoques / start_from_epoch
            </label>
            <TagInput
              values={minEpochs}
              onChange={setMinEpochs}
              placeholder="500, 1000, 2000..."
            />
            <p className="text-[10px] text-text-subtle mt-0.5">
              EarlyStopping ne demarre qu&apos;apres cette epoque.
            </p>
          </div>

          <NumberInput
            label="Max. epoques"
            value={maxEpochs}
            onChange={setMaxEpochs}
            min={100}
            step={50}
          />
        </Section>

        {/* ───── 3. Feature subsets ───── */}
        <Section
          id="features"
          title="Feature subsets"
          icon={<Layers />}
          defaultOpen
          badge={`${inputCols.length}`}
        >
          {/* INPUT_COLS chips */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium text-text-muted">
                INPUT_COLS — colonnes d&apos;entree
              </label>
              <span className="text-[10px] text-text-subtle font-mono tabular-nums">
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
              <div className="relative" ref={extraDropdownRef}>
                <button
                  type="button"
                  onClick={() => setShowExtraDropdown((v) => !v)}
                  disabled={availableExtras.length === 0}
                  className={cn(
                    "inline-flex items-center gap-1 px-2.5 h-7 rounded text-xs font-medium border transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    availableExtras.length > 0
                      ? "bg-bg-elevated text-text-muted border-border hover:border-border-strong hover:text-text"
                      : "bg-bg-elevated text-text-subtle border-border opacity-50 cursor-not-allowed"
                  )}
                >
                  <Plus size={12} aria-hidden="true" />
                  Ajouter
                </button>
                {showExtraDropdown && availableExtras.length > 0 && (
                  <div className="absolute z-20 top-full mt-1 left-0 min-w-[220px] max-h-[240px] overflow-y-auto py-1 rounded-md border border-border bg-bg-elevated shadow-lg">
                    {availableExtras.map((col) => (
                      <button
                        key={col}
                        type="button"
                        onClick={() => {
                          addExtraCol(col);
                          setShowExtraDropdown(false);
                        }}
                        className="w-full text-left px-3 py-1.5 text-xs text-text hover:bg-bg-subtle font-mono"
                      >
                        {col}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* OUTPUT_COLS */}
          <div>
            <label className="text-xs font-medium text-text-muted mb-2 block">
              OUTPUT_COLS — colonne cible
            </label>
            <div className="flex flex-wrap gap-1.5">
              {OUTPUT_OPTIONS.map((col) => {
                const active = outputCols.includes(col);
                return (
                  <Chip
                    key={col}
                    label={col}
                    active={active}
                    onClick={() =>
                      setOutputCols((prev) => {
                        if (active) {
                          if (prev.length <= 1) return prev;
                          return prev.filter((c) => c !== col);
                        }
                        return [...prev, col];
                      })
                    }
                  />
                );
              })}
            </div>
            <p className="text-[10px] text-text-subtle mt-1">
              Selectionnez la ou les colonnes cibles. Au moins une requise.
            </p>
          </div>

          {/* Normalisation ON/OFF */}
          <div>
            <label className="text-xs font-medium text-text-muted mb-2 block">
              Normalisation ON/OFF par feature
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {inputCols.map((col) => (
                <label
                  key={col}
                  className="flex items-center gap-2 px-2.5 h-8 rounded border border-border bg-bg-elevated cursor-pointer hover:border-border-strong transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={onOffNorm[col] ?? true}
                    onChange={(e) =>
                      setOnOffNorm((n) => ({ ...n, [col]: e.target.checked }))
                    }
                    className="w-3.5 h-3.5 accent-accent"
                  />
                  <span className="text-[11px] text-text-muted truncate font-mono">
                    {col}
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* Mandatory columns */}
          <div className="pt-3 border-t border-border">
            <div className="flex items-center gap-2 mb-2">
              <Pin size={12} className="text-text-muted" aria-hidden="true" />
              <label className="text-xs font-medium text-text-muted">
                Colonnes obligatoires (toujours presentes dans chaque combinaison)
              </label>
            </div>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {[...new Set(mandatoryCols)].map((col) => (
                <span
                  key={`mandatory-${col}`}
                  className="inline-flex items-center gap-1 px-2.5 h-7 rounded text-xs font-medium font-mono bg-accent-subtle text-accent border border-accent/30"
                >
                  {col}
                  <button
                    type="button"
                    onClick={() =>
                      setMandatoryCols((prev) => prev.filter((c) => c !== col))
                    }
                    className="ml-0.5 text-accent hover:text-danger transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
                    aria-label={`Retirer ${col} des obligatoires`}
                  >
                    <X size={11} aria-hidden="true" />
                  </button>
                </span>
              ))}
              {mandatoryCols.length === 0 && (
                <span className="text-xs text-text-subtle italic">
                  Aucune colonne obligatoire
                </span>
              )}
            </div>
            {(() => {
              const available = inputCols.filter((c) => !mandatoryCols.includes(c));
              if (available.length === 0) return null;
              return (
                <select
                  className="px-3 h-8 rounded text-xs bg-bg-elevated border border-border text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent cursor-pointer font-mono"
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
              );
            })()}
          </div>

          {/* min_input_count */}
          <NumberInput
            label="Nombre minimum d'entrees (min_input_count)"
            value={minInputCount}
            onChange={setMinInputCount}
            min={mandatoryCols.length || 1}
            max={inputCols.length || 10}
            help={`Minimum = ${mandatoryCols.length || 1} (colonnes obligatoires). Defaut ${isTv ? "TV" : "PL"} : ${isTv ? 3 : 2}.`}
          />

          {/* Auto grid summary */}
          <div className="flex items-center gap-2 text-[11px] text-text-subtle pt-2 border-t border-border">
            <Hash size={11} aria-hidden="true" />
            <span>
              Grid de feature subsets active —{" "}
              <span className="text-text-muted font-mono tabular-nums">
                {(() => {
                  const optionalCols = inputCols.filter(
                    (c) => !mandatoryCols.includes(c)
                  );
                  const minOptional = Math.max(0, minInputCount - mandatoryCols.length);
                  function comb(n: number, k: number): number {
                    if (k > n || k < 0) return 0;
                    if (k === 0 || k === n) return 1;
                    let r = 1;
                    for (let i = 0; i < Math.min(k, n - k); i++) {
                      r = (r * (n - i)) / (i + 1);
                    }
                    return Math.round(r);
                  }
                  let s = 0;
                  for (let k = minOptional; k <= optionalCols.length; k++) {
                    s += comb(optionalCols.length, k);
                  }
                  return Math.max(s, 1).toLocaleString("fr-FR");
                })()}
              </span>{" "}
              sous-ensembles generes.
            </span>
          </div>
        </Section>

        {/* ───── 4. Avance ───── */}
        <Section
          id="advanced"
          title="Avance"
          icon={<Scale />}
          defaultOpen={false}
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <NumberInput
              label="Seed (reproductibilite)"
              value={seed}
              onChange={setSeed}
              min={0}
              step={1}
              help="Graine aleatoire pour numpy / TensorFlow."
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

          {/* Feature annee */}
          <div className="pt-3 border-t border-border space-y-3">
            <div className="flex items-center gap-2">
              <Calendar size={12} className="text-text-muted" aria-hidden="true" />
              <Toggle
                label="Activer l'entree Annee"
                checked={useYearFeature}
                onChange={setUseYearFeature}
              />
            </div>
            {useYearFeature && (
              <div className="space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <label className="text-xs font-medium text-text-muted">
                      Colonne contenant l&apos;annee
                    </label>
                    <input
                      type="text"
                      value={yearColumnName}
                      onChange={(e) => setYearColumnName(e.target.value)}
                      placeholder="Annee"
                      className="w-full px-3 h-9 text-sm bg-bg-elevated border border-border rounded text-text font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
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
                  <label className="text-xs font-medium text-text-muted mb-2 block">
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
                          className="w-24 px-2.5 h-8 text-xs bg-bg-elevated border border-border rounded text-text font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                        />
                        <span className="text-text-subtle text-xs">→</span>
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
                          className="w-20 px-2.5 h-8 text-xs bg-bg-elevated border border-border rounded text-text font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                        />
                        <button
                          type="button"
                          onClick={() =>
                            setYearMapping((m) => m.filter((_, i) => i !== idx))
                          }
                          className="text-text-subtle hover:text-danger transition-colors"
                          aria-label="Retirer cette annee"
                        >
                          <X size={14} aria-hidden="true" />
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
                      className="inline-flex items-center gap-1 text-xs text-accent hover:underline transition-colors"
                    >
                      <Plus size={12} aria-hidden="true" /> Ajouter une annee
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Ponderation */}
          <div className="pt-3 border-t border-border space-y-3">
            <Toggle
              label="Ponderation flag_comptage (capteurs permanents)"
              checked={useWeighting}
              onChange={setUseWeighting}
            />
            {useWeighting && (
              <NumberInput
                label="Poids des capteurs permanents (flag=1)"
                value={flagWeight}
                onChange={setFlagWeight}
                min={0}
                step={0.5}
              />
            )}
          </div>
        </Section>
      </div>

      {/* ═══════════ Right column — Sticky resume panel ═══════════ */}
      <aside
        className="lg:sticky lg:top-4 lg:self-start space-y-3"
        aria-label="Resume de la configuration"
      >
        <div className="surface-elevated p-4 space-y-4">
          <div className="space-y-1">
            <p className="text-[11px] uppercase tracking-wide text-text-muted">
              Resume
            </p>
            <p className="text-sm text-text">
              Grille pour le modele{" "}
              <span className="text-accent font-mono">{isTv ? "TV" : "PL"}</span>
            </p>
          </div>

          <div className="space-y-3">
            <div className="space-y-0.5">
              <p className="text-[10px] uppercase tracking-wide text-text-subtle">
                Combinaisons
              </p>
              <p
                className="font-mono text-2xl font-semibold tabular-nums text-text leading-none"
                aria-live="polite"
              >
                {combinationsCount.toLocaleString("fr-FR")}
              </p>
              {combinationsBreakdown.featureSets > 1 && (
                <p className="text-[10px] text-text-muted font-mono pt-1">
                  = {combinationsBreakdown.featureSets} sous-ensembles ×{" "}
                  {combinationsBreakdown.hyperparams} hyperparam
                </p>
              )}
              {combinationsCount >= 4 && (
                <p className="text-[10px] text-warning pt-1">
                  ⚠ {combinationsCount} modeles seront entraines en sequence
                </p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <p className="text-[10px] uppercase tracking-wide text-text-subtle">
                  Duree estimee
                </p>
                <p className="font-mono tabular-nums text-text-muted mt-0.5 flex items-center gap-1">
                  <Clock size={11} aria-hidden="true" />
                  {estimatedDuration}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-text-subtle">
                  Features
                </p>
                <p className="font-mono tabular-nums text-text-muted mt-0.5">
                  {inputCols.length}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-text-subtle">
                  Architectures
                </p>
                <p className="font-mono tabular-nums text-text-muted mt-0.5">
                  {selectedArchs.length || 1}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-text-subtle">
                  Activations
                </p>
                <p className="font-mono tabular-nums text-text-muted mt-0.5">
                  {activations.length || 1}
                </p>
              </div>
            </div>
          </div>

          <Button
            type="button"
            variant="primary"
            size="md"
            icon={<Zap size={14} />}
            onClick={handleSubmit}
            className="w-full"
          >
            Lancer le grid search
          </Button>

          <p className="text-[10px] text-text-subtle italic">
            La duree depend du materiel et de la taille du dataset — l&apos;estimation est indicative.
          </p>
        </div>
      </aside>
    </div>
  );
}
