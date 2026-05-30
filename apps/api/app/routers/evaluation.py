"""Evaluation router — upload validation data, run model evaluation, generate HTML report, download model.

Heavy lifting has been extracted to dedicated services during the T2 refactor:

* ``app.services.ml.metrics_advanced`` — bootstrap CI95, TMJA stratification,
  calibration data, residuals by functional_class, annual drift.
* ``app.services.reports`` — three HTML report generators (TV, PL,
  HPM/HPS) plus the display-label / format helpers they share.

The router itself now mostly orchestrates these services and owns the
HTTP-layer concerns (auth, payload validation, session storage, model load,
prediction + post-processing). For the call shapes of the public endpoints
see the pydantic models below.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..auth import UserRecord, get_current_user, require_owned_session
from ..session import session_manager

# Advanced metrics — extracted to services/ml/metrics_advanced.py (T2).
from ..services.ml.metrics_advanced import (
    _DRIFT_MIN_SAMPLES,
    _compute_calibration_data,
    _compute_drift_by_year,
    _compute_residuals_by_fc,
    _metric_p80_err_rel,
    _metric_r2,
    _metric_tol_in_pct,
    _stratify_by_tmja,
    bootstrap_ci95,
)

# HTML report generators + shared display helpers — extracted to services/reports/.
from ..services.reports import (
    _add_tolerance_columns,
    _build_sensitivity_section_html,
    _compute_flow_metrics,
    _compute_tolerance_counts,
    _fmt,
    _label,
    _make_calibration_plot_html,
    _make_drift_by_year_html,
    _make_residuals_by_fc_html,
)
from ..services.reports.html_peak import (
    _add_tolerance_columns_HPM_HPS,
    _build_sensitivity_section_html_HPM_HPS,
    _compute_flow_metrics_HPM_HPS,
    _make_barplot_html_HPM_HPS,
    _make_distribution_barplot_html_HPM_HPS,
    _make_folium_map_html_HPM_HPS,
    generate_html_report_peak,
)
from ..services.reports.html_pl import (
    _make_barplot_html_PL,
    _make_folium_map_html_PL,
    generate_html_report_pl,
)
from ..services.reports.html_tv import (
    _make_barplot_html,
    _make_folium_map_html,
    generate_html_report_tv,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])

DEFAULT_HIGH_FLOW_THRESHOLD = 1000.0


# ---------------------------------------------------------------------------
# val_renames — FCD HERE ↔ legacy Bordeaux column alias map.
#
# The downstream report / tolerance / barplot code is written against the
# legacy Bordeaux names (TMJABCTV, TMJAFCDTV, TxPenTVRef). We translate the
# new FCD HERE schema (TMJOBCTV, TMJOFCDTV, TxPen) onto those legacy aliases
# at two ingestion points so the report renders correctly without per-section
# patches:
#
#   * ``_VAL_RENAMES_UPLOAD`` — applied at ``/upload-validation``. Includes
#     the rare ``TMJAVL → TMJAFCDVL`` alias for backward compat with very
#     old datasets.
#   * ``_VAL_RENAMES_RUN`` — applied at ``/run``. Same dict minus the VL
#     alias (VL never appears in the model inputs, so adding it would just
#     create a phantom column on the eval frame).
# ---------------------------------------------------------------------------
_VAL_RENAMES_UPLOAD: dict[str, str] = {
    "TMJATV": "TMJAFCDTV",
    "TMJFCDTV": "TMJAFCDTV",
    "TMJOFCDTV": "TMJAFCDTV",
    "TMJAPL": "TMJAFCDPL",
    "TMJFCDPL": "TMJAFCDPL",
    "TMJOFCDPL": "TMJAFCDPL",
    "TMJAVL": "TMJAFCDVL",
    "TMJOBCTV": "TMJABCTV",
    "TMJOBCPL": "TMJABCPL",
    "TxPen": "TxPenTVRef",
    "TxPenPL": "TxPenPLRef",
}

_VAL_RENAMES_RUN: dict[str, str] = {
    # FCD throughput aliases
    "TMJATV": "TMJAFCDTV", "TMJFCDTV": "TMJAFCDTV", "TMJOFCDTV": "TMJAFCDTV",
    "TMJAPL": "TMJAFCDPL", "TMJFCDPL": "TMJAFCDPL", "TMJOFCDPL": "TMJAFCDPL",
    # Sensor counts (Boucle Comptage)
    "TMJOBCTV": "TMJABCTV", "TMJOBCPL": "TMJABCPL",
    # Penetration rates
    "TxPen": "TxPenTVRef", "TxPenPL": "TxPenPLRef",
}


# ---------------------------------------------------------------------------
# Backward-compatible aliases for the renamed report generators.
# The body still uses the original ``_generate_html_report_*`` names; these
# thin aliases keep the dispatcher readable + grep-friendly across the
# legacy commit history.
# ---------------------------------------------------------------------------
_generate_html_report = generate_html_report_tv
_generate_html_report_PL = generate_html_report_pl


def _generate_html_report_kind(*args, **kwargs) -> str:
    """Thin alias — delegates to :func:`generate_html_report_peak` (HPM/HPS)."""
    return generate_html_report_peak(*args, **kwargs)


def _generate_html_report_HPM(*args, **kwargs) -> str:
    """Thin alias — HPM rapport (h08-h09, v/h, ref TMJOBCTV_HPM)."""
    from ..services.ml.types import HPM_CONFIG
    kwargs.pop("type_config", None)
    return generate_html_report_peak(*args, type_config=HPM_CONFIG, **kwargs)


def _generate_html_report_HPS(*args, **kwargs) -> str:
    """Thin alias — HPS rapport (h17-h18, v/h, ref TMJOBCTV_HPS)."""
    from ..services.ml.types import HPS_CONFIG
    kwargs.pop("type_config", None)
    return generate_html_report_peak(*args, type_config=HPS_CONFIG, **kwargs)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class EvalRequest(BaseModel):
    session_id: str
    model_name: str | None = None
    model_dir: str | None = None
    high_flow_threshold: float = DEFAULT_HIGH_FLOW_THRESHOLD
    filter_flag_comptage: bool = False
    column_mapping: dict[str, str] | None = None  # target -> source mapping from frontend
    # Year-feature mapping override — the frontend keeps year_value_mapping
    # in its training config (Zustand). When evaluating, pass it here so
    # year_mapped can be replayed correctly even if the model's
    # training_config.json was saved before year_value_mapping started
    # being persisted there.
    year_column_name: str | None = None
    year_value_mapping: dict[str, float] | None = None


class MetricsResult(BaseModel):
    rmse: float
    mae: float
    mape: float | None = None
    r_squared: float
    geh_mean: float
    geh_pct_below_5: float
    n_samples: int
    hd_rmse: float | None = None
    ld_rmse: float | None = None
    median_relative_error: float | None = None


class EvalResponse(BaseModel):
    session_id: str
    model_name: str
    metrics: MetricsResult
    report_url: str
    # P1.1 - bootstrap CI95 on tol_in_pct, p80 (err_rel), r2.
    # Keys: "tol_in_pct" -> [low, high], "p80" -> [low, high], "r2" -> [low, high].
    # None when bootstrap was skipped (n<30 or bootstrap_iter=0).
    metrics_ci95: dict[str, list[float] | None] | None = None
    # P1.2 — same metrics (tol_in_pct, p80, r2, n_samples) recomputed per
    # TMJOBCTV bucket so we can see whether the model fails specifically
    # on low- or high-traffic sensors. Empty list when TMJOBCTV/TMJABCTV
    # is absent from the validation data.
    metrics_by_tmja_bucket: list[dict[str, Any]] = Field(default_factory=list)
    # P4.1 — calibration scatter (obs vs pred). None when y_true/y_pred empty.
    # Shape: {"obs": [...], "pred": [...], "n": int}.
    calibration_data: dict[str, Any] | None = None
    # P4.2 — residual boxplot by functional_class. List of per-class entries
    # {"fc": 1..5, "residuals": [...], "n": int, "median": float, ...}.
    # Empty list when functional_class (or fc_1..fc_5 one-hot) is absent.
    residuals_by_fc: list[dict[str, Any]] = Field(default_factory=list)
    # P4.3 — annual drift table. One entry per year_mapped value with at
    # least 10 samples; {"year_mapped": int, "year_label": str, "n_samples":
    # int, "r2": float, "mae": float, "tol_in_pct": float, "p80": float}.
    drift_by_year: list[dict[str, Any]] = Field(default_factory=list)


class ReportResponse(BaseModel):
    session_id: str
    report_html: str


class ModelInfo(BaseModel):
    name: str
    path: str
    has_weights: bool
    has_architecture: bool
    has_norm: bool
    training_config: dict[str, Any] | None = None


class ModelsListResponse(BaseModel):
    models: list[ModelInfo]


# P1.4 — McNemar comparison of two evaluated models
class CompareRequest(BaseModel):
    session_id: str
    run_a: str
    run_b: str
    tolerance_pct: float = 15.0


class KFoldRequest(BaseModel):
    """Body for POST /api/evaluation/kfold (P1.3).

    The endpoint re-trains the model identified by ``run_name`` k times on
    different folds of the session's training DataFrame, using the *same*
    hyper-parameters as the original run. It returns per-fold held-out
    metrics plus a mean/std summary so the caller can see how stable a
    "good" model actually is.
    """

    session_id: str
    run_name: str
    # k must be small enough to keep the wall-clock under control, large
    # enough to give a meaningful std estimate. The audit plan specifies 5;
    # we cap at 10 to discourage absurdly long runs.
    k: int = Field(default=5, ge=2, le=10)
    shuffle_seed: int = 1750
    # Optional override of the search root used to locate ``run_name``.
    # When None, we look under ``WORKSPACE_ROOT/{session_id}/models/``.
    model_dir: str | None = None


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

def _geh(observed: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """GEH statistic (traffic engineering).

    Inputs are TMJA (volumes journaliers) — converted to hourly (/24) before
    applying the standard GEH formula `sqrt(2*(M-C)**2/(M+C))`. Matches the
    implementation in services/ml/evaluation_pipeline.py.
    """
    obs_h = observed / 24.0
    pred_h = predicted / 24.0
    denom = (obs_h + pred_h) / 2.0
    denom = np.where(denom == 0, 1e-9, denom)
    return np.sqrt((obs_h - pred_h) ** 2 / denom)


def _geh_hourly(observed: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """GEH statistic on already-hourly volumes (HPM/HPS, unit v/h).

    Universal GEH formula ``sqrt(2*(M-C)**2/(M+C))`` applied as-is (no /24
    conversion). Matches ``_compute_flow_metrics_HPM_HPS`` and the HTML
    report computation so MetricsResult.geh_pct_below_5 aligns with the
    HPM/HPS HTML card.

    A weakly trained model can produce strongly negative predictions, which
    yields ``observed + predicted < 0`` and a NaN under the square root. We
    floor the denominator at ``1e-9`` (matches the legacy ``_geh`` helper)
    so the resulting array is finite even on edge cases.
    """
    denom = (observed + predicted) / 2.0
    denom = np.where(denom <= 0, 1e-9, denom)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.sqrt((observed - predicted) ** 2 / denom)


def _compute_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    high_threshold: float,
    flows: np.ndarray | None = None,
) -> MetricsResult:
    """Compute evaluation metrics.

    The HD/LD split (``hd_rmse`` / ``ld_rmse``) is applied on the observed
    traffic flow (TMJOBCTV, typical range 100..50000+) — NOT on ``y_true``,
    which may be a penetration rate (TxPen, range ~0..1) and would therefore
    never exceed the default 1000 threshold. Callers pass the flow array
    through ``flows``; if absent, both hd_rmse and ld_rmse fall back to
    ``None`` (no crash, no misleading number).
    """
    residuals = y_true - y_pred
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    mae = float(np.mean(np.abs(residuals)))

    # MAPE
    nonzero = y_true != 0
    mape = float(np.mean(np.abs(residuals[nonzero] / y_true[nonzero])) * 100) if nonzero.any() else None

    # Median relative error
    median_rel = float(np.median(np.abs(residuals[nonzero] / y_true[nonzero])) * 100) if nonzero.any() else None

    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    geh_vals = _geh(y_true, y_pred)
    geh_mean = float(np.mean(geh_vals))
    geh_below_5 = float(np.mean(geh_vals < 5) * 100)

    # HD / LD subsets — the threshold is meant to separate high-flow vs
    # low-flow segments of the road network, so it MUST be applied on the
    # observed flow (TMJOBCTV), not on ``y_true`` (which could be a 0..1
    # penetration rate). Gracefully fall back when ``flows`` is absent.
    hd_rmse: float | None = None
    ld_rmse: float | None = None
    if flows is not None:
        flows_arr = np.asarray(flows, dtype=np.float64)
        if flows_arr.shape == y_true.shape:
            finite = np.isfinite(flows_arr)
            hd_mask = finite & (flows_arr >= high_threshold)
            ld_mask = finite & (flows_arr < high_threshold)
            if hd_mask.any():
                hd_rmse = float(np.sqrt(np.mean(residuals[hd_mask] ** 2)))
            if ld_mask.any():
                ld_rmse = float(np.sqrt(np.mean(residuals[ld_mask] ** 2)))
        else:
            logger.warning(
                "hd/ld split skipped: flows shape %s != y_true shape %s",
                flows_arr.shape,
                y_true.shape,
            )

    return MetricsResult(
        rmse=round(rmse, 4),
        mae=round(mae, 4),
        mape=round(mape, 2) if mape is not None else None,
        r_squared=round(r2, 6),
        geh_mean=round(geh_mean, 4),
        geh_pct_below_5=round(geh_below_5, 2),
        n_samples=len(y_true),
        hd_rmse=round(hd_rmse, 4) if hd_rmse is not None else None,
        ld_rmse=round(ld_rmse, 4) if ld_rmse is not None else None,
        median_relative_error=round(median_rel, 2) if median_rel is not None else None,
    )


def _compute_metrics_hourly(
    obs_vh: np.ndarray,
    pred_vh: np.ndarray,
    high_threshold: float,
) -> MetricsResult:
    """Compute MetricsResult for HPM/HPS from already-hourly v/h volumes.

    Mirrors ``_compute_metrics`` but:
      * GEH uses the universal hourly formula (no /24 conversion) so it
        aligns with the HTML report's ``_compute_flow_metrics_HPM_HPS``.
      * All deltas (RMSE/MAE/MAPE/R²/median_rel) are computed on the
        redressed v/h pair (predicted HPM_FCDr/HPS_FCDr vs counter
        TMJOBCTV_HPM/HPS) instead of the raw TxPen 0..100 scale. NaN/Inf
        rows are filtered upfront so the report card and the API agree
        on n_samples.
      * HD/LD split is applied on the observed counter (v/h) using the
        kind-specific high_threshold (HPM/HPS default = 80 v/h).
    """
    obs = np.asarray(obs_vh, dtype=np.float64).ravel()
    pred = np.asarray(pred_vh, dtype=np.float64).ravel()
    finite = np.isfinite(obs) & np.isfinite(pred)
    obs = obs[finite]
    pred = pred[finite]

    if obs.size == 0:
        return MetricsResult(
            rmse=0.0, mae=0.0, mape=None, r_squared=0.0,
            geh_mean=0.0, geh_pct_below_5=0.0, n_samples=0,
            hd_rmse=None, ld_rmse=None, median_relative_error=None,
        )

    residuals = obs - pred
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    mae = float(np.mean(np.abs(residuals)))

    nonzero = obs != 0
    mape = float(np.mean(np.abs(residuals[nonzero] / obs[nonzero])) * 100) if nonzero.any() else None
    median_rel = float(np.median(np.abs(residuals[nonzero] / obs[nonzero])) * 100) if nonzero.any() else None

    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((obs - np.mean(obs)) ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    geh_vals = _geh_hourly(obs, pred)
    # Robust against rare NaN (denom clamping never returns NaN, but keep
    # nan-aware aggregators as a belt-and-braces): we want geh_mean to be a
    # finite number aligned with the report card (which uses dropna upstream).
    geh_finite = geh_vals[np.isfinite(geh_vals)]
    geh_mean = float(np.mean(geh_finite)) if geh_finite.size else 0.0
    geh_below_5 = (
        float(np.mean(geh_finite < 5) * 100) if geh_finite.size else 0.0
    )

    # HD / LD split on the observed counter (v/h). high_threshold should be
    # the kind-specific peak-hour threshold (HPM/HPS default 80 v/h).
    hd_mask = obs >= high_threshold
    ld_mask = obs < high_threshold
    hd_rmse = float(np.sqrt(np.mean(residuals[hd_mask] ** 2))) if hd_mask.any() else None
    ld_rmse = float(np.sqrt(np.mean(residuals[ld_mask] ** 2))) if ld_mask.any() else None

    return MetricsResult(
        rmse=round(rmse, 4),
        mae=round(mae, 4),
        mape=round(mape, 2) if mape is not None else None,
        r_squared=round(r2, 6),
        geh_mean=round(geh_mean, 4),
        geh_pct_below_5=round(geh_below_5, 2),
        n_samples=int(obs.size),
        hd_rmse=round(hd_rmse, 4) if hd_rmse is not None else None,
        ld_rmse=round(ld_rmse, 4) if ld_rmse is not None else None,
        median_relative_error=round(median_rel, 2) if median_rel is not None else None,
    )


# ---------------------------------------------------------------------------
# Helper: load model from disk
# ---------------------------------------------------------------------------

def _load_model_from_dir(model_path: Path) -> tuple[Any, dict]:
    """Load a Keras model + norm coefficients from a model directory on disk.

    Uses services.ml.packaging.load_model_compat so both the new
    .keras format and the legacy NNarchitecture.json + .weights.h5 layout
    are supported transparently (C4).
    """
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

    from ..services.ml.packaging import load_model_compat
    model = load_model_compat(model_path)

    # Load norm coefficients
    norm_file = model_path / "NNnormCoefficients.json"
    if not norm_file.exists():
        raise FileNotFoundError(f"NNnormCoefficients.json introuvable dans {model_path}")

    norm_data = json.loads(norm_file.read_text(encoding="utf-8"))

    # Load training config if available
    config_file = model_path / "training_config.json"
    training_config = None
    if config_file.exists():
        training_config = json.loads(config_file.read_text(encoding="utf-8"))

    return model, norm_data, training_config


def _read_uploaded_df(session_id: str) -> pd.DataFrame:
    """Get validation DataFrame from session (try multiple keys).

    Works with both MemoryBackend (session.data) and RedisBackend (get_data).
    """
    for key in ("validation_df", "learning_df", "raw_df"):
        try:
            df = session_manager.get_data(session_id, key)
            if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                logger.info("Using '%s' as validation data (%d rows)", key, len(df))
                return df.copy()
        except (KeyError, Exception) as e:
            logger.debug("Key '%s' not found: %s", key, e)
            continue
    raise ValueError("Aucune donnee de validation disponible dans la session.")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/upload-validation")
async def upload_validation(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    column_mapping: str = Form(""),
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Upload a validation file (GeoJSON or CSV) and store it in the session."""
    session = require_owned_session(session_id, current_user)

    content = await file.read()
    filename = file.filename or "validation"

    try:
        if filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        elif filename.lower().endswith((".geojson", ".json")):
            import geopandas as gpd
            df = gpd.read_file(io.BytesIO(content))
            # Extract lat/lon from Point geometry before dropping
            if "geometry" in df.columns:
                try:
                    points = df["geometry"]
                    if "lat" not in df.columns:
                        df["lat"] = points.y
                    if "lon" not in df.columns:
                        df["lon"] = points.x
                except (AttributeError, ValueError) as exc:
                    logger.warning("Could not derive lat/lon from geometry: %s", exc)
                df = pd.DataFrame(df.drop(columns=["geometry"]))
        else:
            # Try CSV fallback
            df = pd.read_csv(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Impossible de lire le fichier : {exc}",
        )

    # Column renames for compatibility (same aliases as training scripts).
    # Adds FCD HERE → legacy Bordeaux mapping so the eval report renders.
    for old, new in _VAL_RENAMES_UPLOAD.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]

    # Also try case-insensitive matching for columns the model expects
    col_lower_map = {c.lower(): c for c in df.columns}
    common_cols = [
        "TMJAFCDTV", "TMJAFCDPL", "TMJABCTV", "TMJABCPL",
        "car_average_speed_kmh", "car_average_distance_km",
        "truck_average_speed_kmh", "truck_min_average_distance_km",
        "car_count", "truck_count", "variabilite_FCD",
        "TxPenTVRef", "TxPenPLRef", "flag_comptage",
    ]
    for target in common_cols:
        if target not in df.columns and target.lower() in col_lower_map:
            df[target] = df[col_lower_map[target.lower()]]

    # Apply user-provided column mapping (target -> source)
    if column_mapping:
        try:
            mapping_dict: dict[str, str] = json.loads(column_mapping)
            for target_col, source_col in mapping_dict.items():
                if source_col and source_col in df.columns and target_col not in df.columns:
                    df[target_col] = df[source_col]
                    logger.info("Mapping colonne: %s -> %s", source_col, target_col)
        except (json.JSONDecodeError, TypeError):
            logger.warning("column_mapping invalide, ignore: %s", column_mapping[:100])

    # HPM / HPS — derive hourly columns from any present source (FCDTV_h08 /
    # h17 -> FCD_HPM_TV / FCD_HPS_TV ; FCD+BC -> TxPen_HPM / TxPen_HPS).
    # Idempotent : ne reecrit jamais les colonnes existantes.
    try:
        from ..services.ml.data_prep import derive_hpm_hps_columns
        df = derive_hpm_hps_columns(df)
    except Exception as _hpm_exc:  # noqa: BLE001
        logger.debug(
            "derive_hpm_hps_columns failed at upload-validation (non-blocking): %s",
            _hpm_exc,
        )

    logger.info("Validation columns after renames+mapping: %s", list(df.columns)[:30])
    session_manager.store_data(session_id, "validation_df", df)

    logger.info(
        "Validation file uploaded: session=%s file=%s rows=%d cols=%d",
        session_id, filename, len(df), len(df.columns),
    )

    return {
        "status": "ok",
        "filename": filename,
        "rows": len(df),
        "columns": len(df.columns),
    }


@router.post("/run", response_model=EvalResponse)
async def run_evaluation(
    body: EvalRequest,
    bootstrap_iter: int = Query(
        1000,
        ge=0,
        le=10000,
        description=(
            "Bootstrap iterations for CI95 on tol_in_pct / p80 / R-squared. "
            "Set to 0 to skip entirely. When non-zero, must lie in [100, 10000]."
        ),
    ),
    tta_iter: int = Query(
        1,
        ge=1,
        le=20,
        description=(
            "P4.7 — Test-time augmentation iterations. Default 1 disables TTA "
            "(behaviour identical to a single noise-free model.predict call). "
            "Values > 1 average n forward passes with small Gaussian noise "
            "injected in normalized feature space."
        ),
    ),
    tta_noise_std: float = Query(
        0.01,
        ge=0.0,
        le=0.1,
        description=(
            "P4.7 — Standard deviation of the Gaussian noise added in normalized "
            "feature space (1.0 == one standard deviation per feature). Ignored "
            "when tta_iter == 1."
        ),
    ),
    current_user: UserRecord = Depends(get_current_user),
) -> EvalResponse:
    """Run model evaluation on validation data.

    Supports two modes:
    1. model_name + model_dir: load model from disk (output_dir from training)
    2. Fallback to session-stored model (legacy)
    """
    # Validate bootstrap_iter - Query's ge=0/le=10000 only enforces the outer
    # envelope; the contract is "0 OR [100, 10000]" (P1.1 spec). Any other
    # value is a 422-equivalent client error.
    if bootstrap_iter != 0 and bootstrap_iter < 100:
        raise HTTPException(
            status_code=422,
            detail=(
                f"bootstrap_iter must be 0 or within [100, 10000]; got {bootstrap_iter}."
            ),
        )
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

    session = require_owned_session(body.session_id, current_user)

    # --- Determine model source ---
    model = None
    norm_params = None
    training_config = None
    model_name = body.model_name or "model"

    if body.model_name and body.model_dir:
        # Load from disk. Multiple resolutions tried in order :
        #   1. body.model_dir / body.model_name  (standard nested layout)
        #   2. body.model_dir                    (model files at the root of
        #                                         the dir — common when training
        #                                         did not create a run sub-folder)
        #   3. parent(body.model_dir) / body.model_name (duplicate-join case)
        #   4. body.model_dir / "models" / body.model_name (extra "models" wrap)
        # A candidate is accepted only when it contains the expected model file
        # (model.keras OR NNarchitecture.json) — this avoids accepting any dir
        # that happens to share a name with the requested model.
        model_dir_path = Path(body.model_dir)
        candidates: list[Path] = [
            model_dir_path / body.model_name,
            model_dir_path,
            model_dir_path.parent / body.model_name,
            model_dir_path / "models" / body.model_name,
        ]

        def _is_valid_model_dir(p: Path) -> bool:
            if not p.exists() or not p.is_dir():
                return False
            return (p / "model.keras").exists() or (p / "NNarchitecture.json").exists()

        model_path = next((c for c in candidates if _is_valid_model_dir(c)), None)
        if model_path is None:
            tried = " | ".join(str(c) for c in candidates)
            raise HTTPException(
                status_code=404,
                detail=f"Dossier modele introuvable. Chemins tentes : {tried}",
            )
        try:
            model, norm_raw, training_config = await asyncio.to_thread(
                _load_model_from_dir, model_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # Parse norm coefficients from disk format (muX/SX/muY/SY)
        x_mean = np.array(norm_raw["muX"][0], dtype=np.float64)
        x_std = np.array(norm_raw["SX"][0], dtype=np.float64)
        y_mean = float(norm_raw["muY"][0][0])
        y_std = float(norm_raw["SY"][0][0])

        # Get input/output cols from training config. The training pipeline
        # writes `output_cols` (plural list) — older callers used the singular
        # form so we accept both. Default mapped onto the new schema's TxPen
        # via val_renames a few lines down.
        if training_config:
            input_cols = training_config.get("input_cols", [])
            output_col = training_config.get("output_col")
            if not output_col:
                out_list = training_config.get("output_cols") or []
                output_col = out_list[0] if out_list else "TxPenTVRef"
        else:
            raise HTTPException(
                status_code=400,
                detail="training_config.json manquant dans le dossier modele.",
            )
    else:
        # Legacy: load from session
        model_json_str = session_manager.get_data(body.session_id, "trained_model_json")
        weights_bytes = session_manager.get_data(body.session_id, "trained_weights")
        session_norm = session_manager.get_data(body.session_id, "norm_params")

        if not all([model_json_str, weights_bytes, session_norm]):
            raise HTTPException(
                status_code=400,
                detail="Aucun modele entraine. Specifiez model_name + model_dir ou lancez l'entrainement.",
            )

        from tensorflow.keras.models import model_from_json
        model = model_from_json(model_json_str)

        with tempfile.NamedTemporaryFile(suffix=".weights.h5", delete=False) as tmp:
            tmp.write(weights_bytes)
            tmp_path = tmp.name
        model.load_weights(tmp_path)
        Path(tmp_path).unlink(missing_ok=True)

        input_cols = session_norm["input_cols"]
        output_col = session_norm["output_col"]
        x_mean = np.array(session_norm["x_mean"])
        x_std = np.array(session_norm["x_std"])
        y_mean = session_norm["y_mean"]
        y_std = session_norm["y_std"]

    # --- Get evaluation data ---
    try:
        df = _read_uploaded_df(body.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Apply user-provided column mapping first (from frontend)
    if body.column_mapping:
        for target_col, source_col in body.column_mapping.items():
            if source_col and source_col in df.columns and target_col not in df.columns:
                df[target_col] = df[source_col]

    # Apply column renames on validation data too (same as upload).
    # The downstream report/tolerance/barplot code is written against the
    # legacy Bordeaux names (TMJABCTV, TMJAFCDTV, TxPenTVRef). Map the new
    # FCD HERE schema (TMJOBCTV, TMJOFCDTV, TxPen) onto those legacy aliases
    # so the report renders correctly without per-section patches.
    for old, new in _VAL_RENAMES_RUN.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]

    # HPM / HPS — derive hourly columns (FCD_HPM_TV, TMJOBCTV_HPM, TxPen_HPM
    # et idem HPS) si absentes mais les sources brutes (FCDTV_h08 / h17) sont
    # presentes. Idempotent : si les colonnes existent deja, ne touche pas.
    try:
        from ..services.ml.data_prep import derive_hpm_hps_columns
        df = derive_hpm_hps_columns(df)
    except Exception as _hpm_exc:  # noqa: BLE001
        logger.debug("derive_hpm_hps_columns failed at eval (non-blocking): %s", _hpm_exc)

    # Case-insensitive fallback for missing columns
    col_lower = {c.lower(): c for c in df.columns}
    for target in input_cols + [output_col]:
        if target not in df.columns and target.lower() in col_lower:
            df[target] = df[col_lower[target.lower()]]

    # Derive year_mapped from Annee if the model needs it. The mapping is
    # resolved in priority order:
    #   1. body.year_value_mapping   (frontend-provided, always wins)
    #   2. training_config.year_value_mapping  (persisted at train time)
    #   3. raw Annee values          (last-resort fallback, may bias the model)
    if "year_mapped" in input_cols and "year_mapped" not in df.columns:
        year_col = body.year_column_name or None
        if not year_col or year_col not in df.columns:
            for cand in ("Annee", "annee", "Year", "year"):
                if cand in df.columns:
                    year_col = cand
                    break
        year_mapping = body.year_value_mapping or (training_config or {}).get("year_value_mapping") or {}
        if year_col and year_mapping:
            df["year_mapped"] = df[year_col].astype(str).map(year_mapping)
            if df["year_mapped"].isna().any():
                df["year_mapped"] = df["year_mapped"].fillna(df["year_mapped"].median())
            logger.info(
                "year_mapped: %d valeurs encodees via mapping (%d uniques)",
                int(df["year_mapped"].notna().sum()),
                len(year_mapping),
            )
        elif year_col:
            df["year_mapped"] = pd.to_numeric(df[year_col], errors="coerce")
            df["year_mapped"] = df["year_mapped"].fillna(df["year_mapped"].median())
            logger.warning(
                "year_mapped: pas de mapping fourni — utilisation directe de la colonne %s "
                "(les predictions seront biaisees si le modele a ete entraine sur des valeurs encodees)",
                year_col,
            )
        else:
            logger.warning("year_mapped requis mais Annee absente — assignation 0")
            df["year_mapped"] = 0

    # Filter by flag_comptage if requested (permanent sensors only)
    if body.filter_flag_comptage:
        if "flag_comptage" in df.columns:
            before = len(df)
            df = df[pd.to_numeric(df["flag_comptage"], errors="coerce") == 1]
            logger.info("Filtre flag_comptage=1 : %d -> %d lignes", before, len(df))
        else:
            logger.warning("flag_comptage demande mais colonne absente — pas de filtre applique")

    # Bug 7 — replay feature engineering on the evaluation df. When the model
    # was trained with feature_engineering.{add_pl_tv_ratio, log_transform_cols,
    # one_hot_functional_class}, the derived columns (ratio_PLTV, log_*, fc_*)
    # must be present in df BEFORE the missing-cols check below. The artifact's
    # training_config carries the exact derivations applied at train time.
    _fe = dict((training_config or {}).get("feature_engineering") or {})
    if _fe:
        try:
            from ..services.ml.data_prep import (
                _add_pl_tv_ratio,
                _apply_log_transform_cols,
                _one_hot_functional_class,
            )
            if bool(_fe.get("add_pl_tv_ratio", False)):
                df = _add_pl_tv_ratio(df)
            log_cols = list(_fe.get("log_transform_cols") or [])
            if log_cols:
                df = _apply_log_transform_cols(df, log_cols)
            if bool(_fe.get("one_hot_functional_class", False)):
                df = _one_hot_functional_class(df)
            logger.info("feature_engineering replayed at eval: %s", _fe)
        except Exception as exc:
            logger.warning("Failed to replay feature_engineering at eval: %s", exc)

    missing = [c for c in input_cols + [output_col] if c not in df.columns]
    if missing:
        # Log available columns for debugging
        logger.error("Colonnes manquantes: %s. Colonnes disponibles: %s", missing, list(df.columns)[:30])
        raise HTTPException(
            status_code=400,
            detail=f"Colonnes manquantes dans les donnees de validation : {missing}. Colonnes disponibles : {list(df.columns)[:20]}",
        )

    # Keep the full DataFrame for the report (with all columns like lat, lon, PTM_ID, etc.)
    # but only use rows where input_cols + output_col are non-null for prediction
    all_needed = input_cols + [output_col]
    sub = df.copy()
    sub[all_needed] = sub[all_needed].apply(pd.to_numeric, errors="coerce")
    valid_mask = sub[all_needed].notna().all(axis=1)
    sub = sub[valid_mask].copy()

    if len(sub) < 2:
        raise HTTPException(status_code=400, detail="Trop peu de lignes valides pour l'evaluation.")

    X = sub[input_cols].values.astype(np.float64)
    y_true = sub[output_col].values.astype(np.float64)

    # Expand mu/sigma to full input_cols length using on_off_norm. The training
    # pipeline only stores mu/sigma for the SUBSET of features with
    # on_off_norm=True (so a 5-feature model with year_mapped left raw stores
    # only 4 mu values). Without this expansion, `(X - mu) / sigma` raises
    # "could not be broadcast" — exactly the crash reported on Lyon for
    # fmask_111101 / fmask_111111 models.
    n_inputs = len(input_cols)
    if len(x_mean) != n_inputs:
        on_off_raw = (training_config or {}).get("on_off_norm")
        if on_off_raw is not None and len(on_off_raw) == n_inputs:
            on_off_arr = np.array(on_off_raw, dtype=bool)
        else:
            # Legacy fallback: assume trailing features (year_mapped, flag_*)
            # were left un-normalised. Matches evaluation_pipeline.py logic.
            on_off_arr = np.ones(n_inputs, dtype=bool)
            n_not_normed = n_inputs - len(x_mean)
            if n_not_normed > 0:
                on_off_arr[-n_not_normed:] = False
        if int(on_off_arr.sum()) == len(x_mean):
            full_mu = np.zeros(n_inputs, dtype=np.float64)
            full_sigma = np.ones(n_inputs, dtype=np.float64)
            full_mu[on_off_arr] = x_mean
            full_sigma[on_off_arr] = x_std
            x_mean = full_mu
            x_std = full_sigma
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Normalisation incoherente : mu shape={x_mean.shape}, "
                    f"input_cols={n_inputs}. Reentrainez le modele."
                ),
            )

    # Normalize and predict
    x_std_safe = np.where(x_std == 0, 1.0, x_std)
    X_norm = (X - x_mean) / x_std_safe
    # B4: predict can take seconds on validation data sets - offload.
    # P4.7: route through apply_model_tta. With tta_iter=1 (the default) the
    # function calls model.predict exactly once with no noise, so behaviour is
    # bit-identical to the legacy path. Larger tta_iter averages predictions
    # over several noisy forward passes for smoother inference.
    from ..services.ml.evaluation_pipeline import apply_model_tta
    y_pred_norm = (
        await asyncio.to_thread(
            apply_model_tta,
            model,
            X_norm.astype(np.float32),
            tta_iter,
            tta_noise_std,
        )
    ).flatten()
    y_pred = y_pred_norm * y_std + y_mean

    # Compute basic API metrics. The HD/LD split (hd_rmse/ld_rmse) must be
    # applied on the observed traffic flow (TMJOBCTV), not on y_true — when
    # the model predicts TxPen (a 0..1 rate), the default threshold of 1000
    # would otherwise classify every row as low-density and produce
    # hd_rmse=None. TMJABCTV is the legacy alias under which val_renames
    # stores TMJOBCTV; prefer the modern name when both exist.
    # Pour HD/LD split : prend la colonne capteur la plus appropriee selon
    # le kind. TV/PL : TMJOBCTV / TMJABCTV (daily). HPM/HPS : compteur horaire
    # (TMJOBCTV_HPM / TMJOBCTV_HPS) — sinon le threshold daily (1000) classe
    # tout en LD et hd_rmse/ld_rmse perdent leur sens.
    _flow_candidates = ("TMJOBCTV", "TMJABCTV")
    if training_config and isinstance(training_config, dict):
        _kind_for_flow = str(training_config.get("model_kind") or "").upper()
        if _kind_for_flow == "HPM":
            _flow_candidates = ("TMJOBCTV_HPM",) + _flow_candidates
        elif _kind_for_flow == "HPS":
            _flow_candidates = ("TMJOBCTV_HPS",) + _flow_candidates
    flows: np.ndarray | None = None
    for flow_col in _flow_candidates:
        if flow_col in sub.columns:
            flows = pd.to_numeric(sub[flow_col], errors="coerce").to_numpy(dtype=np.float64)
            break
    if flows is None:
        logger.warning(
            "HD/LD split disabled: aucune colonne capteur (%s) trouvee dans les donnees de validation",
            "/".join(_flow_candidates),
        )
    metrics = _compute_metrics(y_true, y_pred, body.high_flow_threshold, flows=flows)

    # --- Build enriched DataFrame for the HTML report ---
    # Resolve the model kind. Priority order:
    #   1. training_config.model_kind  (written by training.py for HPM/HPS)
    #   2. output_cols[0]              (legacy detection: "pl"/"hpm"/"hps")
    # Defaults to TV.
    _model_kind = "TV"
    _is_pl_model = False
    if training_config and isinstance(training_config, dict):
        _kind_in_cfg = str(training_config.get("model_kind") or "").upper()
        if _kind_in_cfg in ("TV", "PL", "HPM", "HPS"):
            _model_kind = _kind_in_cfg
        else:
            _out_cols = training_config.get("output_cols") or []
            _out0 = str(_out_cols[0]).lower() if _out_cols else ""
            if "hpm" in _out0:
                _model_kind = "HPM"
            elif "hps" in _out0:
                _model_kind = "HPS"
            elif "pl" in _out0:
                _model_kind = "PL"
        _is_pl_model = _model_kind == "PL"
    _is_hourly_kind = _model_kind in ("HPM", "HPS")

    report_df = sub.copy()
    report_df["TP_redressement"] = pd.to_numeric(y_pred, errors="coerce")

    if _is_hourly_kind:
        # ── HPM / HPS branch ──
        # Predit : HPM_FCDr / HPS_FCDr = FCD_HPM_TV / TP_redressement * 100
        # Reference compteur : TMJOBCTV_HPM / TMJOBCTV_HPS (jamais TMJOBCTV daily).
        # Unite : v/h. Pas de variante PL pour ces kinds.
        from ..services.ml.types import CONFIGS as _CONFIGS
        _hourly_cfg = _CONFIGS[_model_kind]
        _fcd_col_h = _hourly_cfg.fcd_col                   # FCD_HPM_TV / FCD_HPS_TV
        _ref_col_h = _hourly_cfg.eval_reference_col         # TMJOBCTV_HPM / TMJOBCTV_HPS
        _pred_col_h = _hourly_cfg.eval_predicted_col        # HPM_FCDr / HPS_FCDr

        if _fcd_col_h and _fcd_col_h in report_df.columns:
            report_df[_pred_col_h] = (
                pd.to_numeric(report_df[_fcd_col_h], errors="coerce")
                / report_df["TP_redressement"]
                * 100.0
            )
        else:
            report_df[_pred_col_h] = pd.to_numeric(y_pred, errors="coerce")

        if _ref_col_h in report_df.columns:
            report_df[_ref_col_h] = pd.to_numeric(report_df[_ref_col_h], errors="coerce")

        if _pred_col_h in report_df.columns and _ref_col_h in report_df.columns:
            report_df["Erreur absolue"] = (
                report_df[_pred_col_h] - report_df[_ref_col_h]
            ).abs().round(1)
            denom = report_df[_ref_col_h].replace([np.inf, -np.inf], np.nan)
            report_df["Erreur %"] = (
                report_df["Erreur absolue"] / denom * 100.0
            ).replace([np.inf, -np.inf], np.nan)
        else:
            report_df["Erreur absolue"] = np.nan
            report_df["Erreur %"] = np.nan

        # GEH universel — formule unique sqrt(2*(M-C)**2/(M+C)). En pointe
        # horaire les volumes sont DEJA horaires : pas de division par 24.
        if _pred_col_h in report_df.columns and _ref_col_h in report_df.columns:
            a = pd.to_numeric(report_df[_pred_col_h], errors="coerce")
            b = pd.to_numeric(report_df[_ref_col_h], errors="coerce")
            with np.errstate(divide="ignore", invalid="ignore"):
                geh_vals = np.sqrt(2.0 * (a - b) ** 2 / (a + b))
            report_df["GEH"] = pd.to_numeric(geh_vals, errors="coerce").replace([np.inf, -np.inf], np.nan)

        # lat / lon
        if "__lat" in report_df.columns and "lat" not in report_df.columns:
            report_df["lat"] = pd.to_numeric(report_df["__lat"], errors="coerce")
        if "__lon" in report_df.columns and "lon" not in report_df.columns:
            report_df["lon"] = pd.to_numeric(report_df["__lon"], errors="coerce")

        # Tolerance bandes recalibrees pour v/h (cf. _HPM_HPS_TOL_BINS).
        if _pred_col_h in report_df.columns and _ref_col_h in report_df.columns:
            report_df = _add_tolerance_columns_HPM_HPS(report_df, _hourly_cfg)
    elif _is_pl_model:
        # ── PL branch ── DPL = TMJOFCDPL / TP_redressement * 100, reference = TMJOBCPL.
        from ..services.ml.types import PL_CONFIG
        tmja_fcd_col = None
        for cand in ("TMJAFCDPL", "TMJOFCDPL"):
            if cand in report_df.columns:
                tmja_fcd_col = cand
                break
        if tmja_fcd_col is not None:
            report_df["DPL"] = (
                pd.to_numeric(report_df[tmja_fcd_col], errors="coerce")
                / report_df["TP_redressement"]
                * 100.0
            )
        else:
            report_df["DPL"] = pd.to_numeric(y_pred, errors="coerce")

        # val_renames stores the PL reference as the legacy alias `TMJABCPL`.
        # PL_CONFIG.eval_reference_col is the modern `TMJOBCPL`; the rest of
        # the PL report (and add_tolerance_columns) reads that exact name —
        # so mirror the alias under both names when only the legacy one is
        # present. Without this, Erreur/GEH/Tolerance_IN_OUT stay all-NaN
        # and the report card shows tol 0/0 (or, when only two rows happen
        # to satisfy the bands fallback, the 2/2 artefact we saw).
        if "TMJOBCPL" not in report_df.columns and "TMJABCPL" in report_df.columns:
            report_df["TMJOBCPL"] = report_df["TMJABCPL"]
        if "TMJOBCPL" in report_df.columns:
            report_df["TMJOBCPL"] = pd.to_numeric(report_df["TMJOBCPL"], errors="coerce")

        # Erreur absolue & Erreur % vs TMJOBCPL
        if "DPL" in report_df.columns and "TMJOBCPL" in report_df.columns:
            report_df["Erreur absolue"] = (report_df["DPL"] - report_df["TMJOBCPL"]).abs().round(1)
            denom = report_df["TMJOBCPL"].replace([np.inf, -np.inf], np.nan)
            report_df["Erreur %"] = (
                report_df["Erreur absolue"] / denom * 100.0
            ).replace([np.inf, -np.inf], np.nan)
        else:
            report_df["Erreur absolue"] = np.nan
            report_df["Erreur %"] = np.nan

        # GEH (daily flows, no /24 — matches P0.1 fix in evaluation_pipeline)
        if "DPL" in report_df.columns and "TMJOBCPL" in report_df.columns:
            a = report_df["DPL"]
            b = report_df["TMJOBCPL"]
            with np.errstate(divide="ignore", invalid="ignore"):
                geh_vals = np.sqrt(2.0 * (a - b) ** 2 / (a + b))
            report_df["GEH"] = pd.to_numeric(geh_vals, errors="coerce").replace([np.inf, -np.inf], np.nan)

        # lat/lon
        if "__lat" in report_df.columns and "lat" not in report_df.columns:
            report_df["lat"] = pd.to_numeric(report_df["__lat"], errors="coerce")
        if "__lon" in report_df.columns and "lon" not in report_df.columns:
            report_df["lon"] = pd.to_numeric(report_df["__lon"], errors="coerce")

        # Tolerance columns using PL_CONFIG (produces DPLmin, DPLmax, Tolerance_IN_OUT)
        if "DPL" in report_df.columns and "TMJOBCPL" in report_df.columns:
            report_df = _add_tolerance_columns(report_df, PL_CONFIG)
    else:
        # ── TV branch (unchanged — TV model works in production) ──
        # TVr = TMJAFCDTV / TP_redressement * 100
        tmja_fcd_col = None
        for cand in ("TMJAFCDTV", "TMJATV"):
            if cand in report_df.columns:
                tmja_fcd_col = cand
                break
        if tmja_fcd_col is not None:
            report_df["TVr"] = (
                pd.to_numeric(report_df[tmja_fcd_col], errors="coerce")
                / report_df["TP_redressement"]
                * 100.0
            )
        else:
            report_df["TVr"] = pd.to_numeric(y_pred, errors="coerce")

        if "TMJABCTV" in report_df.columns:
            report_df["TMJABCTV"] = pd.to_numeric(report_df["TMJABCTV"], errors="coerce")

        if "TVr" in report_df.columns and "TMJABCTV" in report_df.columns:
            report_df["Erreur absolue"] = (report_df["TVr"] - report_df["TMJABCTV"]).abs().round(1)
            denom = report_df["TMJABCTV"].replace([np.inf, -np.inf], np.nan)
            report_df["Erreur %"] = (
                report_df["Erreur absolue"] / denom * 100.0
            ).replace([np.inf, -np.inf], np.nan)
        else:
            report_df["Erreur absolue"] = np.nan
            report_df["Erreur %"] = np.nan

        if "TVr" in report_df.columns and "TMJABCTV" in report_df.columns:
            a = report_df["TVr"] / 24.0
            b = report_df["TMJABCTV"] / 24.0
            with np.errstate(divide="ignore", invalid="ignore"):
                geh_vals = np.sqrt(2.0 * (a - b) ** 2 / (a + b))
            report_df["GEH"] = pd.to_numeric(geh_vals, errors="coerce").replace([np.inf, -np.inf], np.nan)

        if "__lat" in report_df.columns and "lat" not in report_df.columns:
            report_df["lat"] = pd.to_numeric(report_df["__lat"], errors="coerce")
        if "__lon" in report_df.columns and "lon" not in report_df.columns:
            report_df["lon"] = pd.to_numeric(report_df["__lon"], errors="coerce")

        if "TVr" in report_df.columns and "TMJABCTV" in report_df.columns:
            report_df = _add_tolerance_columns(report_df)

    # ── HPM/HPS: realign MetricsResult on redressed v/h values (fix v2). ────
    # The initial _compute_metrics() call above operated on the raw TxPen
    # output (y_true/y_pred in 0..100 % scale). For peak-hour kinds the
    # business-meaningful metric is the comparison between the redressed
    # hourly volume (HPM_FCDr / HPS_FCDr, v/h) and the hourly counter
    # (TMJOBCTV_HPM / HPS). The HTML report card already does this — re-
    # building MetricsResult here keeps the API payload coherent with the
    # report (no more "API says 100%, report says 27.9%" divergence).
    # TV/PL paths are untouched: their target output_col is already the
    # daily v/j volume after the standard FCD/TxPen pipeline, so the
    # original metrics object is correct as-is.
    if _is_hourly_kind:
        from ..services.ml.types import CONFIGS as _CONFIGS_M
        _hcfg = _CONFIGS_M[_model_kind]
        _pred_col_m = _hcfg.eval_predicted_col   # HPM_FCDr / HPS_FCDr
        _ref_col_m = _hcfg.eval_reference_col    # TMJOBCTV_HPM / TMJOBCTV_HPS
        if _pred_col_m in report_df.columns and _ref_col_m in report_df.columns:
            _obs_vh = pd.to_numeric(report_df[_ref_col_m], errors="coerce").to_numpy(dtype=np.float64)
            _pred_vh = pd.to_numeric(report_df[_pred_col_m], errors="coerce").to_numpy(dtype=np.float64)
            # HPM/HPS HD/LD threshold lives on the kind config (80 v/h by default).
            _hourly_thr = float(getattr(_hcfg, "default_high_flow_threshold", 80.0) or 80.0)
            metrics = _compute_metrics_hourly(_obs_vh, _pred_vh, _hourly_thr)
            logger.info(
                "Metrics realigned on %s/%s (v/h) for %s: RMSE=%.2f GEH<5=%.2f%% n=%d",
                _pred_col_m, _ref_col_m, _model_kind,
                metrics.rmse, metrics.geh_pct_below_5, metrics.n_samples,
            )
        else:
            logger.warning(
                "%s/%s missing from report_df — MetricsResult left on TxPen scale (API/report may diverge)",
                _pred_col_m, _ref_col_m,
            )

    # P1.1 - Bootstrap CI95 for tol_in_pct, p80 (err_rel), R-squared.
    # Skipped when bootstrap_iter == 0 (opt-out) or n < 30 (handled inside
    # bootstrap_ci95). The metric pipeline above does NOT apply any
    # flag_comptage / flag_y2025 reweighting today, so we pass weights=None
    # - the bootstrap stays consistent with the un-bootstrapped metric.
    metrics_ci95: dict[str, list[float] | None] | None = None
    if bootstrap_iter > 0:
        metrics_ci95 = {}

        # R-squared - bootstrap on (y_true, y_pred) directly.
        r2_res = await asyncio.to_thread(
            bootstrap_ci95, _metric_r2, y_true, y_pred, None, bootstrap_iter, 1750,
        )
        metrics_ci95["r2"] = (
            [round(r2_res[1], 6), round(r2_res[2], 6)] if r2_res else None
        )

        # p80 of relative error - bootstrap on the (TMJABCTV, TVr) pair so it
        # matches the reported err_rel_p80. Fall back to (y_true, y_pred)
        # when the report columns aren't available (matches the report's own
        # fallback path).
        if (
            "TMJABCTV" in report_df.columns and "TVr" in report_df.columns
        ):
            obs_p80 = pd.to_numeric(report_df["TMJABCTV"], errors="coerce").to_numpy(
                dtype=np.float64
            )
            pred_p80 = pd.to_numeric(report_df["TVr"], errors="coerce").to_numpy(
                dtype=np.float64
            )
            mask = np.isfinite(obs_p80) & np.isfinite(pred_p80)
            obs_p80, pred_p80 = obs_p80[mask], pred_p80[mask]
        else:
            obs_p80, pred_p80 = y_true, y_pred
        p80_res = await asyncio.to_thread(
            bootstrap_ci95,
            _metric_p80_err_rel,
            obs_p80,
            pred_p80,
            None,
            bootstrap_iter,
            1750,
        )
        metrics_ci95["p80"] = (
            [round(p80_res[1], 4), round(p80_res[2], 4)] if p80_res else None
        )

        # tol_in_pct - bootstrap on Tolerance_IN_OUT codes (1/2/3). We pass
        # the codes as ``observed`` and a dummy zero array as ``predicted``;
        # the adapter only reads ``observed`` (see _metric_tol_in_pct).
        if "Tolerance_IN_OUT" in report_df.columns:
            tol_codes = pd.to_numeric(
                report_df["Tolerance_IN_OUT"], errors="coerce"
            ).to_numpy(dtype=np.float64)
            tol_codes = tol_codes[~np.isnan(tol_codes)]
            if tol_codes.size > 0:
                dummy = np.zeros_like(tol_codes)
                tol_res = await asyncio.to_thread(
                    bootstrap_ci95,
                    _metric_tol_in_pct,
                    tol_codes,
                    dummy,
                    None,
                    bootstrap_iter,
                    1750,
                )
                metrics_ci95["tol_in_pct"] = (
                    [round(tol_res[1], 2), round(tol_res[2], 2)] if tol_res else None
                )
            else:
                metrics_ci95["tol_in_pct"] = None
        else:
            metrics_ci95["tol_in_pct"] = None

    # P1.2 — Stratified metrics per TMJOBCTV bucket. Purely additive: the
    # global metrics above are untouched. When neither TMJOBCTV nor its
    # legacy alias TMJABCTV is available we log a warning and persist an
    # empty list (front-end renders "stratification indisponible").
    metrics_by_tmja_bucket: list[dict[str, Any]] = []
    strat_flow_col: str | None = None
    for _cand in ("TMJOBCTV", "TMJABCTV"):
        if _cand in report_df.columns:
            strat_flow_col = _cand
            break
    if strat_flow_col is None:
        logger.warning(
            "TMJA bucket stratification disabled: ni TMJOBCTV ni TMJABCTV "
            "trouve dans les donnees de validation"
        )
    else:
        try:
            metrics_by_tmja_bucket = _stratify_by_tmja(
                report_df, strat_flow_col, y_true, y_pred,
            )
        except Exception as exc:  # noqa: BLE001 — non-blocking by design
            logger.warning(
                "TMJA stratification failed (non-blocking): %s", exc,
            )
            metrics_by_tmja_bucket = []

    # P4.1 — Calibration data (obs, pred). Always computed because y_true /
    # y_pred are guaranteed non-empty at this point (early-exit above when
    # len(sub) < 2). Stored under a stable session key so the cached
    # /report/{session_id} endpoint can replay the section verbatim.
    calibration_data: dict[str, Any] | None = None
    try:
        calibration_data = _compute_calibration_data(y_true, y_pred)
    except Exception as exc:  # noqa: BLE001 — non-blocking by design
        logger.warning("Calibration data computation failed (non-blocking): %s", exc)
        calibration_data = None

    # P4.2 — Residual boxplot by functional_class. Gracefully empty when
    # neither ``functional_class`` nor ``fc_*`` one-hot columns exist.
    residuals_by_fc: list[dict[str, Any]] = []
    try:
        residuals_by_fc = _compute_residuals_by_fc(report_df, y_true, y_pred)
        if not residuals_by_fc:
            logger.debug(
                "Residuals by FC skipped: functional_class column absent "
                "from validation data."
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Residuals-by-FC computation failed (non-blocking): %s", exc)
        residuals_by_fc = []

    # P4.3 — Annual drift. Reads year_mapped + the inverse year_value_mapping
    # (body override > training_config) so the table can show 2019..2025
    # labels instead of the raw encoded value.
    drift_by_year: list[dict[str, Any]] = []
    try:
        _year_mapping = (
            body.year_value_mapping
            or (training_config or {}).get("year_value_mapping")
            or {}
        )
        drift_by_year = _compute_drift_by_year(
            report_df, y_true, y_pred, year_value_mapping=_year_mapping,
        )
        if not drift_by_year:
            logger.debug(
                "Drift by year skipped: year_mapped absent or no year has "
                "at least %d samples.", _DRIFT_MIN_SAMPLES,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Drift-by-year computation failed (non-blocking): %s", exc)
        drift_by_year = []

    # Build sensitivity analysis section. The function defaults to TV_CONFIG
    # for back-compat; pass PL_CONFIG when the model targets TxPenPL so the
    # chart shows DPL ~ feature instead of TVr ~ feature. For HPM/HPS we use
    # the dedicated HPM/HPS sensitivity builder (axis = v/h, predit = HPM_FCDr / HPS_FCDr).
    sensitivity_html = None
    try:
        if model is not None and input_cols:
            mu_x_arr = np.array(x_mean, dtype=np.float64)
            s_x_arr = np.array(x_std, dtype=np.float64)
            mu_y_arr = np.array(y_mean, dtype=np.float64)
            s_y_arr = np.array(y_std, dtype=np.float64)
            from ..services.ml.types import CONFIGS as _CONFIGS_S
            from ..services.ml.types import PL_CONFIG, TV_CONFIG
            if _is_hourly_kind:
                sensitivity_html = _build_sensitivity_section_html_HPM_HPS(
                    df=report_df, model=model,
                    mu_x=mu_x_arr, s_x=s_x_arr, mu_y=mu_y_arr, s_y=s_y_arr,
                    input_cols=input_cols, type_config=_CONFIGS_S[_model_kind],
                )
            else:
                _sens_type_config = PL_CONFIG if _is_pl_model else TV_CONFIG
                sensitivity_html = _build_sensitivity_section_html(
                    df=report_df, model=model,
                    mu_x=mu_x_arr, s_x=s_x_arr, mu_y=mu_y_arr, s_y=s_y_arr,
                    input_cols=input_cols, type_config=_sens_type_config,
                )
    except Exception as exc:
        logger.warning("Sensitivity analysis failed (non-blocking): %s", exc)
        sensitivity_html = None

    # Generate HTML report — dispatch by model kind.
    #   TV  -> generate_html_report_tv         (daily, v/j, TVr / TMJOBCTV)
    #   PL  -> generate_html_report_pl         (daily, v/j, DPL / TMJOBCPL)
    #   HPM -> _generate_html_report_HPM       (h08-h09, v/h, HPM_FCDr / TMJOBCTV_HPM)
    #   HPS -> _generate_html_report_HPS       (h17-h18, v/h, HPS_FCDr / TMJOBCTV_HPS)
    if _model_kind == "HPM":
        report_html = _generate_html_report_HPM(
            metrics=metrics, model_name=model_name, training_config=training_config,
            y_true=y_true, y_pred=y_pred, df=report_df,
            sensitivity_html=sensitivity_html, metrics_ci95=metrics_ci95,
            metrics_by_tmja_bucket=metrics_by_tmja_bucket,
            calibration_data=calibration_data, residuals_by_fc=residuals_by_fc,
            drift_by_year=drift_by_year,
        )
    elif _model_kind == "HPS":
        report_html = _generate_html_report_HPS(
            metrics=metrics, model_name=model_name, training_config=training_config,
            y_true=y_true, y_pred=y_pred, df=report_df,
            sensitivity_html=sensitivity_html, metrics_ci95=metrics_ci95,
            metrics_by_tmja_bucket=metrics_by_tmja_bucket,
            calibration_data=calibration_data, residuals_by_fc=residuals_by_fc,
            drift_by_year=drift_by_year,
        )
    elif _model_kind == "PL":
        report_html = generate_html_report_pl(
            metrics=metrics, model_name=model_name, training_config=training_config,
            y_true=y_true, y_pred=y_pred, df=report_df,
            sensitivity_html=sensitivity_html, metrics_ci95=metrics_ci95,
            metrics_by_tmja_bucket=metrics_by_tmja_bucket,
            calibration_data=calibration_data, residuals_by_fc=residuals_by_fc,
            drift_by_year=drift_by_year,
        )
    else:
        report_html = generate_html_report_tv(
            metrics=metrics, model_name=model_name, training_config=training_config,
            y_true=y_true, y_pred=y_pred, df=report_df,
            sensitivity_html=sensitivity_html, metrics_ci95=metrics_ci95,
            metrics_by_tmja_bucket=metrics_by_tmja_bucket,
            calibration_data=calibration_data, residuals_by_fc=residuals_by_fc,
            drift_by_year=drift_by_year,
        )

    # Store in session
    session_manager.store_data(body.session_id, "eval_metrics", metrics.model_dump())
    session_manager.store_data(body.session_id, "eval_y_true", y_true.tolist())
    session_manager.store_data(body.session_id, "eval_y_pred", y_pred.tolist())
    session_manager.store_data(body.session_id, "eval_report_html", report_html)
    session_manager.store_data(body.session_id, "eval_model_name", model_name)
    # P4.7 — persist TTA parameters so the report (and any downstream
    # auditing) can show whether TTA was used and with what intensity.
    tta_params = {"n_iter": int(tta_iter), "noise_std": float(tta_noise_std)}
    session_manager.store_data(body.session_id, "eval_tta", tta_params)
    if metrics_ci95 is not None:
        session_manager.store_data(body.session_id, "eval_metrics_ci95", metrics_ci95)
    # P1.2 — always persist, even when empty list, so consumers can rely
    # on the key existing after a successful /run.
    session_manager.store_data(
        body.session_id, "metrics_by_tmja_bucket", metrics_by_tmja_bucket,
    )
    # P4.1/4.2/4.3 — persist the new sections so /report/{session_id}
    # replays them without recomputing. ``calibration_data`` may be None
    # (empty obs/pred); store None explicitly to keep the key shape stable.
    session_manager.store_data(
        body.session_id, "calibration_data", calibration_data,
    )
    session_manager.store_data(
        body.session_id, "residuals_by_fc", residuals_by_fc,
    )
    session_manager.store_data(
        body.session_id, "drift_by_year", drift_by_year,
    )

    # P1.4 — persist per-model evaluation artifacts so /api/evaluation/compare
    # can pair predictions from two different runs against the SAME observation
    # vector (McNemar test is paired). Stored under a model-namespaced key.
    session_manager.store_data(
        body.session_id,
        f"eval_artifact:{model_name}",
        {
            "y_true": y_true.tolist(),
            "y_pred": y_pred.tolist(),
            # P4.7 — track the TTA settings used for THIS artifact so paired
            # comparisons (McNemar) can flag when two runs used different
            # inference regimes.
            "tta": tta_params,
        },
    )
    # Maintain a roster of evaluated models in this session so consumers can
    # enumerate them without scanning every key in the backend.
    roster = session_manager.get_data(body.session_id, "eval_model_roster", []) or []
    if model_name not in roster:
        roster = [*roster, model_name]
        session_manager.store_data(body.session_id, "eval_model_roster", roster)

    logger.info(
        "Evaluation done: session=%s model=%s RMSE=%.4f R2=%.4f GEH<5=%.1f%% "
        "bootstrap_iter=%d tta_iter=%d tta_noise_std=%.4f",
        body.session_id, model_name, metrics.rmse, metrics.r_squared, metrics.geh_pct_below_5,
        bootstrap_iter, tta_iter, tta_noise_std,
    )

    return EvalResponse(
        session_id=body.session_id,
        model_name=model_name,
        metrics=metrics,
        report_url=f"/api/evaluation/report/{body.session_id}",
        metrics_ci95=metrics_ci95,
        metrics_by_tmja_bucket=metrics_by_tmja_bucket,
        calibration_data=calibration_data,
        residuals_by_fc=residuals_by_fc,
        drift_by_year=drift_by_year,
    )


@router.get("/report/{session_id}", response_model=ReportResponse)
async def get_report(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> ReportResponse:
    """Return the generated HTML evaluation report."""
    session = require_owned_session(session_id, current_user)

    report_html = session_manager.get_data(session_id, "eval_report_html")
    if report_html is None:
        # Fallback: generate a minimal report from stored metrics
        metrics_dict = session_manager.get_data(session_id, "eval_metrics")
        if metrics_dict is None:
            raise HTTPException(status_code=400, detail="Lancez l'evaluation d'abord (/api/evaluation/run).")

        metrics = MetricsResult(**metrics_dict)
        model_name = session_manager.get_data(session_id, "eval_model_name", "modele")
        y_true = np.array(session_manager.get_data(session_id, "eval_y_true", []))
        y_pred = np.array(session_manager.get_data(session_id, "eval_y_pred", []))
        # P1.2 — replay the persisted stratification if available so the
        # regenerated fallback report still shows the bucket table.
        cached_buckets = session_manager.get_data(
            session_id, "metrics_by_tmja_bucket", []
        )
        # P4.1 / P4.2 / P4.3 — replay the new sections from session storage
        # so the cached fallback report has the same shape as the freshly
        # generated one.
        cached_calibration = session_manager.get_data(
            session_id, "calibration_data", None
        )
        cached_residuals_fc = session_manager.get_data(
            session_id, "residuals_by_fc", []
        )
        cached_drift = session_manager.get_data(
            session_id, "drift_by_year", []
        )

        report_html = generate_html_report_tv(
            metrics=metrics,
            model_name=model_name,
            training_config=None,
            y_true=y_true,
            y_pred=y_pred,
            metrics_by_tmja_bucket=cached_buckets,
            calibration_data=cached_calibration,
            residuals_by_fc=cached_residuals_fc,
            drift_by_year=cached_drift,
        )

    return ReportResponse(session_id=session_id, report_html=report_html)


@router.get("/download-model")
async def download_model(
    model_name: str = Query(...),
    model_dir: str = Query(...),
    session_id: str = Query(None),
    current_user: UserRecord = Depends(get_current_user),
) -> StreamingResponse:
    """Download a model folder as a ZIP file."""
    # Security: a model_dir can only be served if it lives under the caller's
    # own session workspace. session_id is required and must be owned by the
    # caller — that prevents user B from downloading user A's trained models.
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id requis.")
    require_owned_session(session_id, current_user)

    # Try the same 4 candidates as /run so the download endpoint stays in
    # sync with the eval resolver. Without this, a model whose files live
    # at the root of model_dir (no run sub-folder) evaluated fine via /run
    # candidate #2 but the download button still 404'd.
    model_dir_path = Path(model_dir)
    candidates: list[Path] = [
        model_dir_path / model_name,
        model_dir_path,
        model_dir_path.parent / model_name,
        model_dir_path / "models" / model_name,
    ]

    def _is_valid_model_dir(p: Path) -> bool:
        if not p.exists() or not p.is_dir():
            return False
        return (p / "model.keras").exists() or (p / "NNarchitecture.json").exists()

    model_path = next((c for c in candidates if _is_valid_model_dir(c)), None)
    if model_path is None:
        tried = " | ".join(str(c) for c in candidates)
        raise HTTPException(
            status_code=404,
            detail=f"Dossier modele introuvable. Chemins tentes : {tried}",
        )

    # Create ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in model_path.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(model_path)
                zf.write(file, arcname)

    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{model_name}.zip"',
        },
    )


# ---------------------------------------------------------------------------
# P1.4 — McNemar paired comparison of two evaluated models
# ---------------------------------------------------------------------------

@router.post("/compare")
async def compare_models_endpoint(
    body: CompareRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Run McNemar test on two previously-evaluated models.

    Both run_a and run_b must have been evaluated via
    POST /api/evaluation/run in the SAME session — the test is paired on
    the per-sensor binary in-tolerance outcome, so the two prediction
    vectors must align element-wise against a shared observation vector.

    Tolerance is expressed in percent of the observed value:
    in_tolerance := |pred - obs| / |obs| <= tolerance_pct / 100.
    """
    require_owned_session(body.session_id, current_user)

    if not (0.0 < body.tolerance_pct <= 100.0):
        raise HTTPException(
            status_code=422,
            detail=(
                f"tolerance_pct doit etre dans (0, 100], recu {body.tolerance_pct}."
            ),
        )
    if body.run_a == body.run_b:
        raise HTTPException(
            status_code=422,
            detail="run_a et run_b doivent etre deux modeles distincts.",
        )

    artifact_a = session_manager.get_data(
        body.session_id, f"eval_artifact:{body.run_a}"
    )
    artifact_b = session_manager.get_data(
        body.session_id, f"eval_artifact:{body.run_b}"
    )

    missing: list[str] = []
    if not artifact_a:
        missing.append(body.run_a)
    if not artifact_b:
        missing.append(body.run_b)
    if missing:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Aucun artefact evaluation trouve pour : {', '.join(missing)}. "
                "Lancez d abord POST /api/evaluation/run pour chacun des modeles "
                "a comparer."
            ),
        )

    y_true_a = np.asarray(artifact_a.get("y_true", []), dtype=np.float64)
    y_pred_a = np.asarray(artifact_a.get("y_pred", []), dtype=np.float64)
    y_true_b = np.asarray(artifact_b.get("y_true", []), dtype=np.float64)
    y_pred_b = np.asarray(artifact_b.get("y_pred", []), dtype=np.float64)

    if y_true_a.shape != y_true_b.shape or y_pred_a.shape != y_pred_b.shape:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Les deux modeles n ont pas ete evalues sur le meme jeu : "
                f"{body.run_a}={y_true_a.shape[0]} obs, "
                f"{body.run_b}={y_true_b.shape[0]} obs. Reevaluez sur le meme "
                "fichier de validation."
            ),
        )
    if y_true_a.size == 0:
        raise HTTPException(
            status_code=422,
            detail="Les artefacts d evaluation sont vides — rien a comparer.",
        )
    # Defensive: the obs vector for paired tests must be element-wise equal.
    # Tiny float drift can creep in via JSON round-trip, hence allclose.
    if not np.allclose(y_true_a, y_true_b, equal_nan=True):
        raise HTTPException(
            status_code=422,
            detail=(
                "Les vecteurs d observations des deux evaluations different. "
                "Le test McNemar exige un appariement strict — reevaluez les "
                "deux modeles sur exactement le meme fichier de validation."
            ),
        )

    from ..services.ml.stats_compare import compare_models

    try:
        result = compare_models(
            obs=y_true_a,
            pred_a=y_pred_a,
            pred_b=y_pred_b,
            tolerance_pct=body.tolerance_pct,
            name_a=body.run_a,
            name_b=body.run_b,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    logger.info(
        "McNemar compare: session=%s a=%s b=%s tol=%.2f%% "
        "method=%s p=%.4g sig=%s verdict=%s",
        body.session_id, body.run_a, body.run_b, body.tolerance_pct,
        result["method"], result["p_value"],
        result["significant_at_0.05"], result["verdict"],
    )
    return result


# ---------------------------------------------------------------------------
# P1.3 — K-fold cross-validation on a trained model
# ---------------------------------------------------------------------------
#
# A single-split evaluation only tells you how a model performs on ONE
# choice of validation set. With k=5 folds we re-train the same architecture
# on 5 different 80/20 partitions of the source data and look at the
# mean ± std of the held-out metrics. A model whose tol_in_pct swings by
# more than ~5 points across folds is fragile, even if its single-split
# score looked impressive.
#
# This endpoint is intentionally slow (k full trainings of the same model)
# and is meant to be triggered manually for the top finalists of a grid
# search — not on every model.

# Wall-clock above which we emit a warning in the server log. Not a hard
# kill — the FastAPI route itself has no timeout, the cancel_event pattern
# is the official way to abort.
_KFOLD_SLOW_WARN_SECONDS = 600.0


def _kfold_resolve_training_config(
    session_id: str, run_name: str, override_dir: str | None,
) -> tuple[dict[str, Any], Path]:
    """Find the ``training_config.json`` for *run_name* under the session
    workspace (or *override_dir* when provided).

    Returns the parsed config dict + the model directory path.
    Raises HTTPException(404) when the model folder cannot be located.
    """
    from ..config import get_settings

    candidates: list[Path] = []
    if override_dir:
        candidates.append(Path(override_dir) / run_name)
        candidates.append(Path(override_dir))  # caller passed the run dir itself
    settings = get_settings()
    workspace_models = Path(settings.WORKSPACE_ROOT) / session_id / "models"
    candidates.append(workspace_models / run_name)

    for cand in candidates:
        cfg_file = cand / "training_config.json"
        if cfg_file.exists():
            try:
                return json.loads(cfg_file.read_text(encoding="utf-8")), cand
            except (OSError, json.JSONDecodeError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"training_config.json illisible pour {run_name}: {exc}",
                )

    raise HTTPException(
        status_code=404,
        detail=(
            f"Modele '{run_name}' introuvable. Cherche dans : "
            + ", ".join(str(c) for c in candidates)
        ),
    )


@router.post("/kfold")
async def kfold_cross_validation(
    body: KFoldRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> dict[str, Any]:
    """Run K-fold cross-validation on a previously-trained model.

    The endpoint re-trains the model k times on k different 80/20 (for k=5)
    folds of the session's training DataFrame, using the *same*
    hyper-parameters as the original training run. Each fold reports the
    held-out ``tol_in_pct``, ``p80`` (err_rel_p80) and ``r2``. The summary
    gives the mean and unbiased std across folds — a low std means the
    architecture is robust to data sampling, a high std means the metric
    is unreliable.

    Cancellation: the standard `asyncio.CancelledError` mechanism applies.
    A shared `threading.Event` is also propagated into the training loop
    so TF stops between epochs / folds.

    Status codes:
        200 — OK, ``{k, folds, summary, cancelled, duration_s}``
        401/403 — handled by ``require_owned_session`` upstream
        404 — model directory not found
        422 — k out of bounds (Pydantic) or bad request body
        400 — session has no learning_df, or training_config invalid
    """
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    import time as _time

    require_owned_session(body.session_id, current_user)

    # ──────────────────────────────────────────────────────────────────────
    # 1. Locate the training config + parse hyper-parameters
    # ──────────────────────────────────────────────────────────────────────
    training_config, model_dir = _kfold_resolve_training_config(
        body.session_id, body.run_name, body.model_dir,
    )
    if not training_config.get("input_cols"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"training_config.json incomplet pour {body.run_name} "
                "(input_cols manquant). Reentrainez le modele."
            ),
        )

    # ──────────────────────────────────────────────────────────────────────
    # 2. Get the source training DataFrame from the session
    # ──────────────────────────────────────────────────────────────────────
    session = session_manager.get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session expiree.")
    learning_df = session_manager.get_data(body.session_id, "learning_df")
    if learning_df is None or not isinstance(learning_df, pd.DataFrame) or learning_df.empty:
        raise HTTPException(
            status_code=400,
            detail=(
                "Pas de DataFrame d'apprentissage dans la session. "
                "Retournez a l'etape Donnees et revalidez le mapping."
            ),
        )

    # ──────────────────────────────────────────────────────────────────────
    # 3. Determine the model type (TV / PL / HPM / HPS) from training_config.
    # Priority : training_config.model_kind > output_cols[0] heuristic.
    # ──────────────────────────────────────────────────────────────────────
    from ..services.ml.types import CONFIGS as _KFOLD_CONFIGS
    from ..services.ml.types import PL_CONFIG, TV_CONFIG

    _kind_str = str(training_config.get("model_kind") or "").upper()
    if _kind_str in _KFOLD_CONFIGS:
        type_config = _KFOLD_CONFIGS[_kind_str]
    else:
        output_cols = training_config.get("output_cols") or []
        target = (output_cols[0] if output_cols else "TxPen").lower()
        if "hpm" in target:
            type_config = _KFOLD_CONFIGS["HPM"]
        elif "hps" in target:
            type_config = _KFOLD_CONFIGS["HPS"]
        elif "pl" in target:
            type_config = PL_CONFIG
        else:
            type_config = TV_CONFIG

    # ──────────────────────────────────────────────────────────────────────
    # 4. Run the k-fold loop in a worker thread with a cancellation event.
    # ──────────────────────────────────────────────────────────────────────
    import threading as _threading

    cancel_event = _threading.Event()
    started = _time.time()

    def _runner() -> dict[str, Any]:
        # Lazy import — pulls heavy TF state.
        from ..services.ml.kfold import kfold_train_eval

        return kfold_train_eval(
            df=learning_df,
            training_config=training_config,
            type_config=type_config,
            k=body.k,
            shuffle_seed=body.shuffle_seed,
            cancel_event=cancel_event,
        )

    try:
        result = await asyncio.to_thread(_runner)
    except asyncio.CancelledError:
        cancel_event.set()
        # Best-effort: let the thread observe the flag before re-raising.
        await asyncio.sleep(0)
        logger.warning(
            "kfold cancelled: session=%s run=%s", body.session_id, body.run_name,
        )
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "kfold failed: session=%s run=%s err=%s",
            body.session_id, body.run_name, exc,
        )
        raise HTTPException(status_code=500, detail=f"K-fold a echoue : {exc}")

    duration_s = _time.time() - started
    if duration_s > _KFOLD_SLOW_WARN_SECONDS:
        logger.warning(
            "kfold slow: session=%s run=%s k=%d duration=%.1fs > %.0fs",
            body.session_id, body.run_name, body.k, duration_s,
            _KFOLD_SLOW_WARN_SECONDS,
        )

    # Persist for downstream consumers (UI panel, reports).
    try:
        session_manager.store_data(
            body.session_id, f"kfold_result:{body.run_name}", result,
        )
    except Exception:  # noqa: BLE001 — non-fatal
        logger.exception(
            "Failed to persist kfold result for session=%s run=%s",
            body.session_id, body.run_name,
        )

    logger.info(
        "kfold done: session=%s run=%s k=%d folds_returned=%d duration=%.1fs",
        body.session_id, body.run_name, body.k,
        len(result.get("folds") or []), duration_s,
    )

    return {
        **result,
        "run_name": body.run_name,
        "model_dir": str(model_dir),
        "duration_s": round(duration_s, 2),
    }
