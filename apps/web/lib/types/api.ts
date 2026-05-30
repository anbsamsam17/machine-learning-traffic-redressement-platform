/**
 * Shared API response types. Centralized to avoid the
 * redefine-the-same-interface-in-3-pages pattern.
 */

export interface UploadResponse {
  session_id: string;
  columns: string[];
  preview_rows?: Record<string, unknown>[];
  n_rows?: number;
}

export interface ModelInfo {
  name: string;
  path: string;
  has_weights: boolean;
  has_architecture: boolean;
  has_norm: boolean;
  training_config?: Record<string, unknown>;
}

export interface ModelsListResponse {
  models: ModelInfo[];
  extract_dir?: string;
}

export interface EvalMetrics {
  rmse: number;
  mae: number;
  mape: number | null;
  r_squared: number;
  geh_mean: number;
  geh_pct_below_5: number;
  n_samples: number;
  hd_rmse: number | null;
  ld_rmse: number | null;
  median_relative_error?: number | null;
}

export interface EvalRunResponse {
  metrics: EvalMetrics;
  report_html?: string;
}

export interface EvalReportResponse {
  report_html: string;
}

export interface TrainingStatus {
  status: "pending" | "running" | "completed" | "failed";
  current_epoch: number;
  total_epochs: number;
  current_model?: number;
  total_models?: number;
  current_model_name?: string | null;
  loss: number | null;
  val_loss: number | null;
  best_val_loss: number | null;
  error?: string | null;
}

export interface TrainingStartResponse {
  task_id: string;
  total_combinations?: number;
  output_dir?: string;
}

export interface AuthLoginResponse {
  access_token: string;
  token_type?: string;
}

export interface AuthMeResponse {
  email: string;
  id?: string;
}

export type AppMode = "tv" | "pl" | "hpm" | "hps" | "carte" | "compteurs" | "visualisation" | "discontinuites" | null;

/**
 * Backend ModelKind — uppercase variants sent in API payloads (e.g. /api/upload
 * `mode` form field, /api/evaluation/run). The frontend store keeps lowercase
 * variants; convert via `mode.toUpperCase()` when emitting to the backend.
 */
export type ModelKind = "TV" | "PL" | "HPM" | "HPS";
