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
    }
  | null
  | undefined;

interface DynamicColumnsInput {
  tvCfg: TrainingCfg;
  plCfg: TrainingCfg;
  hpmCfg: TrainingCfg;
  hpsCfg: TrainingCfg;
  hpmValid: boolean | null;
  hpsValid: boolean | null;
}

export function computeDynamicRequiredColumns(
  input: DynamicColumnsInput,
): ColumnDef[] {
  const { tvCfg, plCfg, hpmCfg, hpsCfg, hpmValid, hpsValid } = input;

  const tvInputs = Array.isArray(tvCfg?.input_cols)
    ? (tvCfg!.input_cols as unknown[])
    : null;
  const plInputs = Array.isArray(plCfg?.input_cols)
    ? (plCfg!.input_cols as unknown[])
    : null;
  // HPM / HPS inputs are merged into the union ONLY when the corresponding
  // model is loaded — keeps the mapping form lean when the user only does
  // TV+PL. Backend tolerates missing FCD_HPM_TV when ``model_hpm_dir`` is
  // null, so the form follows the same conditional logic.
  const hpmInputs =
    hpmValid === true && Array.isArray(hpmCfg?.input_cols)
      ? (hpmCfg!.input_cols as unknown[])
      : null;
  const hpsInputs =
    hpsValid === true && Array.isArray(hpsCfg?.input_cols)
      ? (hpsCfg!.input_cols as unknown[])
      : null;

  // Fallback: if either mandatory model (TV / PL) lacks training_config /
  // input_cols, use the legacy hardcoded list to preserve compatibility
  // with old models. HPM/HPS are optional so they don't trigger fallback.
  if (!tvInputs || !plInputs) {
    return REQUIRED_COLUMNS;
  }

  const union = new Set<string>();
  for (const c of [
    ...tvInputs,
    ...plInputs,
    ...(hpmInputs ?? []),
    ...(hpsInputs ?? []),
  ]) {
    if (typeof c === "string" && c.length > 0) union.add(c);
  }

  // The form should never ask for backend-derived columns
  for (const derived of BACKEND_DERIVED_COLUMNS) union.delete(derived);

  // If year_mapped was in input_cols (or any config requests the year
  // feature), the form must ask for the source year column (default "Annee")
  // instead, because the backend derives year_mapped via _apply_year_mapping.
  const includesYearMapped = (cfg: TrainingCfg) =>
    Array.isArray(cfg?.input_cols) &&
    (cfg!.input_cols as unknown[]).includes("year_mapped");
  const yearColOf = (cfg: TrainingCfg, dflt = "Annee") =>
    typeof cfg?.year_column_name === "string"
      ? (cfg!.year_column_name as string)
      : dflt;
  const usesYear =
    tvCfg?.use_year_feature === true ||
    plCfg?.use_year_feature === true ||
    hpmCfg?.use_year_feature === true ||
    hpsCfg?.use_year_feature === true ||
    includesYearMapped(tvCfg) ||
    includesYearMapped(plCfg) ||
    (hpmValid === true && includesYearMapped(hpmCfg)) ||
    (hpsValid === true && includesYearMapped(hpsCfg));
  if (usesYear) {
    const yrs = new Set<string>();
    yrs.add(yearColOf(tvCfg));
    yrs.add(yearColOf(plCfg));
    if (hpmValid === true) yrs.add(yearColOf(hpmCfg));
    if (hpsValid === true) yrs.add(yearColOf(hpsCfg));
    for (const y of yrs) union.add(y);
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
