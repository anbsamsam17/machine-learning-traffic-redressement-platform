// ---------------------------------------------------------------------------
// Carte — Column mapping definitions & helpers
// ---------------------------------------------------------------------------
// Extrait du fichier app/carte/page.tsx pour reduire le poids du composant.
// La liste REQUIRED_COLUMNS sert de fallback quand un modele ne fournit pas
// son training_config (back-compat avec les anciens modeles).
// ---------------------------------------------------------------------------

import type { ColumnDef } from "@/lib/carte/types";

export const REQUIRED_COLUMNS: ColumnDef[] = [
  { key: "TMJOFCDTV", label: "TMJOFCDTV", description: "Debit FCD VL (vehicules/jour)", required: true },
  { key: "TMJOFCDPL", label: "TMJOFCDPL", description: "Debit FCD PL (vehicules/jour)", required: true },
  { key: "functional_class", label: "functional_class", description: "Classe fonctionnelle HERE (1-5)", required: true },
  { key: "annee", label: "annee", description: "Annee de la donnee", required: true },
  { key: "avg_speed_kmh", label: "avg_speed_kmh", description: "Vitesse moyenne VL (km/h)", required: true },
  { key: "truck_avg_speed_kmh", label: "truck_avg_speed_kmh", description: "Vitesse moyenne PL (km/h)", required: true },
  { key: "avg_distance_m", label: "avg_distance_m", description: "Distance moyenne trajet VL (metres)", required: true },
  { key: "truck_avg_min_distance_m", label: "truck_avg_min_distance_m", description: "Distance min moyenne PL (metres)", required: true },
  { key: "AgregId", label: "AgregId", description: "Identifiant unique du segment HERE", required: false },
  { key: "avg_min_distance_m", label: "avg_min_distance_m", description: "Distance min moyenne VL (metres)", required: false },
  { key: "avg_distance_before_m", label: "avg_distance_before_m", description: "Trajet VL avant le segment (metres)", required: false },
  { key: "avg_distance_after_m", label: "avg_distance_after_m", description: "Trajet VL apres le segment (metres)", required: false },
  { key: "truck_avg_distance_m", label: "truck_avg_distance_m", description: "Distance moyenne PL (metres)", required: false },
  { key: "truck_avg_distance_before_m", label: "truck_avg_distance_before_m", description: "Trajet PL avant le segment (metres)", required: false },
  { key: "truck_avg_distance_after_m", label: "truck_avg_distance_after_m", description: "Trajet PL apres le segment (metres)", required: false },
  { key: "HD", label: "HD", description: "Heading (cap moyen 0-359°), depuis FCDREFGLOBAL", required: false },
  { key: "DIR_TRAVEL", label: "DIR_TRAVEL", description: "Direction circulation F/T/B (DD sera calcule : True si B)", required: false },
];

// Catalogue of descriptions/labels for the dynamic mapping. If a model
// declares a target column we don't know, we still render it with a sensible
// generic description.
export const COLUMN_METADATA: Record<string, { label: string; description: string }> = {
  // === Canonical names (aligned with BCFCDREF_AllYears_TV.geojson reference) ===
  TMJOFCDTV: { label: "TMJOFCDTV", description: "Debit FCD VL (vehicules/jour)" },
  TMJOFCDPL: { label: "TMJOFCDPL", description: "Debit FCD PL (vehicules/jour)" },
  functional_class: { label: "functional_class", description: "Classe fonctionnelle HERE (1-5)" },
  annee: { label: "annee", description: "Annee de la donnee" },
  avg_speed_kmh: { label: "avg_speed_kmh", description: "Vitesse moyenne VL (km/h)" },
  truck_avg_speed_kmh: { label: "truck_avg_speed_kmh", description: "Vitesse moyenne PL (km/h)" },
  avg_distance_m: { label: "avg_distance_m", description: "Distance moyenne trajet VL (metres)" },
  avg_min_distance_m: { label: "avg_min_distance_m", description: "Distance min moyenne VL (metres)" },
  avg_distance_before_m: { label: "avg_distance_before_m", description: "Trajet VL avant le segment (metres)" },
  avg_distance_after_m: { label: "avg_distance_after_m", description: "Trajet VL apres le segment (metres)" },
  truck_avg_distance_m: { label: "truck_avg_distance_m", description: "Distance moyenne PL (metres)" },
  truck_avg_min_distance_m: { label: "truck_avg_min_distance_m", description: "Distance min moyenne PL (metres)" },
  truck_avg_distance_before_m: { label: "truck_avg_distance_before_m", description: "Trajet PL avant le segment (metres)" },
  truck_avg_distance_after_m: { label: "truck_avg_distance_after_m", description: "Trajet PL apres le segment (metres)" },
  AgregId: { label: "AgregId", description: "Identifiant unique du segment HERE" },
  HD: { label: "HD", description: "Heading (cap 0-359°), depuis FCDREFGLOBAL" },
  DIR_TRAVEL: { label: "DIR_TRAVEL", description: "Direction de circulation (F/T/B) — utilisee pour calculer DD (True si B)" },
  // === Pre-computed engineered features (some models use them) ===
  fcd_log: { label: "fcd_log", description: "Log du debit FCD (pre-calcule)" },
  tv_pl_ratio: { label: "tv_pl_ratio", description: "Ratio TMJOFCDTV / TMJOFCDPL (pre-calcule)" },
  dist_to_lyon_center: { label: "dist_to_lyon_center", description: "Distance au centre de Lyon (metres, pre-calculee)" },
  // === Hourly FCD numerators (HPM / HPS models) ===
  FCD_HPM_TV: { label: "FCD_HPM_TV", description: "Debit FCD heure de pointe matin (8h-9h, v/h)" },
  FCD_HPS_TV: { label: "FCD_HPS_TV", description: "Debit FCD heure de pointe soir (17h-18h, v/h)" },
  // === Legacy names kept for retro-compat (silently aliased server-side) ===
  TMJATV: { label: "TMJATV (legacy)", description: "Ancien nom : sera mappe automatiquement vers TMJOFCDTV" },
  TMJAPL: { label: "TMJAPL (legacy)", description: "Ancien nom : sera mappe automatiquement vers TMJOFCDPL" },
  TMJAFCDTV: { label: "TMJAFCDTV (legacy)", description: "Ancien nom : sera mappe automatiquement vers TMJOFCDTV" },
  TMJAFCDPL: { label: "TMJAFCDPL (legacy)", description: "Ancien nom : sera mappe automatiquement vers TMJOFCDPL" },
  linkFC: { label: "linkFC (legacy)", description: "Ancien nom : sera mappe automatiquement vers functional_class" },
};

// Backend-derived columns that must NOT appear in the mapping form (they are
// computed server-side from other inputs).
export const BACKEND_DERIVED_COLUMNS = new Set<string>(["year_mapped"]);

export function buildColumnDef(key: string, required: boolean): ColumnDef {
  const meta = COLUMN_METADATA[key];
  return {
    key,
    label: meta?.label ?? key,
    description: meta?.description ?? `Colonne d'entree du modele : ${key}`,
    required,
  };
}

// ---------------------------------------------------------------------------
// computeDynamicRequiredColumns
// ---------------------------------------------------------------------------
// Logique pure (sans React) : derive la liste de colonnes a mapper a partir
// des training_config des 4 modeles + fallback. Sortie utilisee par un useMemo
// dans la page.
// ---------------------------------------------------------------------------

type TrainingCfg =
  | {
      input_cols?: unknown;
      use_year_feature?: unknown;
      year_column_name?: unknown;
      year_value_mapping?: unknown;
    }
  | null
  | undefined;

interface DynamicColumnsInput {
  tvCfg: TrainingCfg;
  plCfg: TrainingCfg;
  hpmCfg: TrainingCfg;
  hpsCfg: TrainingCfg;
  /**
   * PL is optional (same as HPM/HPS). Its input columns are merged into the
   * required union ONLY when the PL model is loaded & valid. When ``plValid``
   * is not true, PL-specific inputs are dropped from the mapping form and the
   * derived PL outputs (DPL/DPLmin/DPLmax, PLr*, PLred, VLred) won't be
   * produced server-side.
   */
  plValid: boolean | null;
  hpmValid: boolean | null;
  hpsValid: boolean | null;
}

// ---------------------------------------------------------------------------
// Year helpers — shared with the page so the dedicated "Mapping de l'annee"
// block (ported from evaluation/page.tsx) consumes the SAME logic that
// removes year columns from the regular mapping. The year is no longer asked
// as a regular mapping row : it is derived server-side from a single source
// column + a year->value table.
// ---------------------------------------------------------------------------

const includesYearMapped = (cfg: TrainingCfg): boolean =>
  Array.isArray(cfg?.input_cols) &&
  (cfg!.input_cols as unknown[]).includes("year_mapped");

/**
 * True when ANY of the supplied configs needs the year feature — either via an
 * explicit ``use_year_feature`` flag or because ``year_mapped`` is present in
 * its ``input_cols``. The dedicated year block is shown only when this is true.
 */
export function usesYearFeature(
  configs: ReadonlyArray<TrainingCfg>,
): boolean {
  return configs.some(
    (cfg) => cfg?.use_year_feature === true || includesYearMapped(cfg),
  );
}

/**
 * Resolve the SINGLE canonical source-year column name across all models.
 * We no longer expose one row per model (which produced duplicate 'Annee' /
 * 'annee' rows). Instead we pick the first non-empty ``year_column_name``
 * declared by any config, defaulting to "Annee" when the year feature is used
 * but no column name is declared. Returns null when the year feature is unused.
 */
export function resolveYearColumn(
  configs: ReadonlyArray<TrainingCfg>,
): string | null {
  if (!usesYearFeature(configs)) return null;
  for (const cfg of configs) {
    if (typeof cfg?.year_column_name === "string" && cfg.year_column_name.length > 0) {
      return cfg.year_column_name as string;
    }
  }
  return "Annee";
}

// Literal year column names that must never appear as a regular mapping row
// (they are handled by the dedicated year block). Compared case-insensitively.
const YEAR_COLUMN_LITERALS = ["annee", "year"];

/**
 * Build the set of column names (lower-cased) that must be EXCLUDED from the
 * regular mapping because they represent the year. Covers ``year_mapped``,
 * every config's ``year_column_name`` (case-insensitive) and the literals
 * "annee"/"Annee" (+ "year"/"Year").
 */
function buildYearExclusionSet(
  configs: ReadonlyArray<TrainingCfg>,
): Set<string> {
  const excluded = new Set<string>();
  for (const d of BACKEND_DERIVED_COLUMNS) excluded.add(d.toLowerCase());
  for (const lit of YEAR_COLUMN_LITERALS) excluded.add(lit);
  for (const cfg of configs) {
    if (typeof cfg?.year_column_name === "string" && cfg.year_column_name.length > 0) {
      excluded.add((cfg.year_column_name as string).toLowerCase());
    }
  }
  return excluded;
}

export function computeDynamicRequiredColumns(
  input: DynamicColumnsInput,
): ColumnDef[] {
  const { tvCfg, plCfg, hpmCfg, hpsCfg, plValid, hpmValid, hpsValid } = input;

  const tvInputs = Array.isArray(tvCfg?.input_cols)
    ? (tvCfg!.input_cols as unknown[])
    : null;
  // PL is optional (like HPM/HPS). Its inputs are merged into the union ONLY
  // when the PL model is loaded & valid. When PL is absent, none of the
  // PL-specific input columns are asked for and the backend skips the PL
  // outputs (DPL/DPLmin/DPLmax and derived PLr*/PLred/VLred).
  const plInputs =
    plValid === true && Array.isArray(plCfg?.input_cols)
      ? (plCfg!.input_cols as unknown[])
      : null;
  // HPM / HPS inputs are merged into the union ONLY when the corresponding
  // model is loaded — keeps the mapping form lean when the user only does
  // TV (+ optional PL). Backend tolerates missing FCD_HPM_TV when
  // ``model_hpm_dir`` is null, so the form follows the same conditional logic.
  const hpmInputs =
    hpmValid === true && Array.isArray(hpmCfg?.input_cols)
      ? (hpmCfg!.input_cols as unknown[])
      : null;
  const hpsInputs =
    hpsValid === true && Array.isArray(hpsCfg?.input_cols)
      ? (hpsCfg!.input_cols as unknown[])
      : null;

  // Configs that actually participate in the union (PL/HPM/HPS only when
  // loaded). Used for year detection so a year column declared only by an
  // unloaded optional model never leaks into the exclusion set / dedicated
  // block.
  const activeConfigs: TrainingCfg[] = [tvCfg];
  if (plValid === true) activeConfigs.push(plCfg);
  if (hpmValid === true) activeConfigs.push(hpmCfg);
  if (hpsValid === true) activeConfigs.push(hpsCfg);

  // Fallback: if the mandatory model (TV) lacks training_config / input_cols,
  // use the legacy hardcoded list to preserve compatibility with old models.
  // PL/HPM/HPS are optional so they don't trigger fallback.
  // NOTE: even in fallback we strip the {key:"annee"} row when the year is
  // handled by the dedicated block. With no training_config we cannot know
  // whether the year feature is used, so we conservatively KEEP the legacy
  // "annee" row (old models without training_config relied on it being mapped
  // as a regular column). The dedicated block only renders when a loaded
  // config declares the year feature, so there is no double-ask in practice.
  if (!tvInputs) {
    return REQUIRED_COLUMNS;
  }

  const union = new Set<string>();
  for (const c of [
    ...tvInputs,
    ...(plInputs ?? []),
    ...(hpmInputs ?? []),
    ...(hpsInputs ?? []),
  ]) {
    if (typeof c === "string" && c.length > 0) union.add(c);
  }

  // Exclude EVERY year-related column from the regular mapping. The year is
  // mapped exclusively through the dedicated "Mapping de l'annee" block
  // (single source column + year->value table), exactly like in Evaluation.
  // This removes the old duplicate 'Annee'/'annee' rows and the year_mapped
  // derived column in one pass (case-insensitive).
  const yearExcluded = buildYearExclusionSet(activeConfigs);
  for (const key of Array.from(union)) {
    if (yearExcluded.has(key.toLowerCase())) union.delete(key);
  }

  // Required model inputs, sorted alphabetically for stable rendering
  const required = Array.from(union)
    .sort()
    .map((k) => buildColumnDef(k, true));

  // Optional display-only columns (kept for AgregId and DD output cells)
  const optional: ColumnDef[] = [
    {
      key: "agregId",
      label: "Identifiant troncon",
      description: "LINK_ID ou identifiant unique (optionnel)",
      required: false,
    },
    {
      key: "HD",
      label: "HD",
      description: "Heading (cap 0-359°, optionnel — depuis FCDREFGLOBAL)",
      required: false,
    },
    {
      key: "DIR_TRAVEL",
      label: "Direction",
      description:
        "Direction circulation F/T/B (DD sera calcule : True si B)",
      required: false,
    },
  ];

  return [...required, ...optional];
}
