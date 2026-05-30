// ---------------------------------------------------------------------------
// Carte — Types partages (extraits de app/carte/page.tsx)
// ---------------------------------------------------------------------------

export type ModelKind = "tv" | "pl" | "hpm" | "hps";

export interface UploadResponse {
  session_id: string;
  filename: string;
  rows: number;
  columns: string[];
  preview: Record<string, unknown>[];
}

export interface CarteModelUploadResponse {
  model_dir: string;
  valid: boolean;
  missing_files: string[];
  training_config: Record<string, unknown> | null;
}

export interface CarteStats {
  total_segments: number;
  filtered_segments: number;
  mean_tvr: number | null;
  mean_dpl: number | null;
}

export interface CarteGenerateResponse {
  session_id: string;
  stats: CarteStats;
  geojson_feature_count: number;
}

export interface CapteursPlInfo {
  n_capteurs: number;
  annees_disponibles: number[];
}

export interface CapteursPlUploadResponse {
  session_id: string;
  n_capteurs: number;
  annees_disponibles: number[];
  path?: string;
}

// ---------------------------------------------------------------------------
// Column mapping
// ---------------------------------------------------------------------------

export interface ColumnDef {
  key: string;
  label: string;
  description: string;
  required: boolean;
}

// ---------------------------------------------------------------------------
// Saturation configs (groupements destines aux composants extraits)
// ---------------------------------------------------------------------------

export interface PlSaturationConfig {
  enabled: boolean;
  bornesFc1: number;
  bornesFc2: number;
  bornesFc3: number;
  bornesFc4: number;
  bornesFc5: number;
  alphaFc1: number;
  alphaFc2: number;
  alphaFc3: number;
  alphaFc4: number;
  alphaFc5: number;
  ratioMacroPen: number;
  alphaPhysiqueMax: number;
  seuilVolFcdTv: number;
  // v3 zones critiques
  zoneCritEnabled: boolean;
  capteursPlSessionId: string | null;
  anneeCapteurs: number;
  ratioCapteurCritique: number;
  bufferZoneCritiqueM: number;
  alphaMinZoneCritique: number;
}

export interface HourlySaturationConfig {
  enabled: boolean;
  borneFc1: number;
  borneFc2: number;
  borneFc3: number;
  borneFc4: number;
  borneFc5: number;
  alphaFc1: number;
  alphaFc2: number;
  alphaFc3: number;
  alphaFc4: number;
  alphaFc5: number;
}

// Alias historique demande par la spec
export type HpmHpsSaturationConfig = HourlySaturationConfig;
