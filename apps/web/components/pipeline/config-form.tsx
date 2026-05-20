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
  FlaskConical,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { TagInput } from "@/components/ui/tag-input";
import { Button } from "@/components/ui/button";
import { FieldInfo } from "@/components/ui/tooltip";
import { fieldTooltips } from "@/lib/sam/coaching-content";
import { toast } from "sonner";
import type { AppMode } from "@/lib/store";

// ─── Constants TV (Etape1_MDL_TV refonte FCD HERE) ─────────────────────────
// Defaults aligned with MDL_Lyon_TV_BEST (seed 1751, best-of-10) — 11 features
// at submit time (10 raw cols + year_mapped, appended via useYearFeature=true).
// Order in input_cols at submit ends up as: [10 raw cols, year_mapped], the
// year_mapped slot inheriting the `year_normalization` boolean (false here, so
// year is passed raw). The 10 raw cols all use z-scored normalization EXCEPT
// `functional_class` which is a categorical-like integer (raw).
const DEFAULT_INPUT_COLS_TV = [
  "TMJOFCDTV",
  "TMJOFCDPL",
  "functional_class",
  "avg_distance_before_m",
  "avg_distance_after_m",
  "avg_min_distance_m",
  "truck_avg_distance_m",
  "truck_avg_distance_before_m",
  "truck_avg_distance_after_m",
  "truck_avg_min_distance_m",
];
const EXTRA_INPUT_COLS_TV = [
  "TMJOBCTV_HPM",
  "TMJOBCTV_HPS",
  "avg_distance_m",
  "avg_speed_kmh",
  "truck_avg_speed_kmh",
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
const ALL_LOSSES = [
  "mse",
  "huber",
  "mae",
  "tolerance_aware",
  "pinball_p80",
] as const;

// ─── Phase 2A / 3 / 4 — Advanced ML knobs ───────────────────────────────────
const OPTIMIZER_OPTIONS = ["adam", "adamw"] as const;
const DROPOUT_SCHEDULE_OPTIONS = ["uniform", "decreasing"] as const;
const NORM_LAYER_OPTIONS = ["none", "batch", "layer"] as const;

type Optimizer = (typeof OPTIMIZER_OPTIONS)[number];
type DropoutSchedule = (typeof DROPOUT_SCHEDULE_OPTIONS)[number];
type NormLayer = (typeof NORM_LAYER_OPTIONS)[number];
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
  use_flag_permanent_weighting: boolean;
  flag_permanent_col: string;
  flag_priority_weight: number;
  use_flag_recent_year_weighting: boolean;
  recent_year_priority_weight: number;
  analysis_scope: string;
  seed: number;

  // ── Phase 2A / 3 / 4 — Régularisation et architecture avancée ──────────
  optimizer: Optimizer;
  weight_decay: number;
  use_skip_connection: boolean;
  dropout_schedule: DropoutSchedule;
  clipnorm: number | null;
  norm_layer: NormLayer;
  use_quantile_head: boolean;
  n_seeds: number;
  use_year_embedding: boolean;
  target_log_transform: boolean;
  use_curriculum: boolean;
  use_hard_example_mining: boolean;
  tta_iter: number;
  tta_noise_std: number;
  bootstrap_iter: number;
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
    <div className="surface-elevated overflow-visible">
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
  tooltipKey,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  tooltipKey?: keyof typeof fieldTooltips;
}) {
  const tip = tooltipKey ? fieldTooltips[tooltipKey] : undefined;
  return (
    <span className="inline-flex items-center gap-1.5">
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
      {tip && (
        <FieldInfo
          purpose={tip.purpose}
          recommendation={tip.recommendation}
          label={label}
        />
      )}
    </span>
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
  tooltipKey,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  help?: string;
  tooltipKey?: keyof typeof fieldTooltips;
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-text-muted flex items-center gap-1.5">
        <span>{label}</span>
        {tooltipKey && fieldTooltips[tooltipKey] && (
          <FieldInfo
            purpose={fieldTooltips[tooltipKey].purpose}
            recommendation={fieldTooltips[tooltipKey].recommendation}
            label={label}
          />
        )}
      </label>
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

// ─── Radio group (segmented) ────────────────────────────────────────────────
function RadioGroup<T extends string>({
  label,
  options,
  value,
  onChange,
  tooltipKey,
  help,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  tooltipKey?: keyof typeof fieldTooltips;
  help?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-text-muted flex items-center gap-1.5">
        <span>{label}</span>
        {tooltipKey && fieldTooltips[tooltipKey] && (
          <FieldInfo
            purpose={fieldTooltips[tooltipKey].purpose}
            recommendation={fieldTooltips[tooltipKey].recommendation}
            label={label}
          />
        )}
      </label>
      <div className="flex flex-wrap gap-1.5">
        {options.map((opt) => {
          const active = value === opt;
          return (
            <button
              key={opt}
              type="button"
              onClick={() => onChange(opt)}
              aria-pressed={active}
              className={cn(
                "inline-flex items-center gap-1.5 px-2.5 h-7 rounded text-xs font-medium border transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                active
                  ? "bg-accent-subtle text-accent border-accent/40"
                  : "bg-bg-elevated text-text-muted border-border hover:border-border-strong hover:text-text"
              )}
            >
              {opt}
            </button>
          );
        })}
      </div>
      {help && <p className="text-[10px] text-text-subtle">{help}</p>}
    </div>
  );
}

// ─── Optional number input (toggle null vs value) ───────────────────────────
function OptionalNumberInput({
  label,
  value,
  onChange,
  min,
  step = 1,
  help,
  tooltipKey,
  placeholder,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  min?: number;
  step?: number;
  help?: string;
  tooltipKey?: keyof typeof fieldTooltips;
  placeholder?: string;
}) {
  const enabled = value !== null;
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-text-muted flex items-center gap-1.5">
        <span>{label}</span>
        {tooltipKey && fieldTooltips[tooltipKey] && (
          <FieldInfo
            purpose={fieldTooltips[tooltipKey].purpose}
            recommendation={fieldTooltips[tooltipKey].recommendation}
            label={label}
          />
        )}
      </label>
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => onChange(e.target.checked ? 1 : null)}
            className="w-3.5 h-3.5 accent-accent"
          />
          <span className="text-[11px] text-text-muted">Activer</span>
        </label>
        <input
          type="number"
          value={value ?? ""}
          min={min}
          step={step}
          disabled={!enabled}
          placeholder={placeholder ?? "(désactivé)"}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") {
              onChange(null);
            } else {
              const v = parseFloat(raw);
              onChange(isNaN(v) ? null : v);
            }
          }}
          className={cn(
            "flex-1 px-3 h-9 text-sm bg-bg-elevated border border-border rounded text-text font-mono tabular-nums",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
            !enabled && "opacity-50"
          )}
        />
      </div>
      {help && <p className="text-[10px] text-text-subtle">{help}</p>}
    </div>
  );
}

// ─── Optional slider input (toggle null vs value, slider when enabled) ──────
function OptionalSliderInput({
  label,
  value,
  onChange,
  min,
  max,
  step,
  defaultValue,
  help,
  tooltipKey,
  format,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  min: number;
  max: number;
  step: number;
  defaultValue: number;
  help?: string;
  tooltipKey?: keyof typeof fieldTooltips;
  format?: (v: number) => string;
}) {
  const enabled = value !== null;
  const displayed = enabled ? (value as number) : defaultValue;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <label className="text-xs font-medium text-text-muted flex items-center gap-1.5 min-w-0">
          <span className="truncate">{label}</span>
          {tooltipKey && fieldTooltips[tooltipKey] && (
            <FieldInfo
              purpose={fieldTooltips[tooltipKey].purpose}
              recommendation={fieldTooltips[tooltipKey].recommendation}
              label={label}
            />
          )}
        </label>
        <span
          className={cn(
            "text-xs font-mono tabular-nums px-2 py-0.5 rounded shrink-0",
            enabled
              ? "text-accent bg-accent-subtle"
              : "text-text-subtle bg-bg-subtle"
          )}
        >
          {enabled
            ? format
              ? format(displayed)
              : displayed.toFixed(2)
            : "désactivé"}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1.5 cursor-pointer select-none shrink-0">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => onChange(e.target.checked ? defaultValue : null)}
            className="w-3.5 h-3.5 accent-accent"
          />
          <span className="text-[11px] text-text-muted">Activer</span>
        </label>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={displayed}
          disabled={!enabled}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className={cn(
            "flex-1 h-1 rounded-full appearance-none bg-bg-subtle cursor-pointer accent-accent",
            !enabled && "opacity-40 cursor-not-allowed"
          )}
        />
      </div>
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
  tooltipKey,
  format,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  help?: string;
  tooltipKey?: keyof typeof fieldTooltips;
  format?: (v: number) => string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-xs font-medium text-text-muted flex items-center gap-1.5">
          <span>{label}</span>
          {tooltipKey && fieldTooltips[tooltipKey] && (
            <FieldInfo
              purpose={fieldTooltips[tooltipKey].purpose}
              recommendation={fieldTooltips[tooltipKey].recommendation}
              label={label}
            />
          )}
        </label>
        <span className="text-xs font-mono tabular-nums text-accent bg-accent-subtle px-2 py-0.5 rounded">
          {format ? format(value) : value.toFixed(2)}
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

// ─── ML advanced — group + card helpers (clean spacing & no overlap) ───────
function MlGroup({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2 pt-3 first:pt-0 first:border-0 border-t border-border">
      <h4 className="text-[11px] uppercase tracking-wide text-text-muted font-semibold">
        {title}
      </h4>
      {hint && (
        <p className="text-[11px] text-text-subtle leading-snug">{hint}</p>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">{children}</div>
    </div>
  );
}

function MlCard({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-md border border-border bg-bg-elevated/60 p-3 min-w-0",
        className
      )}
    >
      {children}
    </div>
  );
}

// Variant of <Toggle> that lays out as a full row (label left, switch right)
// — better for grid cells where the label needs to wrap.
function ToggleRow({
  label,
  checked,
  onChange,
  tooltipKey,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  tooltipKey?: keyof typeof fieldTooltips;
}) {
  const tip = tooltipKey ? fieldTooltips[tooltipKey] : undefined;
  return (
    <label className="flex items-center justify-between gap-3 cursor-pointer group select-none min-w-0">
      <span className="flex items-center gap-1.5 text-xs text-text-muted group-hover:text-text transition-colors min-w-0">
        <span className="min-w-0 break-words">{label}</span>
        {tip && (
          <FieldInfo
            purpose={tip.purpose}
            recommendation={tip.recommendation}
            label={label}
          />
        )}
      </span>
      <span className="relative inline-flex shrink-0">
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
    </label>
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
  // MDL_Lyon_TV_BEST default: every raw feature is z-scored EXCEPT
  // `functional_class` which is treated as a categorical integer (raw).
  // `year_mapped` is appended at submit time with its own norm flag
  // (`yearNormalization`, default false → raw year).
  const [onOffNorm, setOnOffNorm] = useState<Record<string, boolean>>(
    () =>
      Object.fromEntries(
        defaultCols.map((c) => [c, c !== "functional_class"])
      )
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
  // MDL_Lyon_TV_BEST uses year_mapped as the 11th input feature with raw
  // (non-normalized) values 1/2/3 for 2023/2024/2025. Default ON so the form
  // mirrors the production configuration; the column is appended to input_cols
  // at submit time with on_off_norm[year_mapped] = yearNormalization (false).
  const [useYearFeature, setUseYearFeature] = useState(true);
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
  // MDL_Lyon_TV_BEST default: no mandatory columns, min_input_count = 0.
  // Combined with feature_subset_grid = false below, the form submits a single
  // combination using exactly the selected input_cols (no Cartesian explosion).
  const defaultMandatory: string[] = isTv ? [] : [];
  const [mandatoryCols, setMandatoryCols] = useState<string[]>(
    defaultMandatory.filter((c) => defaultCols.includes(c))
  );
  const [minInputCount, setMinInputCount] = useState(0);

  // ── Hyperparametres (training) ───────────────────────────────────────────
  // Defaults reflect MDL_Lyon_TV_BEST (best of 10 seeds, seed 1751) — the
  // production-validated configuration. User can still override any value.
  const [activations, setActivations] = useState<string[]>(["elu"]);
  const [learningRates, setLearningRates] = useState<string[]>(["0.01"]);
  const [losses, setLosses] = useState<string[]>(["mse"]);
  const [minEpochs, setMinEpochs] = useState<string[]>(["1250"]);
  const [maxEpochs, setMaxEpochs] = useState(1250);
  const [testSize, setTestSize] = useState(0.0);

  // ── Architecture ─────────────────────────────────────────────────────────
  // Neurons factors [3.0, 2.0, 1.0] = the "[3, 2, 1]" preset (3 hidden layers
  // of 3N / 2N / 1N neurons where N is the feature count).
  const [selectedArchs, setSelectedArchs] = useState<string[]>(["[3, 2, 1]"]);
  const [useBatchNorm, setUseBatchNorm] = useState(false);
  const [dropouts, setDropouts] = useState<string[]>(["0.025"]);
  const [batchSizes, setBatchSizes] = useState<string[]>(["256"]);

  // ── Avance (seed, ponderation) ───────────────────────────────────────────
  // Seed 1751 = the winning seed identified by the best-of-10 sweep on Lyon TV.
  // Permanent weighting ON with weight 2.0 was part of the validated config.
  const [seed, setSeed] = useState(1751);
  const [useWeighting, setUseWeighting] = useState(true);
  const [flagWeight, setFlagWeight] = useState(2.0);
  const [useRecentYearWeighting, setUseRecentYearWeighting] = useState(false);
  const [recentYearWeight, setRecentYearWeight] = useState(2.0);

  // ── Phase 2A / 3 / 4 — Régularisation et architecture avancée ──────────
  // Defaults match types.py ModelTypeConfig.default_* so a user who never
  // opens this section gets byte-identical behaviour to before the refonte.
  const [optimizer, setOptimizer] = useState<Optimizer>("adam");
  const [weightDecay, setWeightDecay] = useState(0);
  const [useSkipConnection, setUseSkipConnection] = useState(false);
  const [dropoutSchedule, setDropoutSchedule] =
    useState<DropoutSchedule>("uniform");
  const [clipnorm, setClipnorm] = useState<number | null>(null);
  const [normLayer, setNormLayer] = useState<NormLayer>("none");
  const [useQuantileHead, setUseQuantileHead] = useState(false);
  const [nSeeds, setNSeeds] = useState(1);
  const [useYearEmbedding, setUseYearEmbedding] = useState(false);
  const [targetLogTransform, setTargetLogTransform] = useState(false);
  const [useCurriculum, setUseCurriculum] = useState(false);
  const [useHardExampleMining, setUseHardExampleMining] = useState(false);
  const [ttaIter, setTtaIter] = useState(1);
  const [ttaNoiseStd, setTtaNoiseStd] = useState(0.01);
  // bootstrap_iter: 0 (disabled) or 100..10000. Default 1000 matches the
  // evaluation router default (apps/api/app/routers/evaluation.py).
  const [bootstrapIter, setBootstrapIter] = useState(1000);

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
  // Note: feature_subset_grid is hardcoded to false at submit (MDL_Lyon_TV_BEST
  // default = single combo, no Cartesian explosion). Keep featureSets = 1 here
  // so the resume panel matches what the backend will receive.
  const combinationsBreakdown = useMemo(() => {
    const featureSets = 1;

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
      // MDL_Lyon_TV_BEST default: single combination, no Cartesian explosion
      // over feature subsets. User can still build a grid by adjusting
      // mandatory_input_cols / min_input_count, but the default trains exactly
      // the selected input_cols once.
      feature_subset_grid: false,
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
      use_flag_permanent_weighting: useWeighting,
      flag_permanent_col: "flag_permanent",
      flag_priority_weight: flagWeight,
      use_flag_recent_year_weighting: useRecentYearWeighting,
      recent_year_priority_weight: recentYearWeight,
      analysis_scope: "all",
      seed,
      // ── Phase 2A / 3 / 4 — propagated to TrainingConfig backend
      // (model_config = {"extra": "allow"}) so unknown fields are accepted.
      optimizer,
      weight_decay: weightDecay,
      use_skip_connection: useSkipConnection,
      dropout_schedule: dropoutSchedule,
      clipnorm,
      norm_layer: normLayer,
      use_quantile_head: useQuantileHead,
      n_seeds: nSeeds,
      use_year_embedding: useYearEmbedding,
      target_log_transform: targetLogTransform,
      use_curriculum: useCurriculum,
      use_hard_example_mining: useHardExampleMining,
      tta_iter: ttaIter,
      tta_noise_std: ttaNoiseStd,
      bootstrap_iter: bootstrapIter,
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
    useRecentYearWeighting,
    recentYearWeight,
    seed,
    isTv,
    onSubmit,
    optimizer,
    weightDecay,
    useSkipConnection,
    dropoutSchedule,
    clipnorm,
    normLayer,
    useQuantileHead,
    nSeeds,
    useYearEmbedding,
    targetLogTransform,
    useCurriculum,
    useHardExampleMining,
    ttaIter,
    ttaNoiseStd,
    bootstrapIter,
  ]);

  // Sync mandatory cols when input cols change
  useEffect(() => {
    setMandatoryCols((prev) => prev.filter((c) => inputCols.includes(c)));
  }, [inputCols]);

  // Auto-adjust minInputCount so it never goes below mandatoryCols.length.
  // (0 is a valid value when no mandatory cols are set — matches the
  // MDL_Lyon_TV_BEST default of "no feature subset grid, no minimum".)
  useEffect(() => {
    const floor = mandatoryCols.length;
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
            <label className="text-xs font-medium text-text-muted mb-2 flex items-center gap-1.5">
              <span>
                Architectures (neurons_factors) — facteurs multiplicateurs de N
              </span>
              <FieldInfo
                purpose={fieldTooltips.neurons_factors.purpose}
                recommendation={fieldTooltips.neurons_factors.recommendation}
                label="Architectures"
              />
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
              <label className="text-xs font-medium text-text-muted mb-2 flex items-center gap-1.5">
                <span>Fonctions d&apos;activation</span>
                <FieldInfo
                  purpose={fieldTooltips.activations.purpose}
                  recommendation={fieldTooltips.activations.recommendation}
                  label="Activations"
                />
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
              tooltipKey="use_batch_norm"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-text-muted mb-1 flex items-center gap-1.5">
              <span>Dropout(s)</span>
              <FieldInfo
                purpose={fieldTooltips.dropouts.purpose}
                recommendation={fieldTooltips.dropouts.recommendation}
                label="Dropouts"
              />
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
            <label className="text-xs font-medium text-text-muted mb-2 flex items-center gap-1.5">
              <span>Fonctions de perte (loss)</span>
              <FieldInfo
                purpose={fieldTooltips.losses.purpose}
                recommendation={fieldTooltips.losses.recommendation}
                label="Losses"
              />
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
              <label className="text-xs font-medium text-text-muted mb-1 flex items-center gap-1.5">
                <span>Learning rates</span>
                <FieldInfo
                  purpose={fieldTooltips.learning_rates.purpose}
                  recommendation={fieldTooltips.learning_rates.recommendation}
                  label="Learning rates"
                />
              </label>
              <TagInput
                values={learningRates}
                onChange={setLearningRates}
                placeholder="0.01, 0.001..."
              />
            </div>
            <div>
              <label className="text-xs font-medium text-text-muted mb-1 flex items-center gap-1.5">
                <span>Batch size(s)</span>
                <FieldInfo
                  purpose={fieldTooltips.batch_sizes.purpose}
                  recommendation={fieldTooltips.batch_sizes.recommendation}
                  label="Batch sizes"
                />
              </label>
              <TagInput
                values={batchSizes}
                onChange={setBatchSizes}
                placeholder="256, 128..."
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-text-muted mb-1 flex items-center gap-1.5">
              <span>Min. epoques / start_from_epoch</span>
              <FieldInfo
                purpose={fieldTooltips.min_nb_epochs_list.purpose}
                recommendation={fieldTooltips.min_nb_epochs_list.recommendation}
                label="Min epochs"
              />
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
            tooltipKey="max_epochs"
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
              <label className="text-xs font-medium text-text-muted flex items-center gap-1.5">
                <span>INPUT_COLS — colonnes d&apos;entree</span>
                <FieldInfo
                  purpose={fieldTooltips.input_cols.purpose}
                  recommendation={fieldTooltips.input_cols.recommendation}
                  label="Input cols"
                />
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
            <label className="text-xs font-medium text-text-muted mb-2 flex items-center gap-1.5">
              <span>OUTPUT_COLS — colonne cible</span>
              <FieldInfo
                purpose={fieldTooltips.output_cols.purpose}
                recommendation={fieldTooltips.output_cols.recommendation}
                label="Output cols"
              />
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
            <label className="text-xs font-medium text-text-muted mb-2 flex items-center gap-1.5">
              <span>Normalisation ON/OFF par feature</span>
              <FieldInfo
                purpose={fieldTooltips.on_off_norm.purpose}
                recommendation={fieldTooltips.on_off_norm.recommendation}
                label="Normalisation"
              />
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
              <label className="text-xs font-medium text-text-muted flex items-center gap-1.5">
                <span>
                  Colonnes obligatoires (toujours presentes dans chaque combinaison)
                </span>
                <FieldInfo
                  purpose={fieldTooltips.mandatory_input_cols.purpose}
                  recommendation={
                    fieldTooltips.mandatory_input_cols.recommendation
                  }
                  label="Colonnes obligatoires"
                />
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
            min={mandatoryCols.length}
            max={inputCols.length || 10}
            help={`Minimum = ${mandatoryCols.length} (colonnes obligatoires). Defaut MDL_Lyon_TV_BEST : 0 (pas de grille de sous-ensembles).`}
            tooltipKey="min_input_count"
          />

          {/* Auto grid summary — feature_subset_grid is off by default
              (MDL_Lyon_TV_BEST). The form trains exactly the selected
              input_cols once; no Cartesian explosion over feature subsets. */}
          <div className="flex items-center gap-2 text-[11px] text-text-subtle pt-2 border-t border-border">
            <Hash size={11} aria-hidden="true" />
            <span>
              Grille de feature subsets <span className="font-mono">désactivée</span>{" "}
              — l&apos;entraînement utilise exactement les{" "}
              <span className="text-text-muted font-mono tabular-nums">
                {inputCols.length}
              </span>{" "}
              colonne(s) sélectionnée(s) en une seule combinaison.
            </span>
          </div>
        </Section>

        {/* ───── 4. Avance ───── */}
        <Section
          id="advanced"
          title="Paramètres Avancés"
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
              tooltipKey="seed"
            />
            <SliderInput
              label="Test size (fraction)"
              value={testSize}
              onChange={setTestSize}
              min={0.0}
              max={0.4}
              step={0.05}
              help="0.0 = pas de split test. 0.2 = 20% reserves pour test."
              tooltipKey="test_size"
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
                tooltipKey="use_year_feature"
              />
            </div>
            {useYearFeature && (
              <div className="space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <label className="text-xs font-medium text-text-muted flex items-center gap-1.5">
                      <span>Colonne contenant l&apos;annee</span>
                      <FieldInfo
                        purpose={fieldTooltips.year_column_name.purpose}
                        recommendation={
                          fieldTooltips.year_column_name.recommendation
                        }
                        label="Colonne annee"
                      />
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
                      tooltipKey="year_normalization"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-xs font-medium text-text-muted mb-2 flex items-center gap-1.5">
                    <span>Mapping annee → valeur</span>
                    <FieldInfo
                      purpose={fieldTooltips.year_value_mapping.purpose}
                      recommendation={
                        fieldTooltips.year_value_mapping.recommendation
                      }
                      label="Mapping annee"
                    />
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
              label="Pondération capteurs permanents"
              checked={useWeighting}
              onChange={setUseWeighting}
              tooltipKey="flag_permanent_weighting"
            />
            {useWeighting && (
              <NumberInput
                label="Poids des capteurs permanents (Permanent / Siredo)"
                value={flagWeight}
                onChange={setFlagWeight}
                min={0}
                step={0.5}
                tooltipKey="flag_priority_weight"
              />
            )}
            <Toggle
              label="Pondération année la plus récente"
              checked={useRecentYearWeighting}
              onChange={setUseRecentYearWeighting}
              tooltipKey="flag_recent_year_weighting"
            />
            {useRecentYearWeighting && (
              <SliderInput
                label="Poids année la plus récente"
                value={recentYearWeight}
                onChange={setRecentYearWeight}
                min={1.0}
                max={5.0}
                step={0.1}
                format={(v) => v.toFixed(1)}
                help="Multiplie le poids des lignes correspondant à l'année la plus récente du dataset."
                tooltipKey="recent_year_priority_weight"
              />
            )}
          </div>
        </Section>

        {/* ───── 5. Phase 2A / 3 / 4 — Régularisation et architecture ML ───── */}
        <Section
          id="ml-advanced"
          title="Paramètres Machine Learning Avancés"
          icon={<FlaskConical />}
          defaultOpen={false}
          badge="Phase 2A/3/4"
        >
          <p className="text-[11px] text-text-subtle">
            Drapeaux additifs introduits par les Phases 2A / 3 / 4 du pipeline.
            Tous les défauts ci-dessous préservent le comportement antérieur :
            laissés tels quels, l&apos;entraînement est bit-identique à la
            version Phase 0-1.
          </p>

          {/* Groupe : Optimiseur & régularisation */}
          <MlGroup title="Optimiseur & régularisation">
            <MlCard>
              <RadioGroup
                label="Optimiseur"
                options={OPTIMIZER_OPTIONS}
                value={optimizer}
                onChange={setOptimizer}
                tooltipKey="optimizer"
              />
            </MlCard>
            <MlCard>
              <SliderInput
                label="Weight decay (L2 découplée)"
                value={weightDecay}
                onChange={setWeightDecay}
                min={0}
                max={0.01}
                step={0.0001}
                format={(v) => v.toExponential(1)}
                help="Ignoré si optimiseur = adam. Plage 0..1e-2."
                tooltipKey="weight_decay"
              />
            </MlCard>
            <MlCard>
              <OptionalSliderInput
                label="Gradient clipnorm"
                value={clipnorm}
                onChange={setClipnorm}
                min={0.1}
                max={5.0}
                step={0.1}
                defaultValue={1.0}
                format={(v) => v.toFixed(1)}
                help="Plafonne la norme du gradient. Plage 0.1..5.0."
                tooltipKey="clipnorm"
              />
            </MlCard>
            <MlCard>
              <RadioGroup
                label="Couche de normalisation"
                options={NORM_LAYER_OPTIONS}
                value={normLayer}
                onChange={setNormLayer}
                tooltipKey="norm_layer"
                help="`none` = legacy use_batch_norm pilote le comportement."
              />
            </MlCard>
          </MlGroup>

          {/* Groupe : Architecture */}
          <MlGroup title="Architecture">
            <MlCard>
              <ToggleRow
                label="Skip connection (entrée → dernière couche)"
                checked={useSkipConnection}
                onChange={setUseSkipConnection}
                tooltipKey="use_skip_connection"
              />
            </MlCard>
            <MlCard>
              <RadioGroup
                label="Schéma de dropout"
                options={DROPOUT_SCHEDULE_OPTIONS}
                value={dropoutSchedule}
                onChange={setDropoutSchedule}
                tooltipKey="dropout_schedule"
              />
            </MlCard>
            <MlCard>
              <ToggleRow
                label="Tête multi-quantile (q=0.2/0.5/0.8)"
                checked={useQuantileHead}
                onChange={setUseQuantileHead}
                tooltipKey="use_quantile_head"
              />
            </MlCard>
            <MlCard>
              <ToggleRow
                label="Embedding catégoriel pour l'année"
                checked={useYearEmbedding}
                onChange={setUseYearEmbedding}
                tooltipKey="use_year_embedding"
              />
            </MlCard>
          </MlGroup>

          {/* Groupe : Stratégie d'entraînement */}
          <MlGroup title="Stratégie d'entraînement">
            <MlCard>
              <SliderInput
                label="Nombre de seeds par combinaison (n_seeds)"
                value={nSeeds}
                onChange={(v) => setNSeeds(Math.round(v))}
                min={1}
                max={10}
                step={1}
                format={(v) => `${Math.round(v)}`}
                help="1 = comportement legacy. 3-5 mesure la variance."
                tooltipKey="n_seeds"
              />
            </MlCard>
            <MlCard>
              <ToggleRow
                label="log1p sur la cible (target_log_transform)"
                checked={targetLogTransform}
                onChange={setTargetLogTransform}
                tooltipKey="target_log_transform"
              />
            </MlCard>
            <MlCard>
              <ToggleRow
                label="Apprentissage curriculaire (faible → fort débit)"
                checked={useCurriculum}
                onChange={setUseCurriculum}
                tooltipKey="use_curriculum"
              />
            </MlCard>
            <MlCard>
              <ToggleRow
                label="Hard example mining (boost erreurs > 15 %)"
                checked={useHardExampleMining}
                onChange={setUseHardExampleMining}
                tooltipKey="use_hard_example_mining"
              />
            </MlCard>
          </MlGroup>

          {/* Groupe : Évaluation (TTA & bootstrap) */}
          <MlGroup
            title="Évaluation (TTA & bootstrap)"
            hint="Paramètres appliqués au moment de l'évaluation. Conservés ici pour limiter le va-et-vient entre les étapes Configuration et Évaluation."
          >
            <MlCard>
              <SliderInput
                label="TTA — itérations"
                value={ttaIter}
                onChange={(v) => setTtaIter(Math.round(v))}
                min={1}
                max={20}
                step={1}
                format={(v) => `${Math.round(v)}`}
                help="1 = pas de TTA. > 1 = moyenne sur N passes bruitées."
                tooltipKey="tta_iter"
              />
            </MlCard>
            <MlCard>
              <SliderInput
                label="TTA — écart-type du bruit"
                value={ttaNoiseStd}
                onChange={setTtaNoiseStd}
                min={0}
                max={0.1}
                step={0.005}
                format={(v) => v.toFixed(3)}
                help="Bruit gaussien sur les features normalisées."
                tooltipKey="tta_noise_std"
              />
            </MlCard>
            <MlCard className="lg:col-span-2">
              <SliderInput
                label="Bootstrap CI95 — nombre d'itérations"
                value={bootstrapIter}
                onChange={(v) => {
                  const rounded = Math.round(v / 100) * 100;
                  setBootstrapIter(Math.max(0, rounded));
                }}
                min={0}
                max={10000}
                step={100}
                format={(v) =>
                  v === 0 ? "désactivé" : v.toLocaleString("fr-FR")
                }
                help="0 = désactivé. Sinon plage valide : 100..10000 (pas de 100)."
                tooltipKey="bootstrap_iter"
              />
              {bootstrapIter !== 0 && bootstrapIter < 100 && (
                <p className="text-[10px] text-warning mt-1">
                  ⚠ Valeur invalide — utilisez 0 (désactivé) ou ≥ 100.
                </p>
              )}
            </MlCard>
          </MlGroup>
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
