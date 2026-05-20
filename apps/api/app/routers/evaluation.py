"""Evaluation router — upload validation data, run model evaluation, generate HTML report, download model."""

from __future__ import annotations

import asyncio
import html as _html
import io
import json
import logging
import math
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])

DEFAULT_HIGH_FLOW_THRESHOLD = 1000.0


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


# ---------------------------------------------------------------------------
# P1.1 - Bootstrap CI95 on tol_in, p80, R-squared
# ---------------------------------------------------------------------------

# Bootstrap is only meaningful for moderately-sized samples - under this
# threshold the percentile interval is too noisy to be informative.
_BOOTSTRAP_MIN_SAMPLES = 30


def bootstrap_ci95(
    metric_fn,
    observed: np.ndarray,
    predicted: np.ndarray,
    weights: np.ndarray | None = None,
    n_iter: int = 1000,
    seed: int = 1750,
) -> tuple[float, float, float] | None:
    """Compute the bootstrap mean and 95% percentile CI of ``metric_fn``.

    Parameters
    ----------
    metric_fn
        Callable ``(obs, pred, weights) -> float``. ``weights`` may be ``None``.
    observed, predicted
        1D arrays of equal length.
    weights
        Optional per-sample weights (e.g. ``flag_comptage`` / ``flag_y2025``).
        When provided, resampled in lockstep with ``observed`` / ``predicted``.
    n_iter
        Number of bootstrap resamples (default 1000).
    seed
        RNG seed for reproducibility (project convention: 1750).

    Returns
    -------
    ``(mean, ci_low, ci_high)`` where ``ci_low`` / ``ci_high`` are the 2.5th /
    97.5th percentiles across resamples. Returns ``None`` when ``observed`` has
    fewer than ``_BOOTSTRAP_MIN_SAMPLES`` rows (bootstrap unreliable on tiny
    samples) or when no finite metric value could be computed.
    """
    obs = np.asarray(observed, dtype=np.float64).ravel()
    pred = np.asarray(predicted, dtype=np.float64).ravel()
    n = obs.shape[0]
    if n < _BOOTSTRAP_MIN_SAMPLES or pred.shape[0] != n:
        return None
    if n_iter < 1:
        return None

    w = None
    if weights is not None:
        w = np.asarray(weights, dtype=np.float64).ravel()
        if w.shape[0] != n:
            w = None  # mismatched weights -> drop them, don't crash

    rng = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(int(n_iter)):
        idx = rng.integers(0, n, size=n)
        obs_b = obs[idx]
        pred_b = pred[idx]
        w_b = w[idx] if w is not None else None
        try:
            v = float(metric_fn(obs_b, pred_b, w_b))
        except Exception:
            continue
        if not math.isfinite(v):
            continue
        values.append(v)

    if not values:
        return None

    arr = np.asarray(values, dtype=np.float64)
    mean = float(np.mean(arr))
    ci_low = float(np.percentile(arr, 2.5))
    ci_high = float(np.percentile(arr, 97.5))
    return mean, ci_low, ci_high


# --- Metric function adapters (signature: (obs, pred, w) -> float) ---

def _metric_r2(obs: np.ndarray, pred: np.ndarray, w: np.ndarray | None) -> float:
    """R-squared (coefficient of determination). Weights, when provided, scale
    the squared residuals and the centred variance consistently."""
    residuals = obs - pred
    if w is not None and w.sum() > 0:
        wsum = float(w.sum())
        mean_obs = float(np.sum(w * obs) / wsum)
        ss_res = float(np.sum(w * residuals ** 2))
        ss_tot = float(np.sum(w * (obs - mean_obs) ** 2))
    else:
        ss_res = float(np.sum(residuals ** 2))
        ss_tot = float(np.sum((obs - np.mean(obs)) ** 2))
    if ss_tot <= 0:
        return 0.0
    return 1.0 - ss_res / ss_tot


def _metric_p80_err_rel(
    obs: np.ndarray, pred: np.ndarray, w: np.ndarray | None
) -> float:
    """80th percentile of the absolute relative error |obs-pred|/obs * 100,
    matching ``compute_flow_metrics``'s ``err_rel_p80``. Weights are accepted
    for API symmetry but the percentile is computed un-weighted (consistent
    with the un-bootstrapped report value)."""
    del w  # unused - kept for signature compatibility
    nonzero = obs != 0
    if not nonzero.any():
        return float("nan")
    err_rel = np.abs((obs[nonzero] - pred[nonzero]) / obs[nonzero]) * 100.0
    return float(np.nanpercentile(err_rel, 80))


def _metric_tol_in_pct(
    obs: np.ndarray, pred: np.ndarray, w: np.ndarray | None
) -> float:
    """Percentage of rows whose Tolerance_IN_OUT == 1 (inclus). Here ``obs``
    is repurposed to carry the pre-computed Tolerance_IN_OUT codes and
    ``pred`` is ignored - this lets us reuse the same bootstrap_ci95 plumbing
    without introducing a separate sampler. Weights are unused (un-weighted
    ratio)."""
    del pred, w
    valid = ~np.isnan(obs)
    if not valid.any():
        return float("nan")
    n_valid = int(valid.sum())
    n_in = int((obs[valid] == 1).sum())
    return 100.0 * n_in / n_valid


# ---------------------------------------------------------------------------
# P1.2 — Stratified metrics by TMJOBCTV bucket
# ---------------------------------------------------------------------------
#
# A single global tol_in_pct hides the fact that a model can be excellent
# on high-traffic sensors but disastrous on the low-traffic tail (or vice
# versa). The audit plan asks for the same metrics broken down into four
# canonical buckets of observed traffic volume so reviewers can see where
# the model actually fails.
_TMJA_BUCKETS: list[tuple[str, float, float]] = [
    ("0-1k", 0.0, 1000.0),
    ("1k-5k", 1000.0, 5000.0),
    ("5k-20k", 5000.0, 20000.0),
    ("20k+", 20000.0, float("inf")),
]

# Buckets below this row count get a warning flag but are NOT dropped — the
# caller may still want to surface them (and the empty cell tells the user
# their validation set lacks coverage in that range).
_TMJA_LOW_SAMPLE_THRESHOLD = 10


def _stratify_by_tmja(
    df: pd.DataFrame,
    flow_col: str,
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> list[dict[str, Any]]:
    """Compute (tol_in_pct, p80, r2, n_samples) per TMJOBCTV bucket.

    Parameters
    ----------
    df
        Enriched evaluation DataFrame. Must contain ``flow_col`` (the observed
        traffic volume column, e.g. TMJOBCTV / TMJABCTV). When the column is
        present we also try to read pre-computed ``Tolerance_IN_OUT``,
        ``TMJABCTV`` and ``TVr`` columns for the tol_in_pct / p80 metrics —
        when they are missing we silently fall back to the (y_true, y_pred)
        arrays so the function still returns 4 rows.
    flow_col
        Name of the flow column actually present in ``df`` (resolved by the
        caller via the same lookup used for hd_rmse).
    y_true, y_pred
        Global aligned arrays (same length as ``df``). Used for the per-bucket
        R-squared and as a fall-back for p80 when TVr/TMJABCTV are absent.

    Returns
    -------
    list of dicts, one per bucket, always in the canonical order
    (0-1k, 1k-5k, 5k-20k, 20k+). Buckets with no rows still appear with
    ``n_samples=0`` and NaN metrics so the front-end can render an empty cell
    without special-casing missing buckets. Returns ``[]`` when ``flow_col``
    is not in ``df.columns`` (caller logs a warning).
    """
    if flow_col not in df.columns:
        return []

    flows = pd.to_numeric(df[flow_col], errors="coerce").to_numpy(dtype=np.float64)
    n_total = flows.shape[0]
    if n_total == 0 or n_total != len(y_true) or n_total != len(y_pred):
        return []

    # Pre-resolve auxiliary columns once. Tolerance_IN_OUT carries the
    # 1/2/3 codes already computed against the (TVrmin, TVrmax) envelope,
    # so we just count code==1 per bucket. TMJABCTV/TVr power the relative
    # error p80 the same way the global metric does.
    tol_codes: np.ndarray | None = None
    if "Tolerance_IN_OUT" in df.columns:
        tol_codes = pd.to_numeric(
            df["Tolerance_IN_OUT"], errors="coerce"
        ).to_numpy(dtype=np.float64)

    obs_p80_arr: np.ndarray | None = None
    pred_p80_arr: np.ndarray | None = None
    if "TMJABCTV" in df.columns and "TVr" in df.columns:
        obs_p80_arr = pd.to_numeric(df["TMJABCTV"], errors="coerce").to_numpy(
            dtype=np.float64
        )
        pred_p80_arr = pd.to_numeric(df["TVr"], errors="coerce").to_numpy(
            dtype=np.float64
        )

    results: list[dict[str, Any]] = []
    for label, lo, hi in _TMJA_BUCKETS:
        if math.isinf(hi):
            mask = np.isfinite(flows) & (flows >= lo)
            range_repr: list[float | None] = [lo, None]
        else:
            mask = np.isfinite(flows) & (flows >= lo) & (flows < hi)
            range_repr = [lo, hi]
        n = int(mask.sum())

        # tol_in_pct: count of Tolerance_IN_OUT == 1 (the un-weighted ratio
        # matches what _metric_tol_in_pct returns globally).
        tol_in_pct_val: float = float("nan")
        tol_in_n_val = 0
        if n > 0 and tol_codes is not None:
            codes_b = tol_codes[mask]
            valid = ~np.isnan(codes_b)
            if valid.any():
                tol_in_n_val = int((codes_b[valid] == 1).sum())
                tol_in_pct_val = 100.0 * tol_in_n_val / int(valid.sum())

        # p80 of relative error |obs - pred| / obs * 100.
        p80_val: float = float("nan")
        if n > 0:
            if obs_p80_arr is not None and pred_p80_arr is not None:
                obs_b = obs_p80_arr[mask]
                pred_b = pred_p80_arr[mask]
            else:
                # Fall back to the raw model output when TVr/TMJABCTV are
                # absent — same fall-back the global p80 bootstrap uses.
                obs_b = np.asarray(y_true, dtype=np.float64)[mask]
                pred_b = np.asarray(y_pred, dtype=np.float64)[mask]
            finite = np.isfinite(obs_b) & np.isfinite(pred_b) & (obs_b != 0)
            if finite.any():
                err_rel = np.abs(
                    (obs_b[finite] - pred_b[finite]) / obs_b[finite]
                ) * 100.0
                p80_val = float(np.nanpercentile(err_rel, 80))

        # R-squared (always on y_true/y_pred — those are the model's own
        # raw target, identical to what _metric_r2 sees globally).
        r2_val: float = float("nan")
        if n > 0:
            yt_b = np.asarray(y_true, dtype=np.float64)[mask]
            yp_b = np.asarray(y_pred, dtype=np.float64)[mask]
            finite = np.isfinite(yt_b) & np.isfinite(yp_b)
            if finite.sum() >= 2:  # need >=2 points for a meaningful variance
                yt_v = yt_b[finite]
                yp_v = yp_b[finite]
                ss_res = float(np.sum((yt_v - yp_v) ** 2))
                ss_tot = float(np.sum((yt_v - np.mean(yt_v)) ** 2))
                if ss_tot > 0:
                    r2_val = 1.0 - ss_res / ss_tot

        entry: dict[str, Any] = {
            "bucket": label,
            "range": range_repr,
            "n_samples": n,
            "tol_in_n": tol_in_n_val,
            "tol_in_pct": (
                round(tol_in_pct_val, 2) if math.isfinite(tol_in_pct_val) else None
            ),
            "p80": round(p80_val, 4) if math.isfinite(p80_val) else None,
            "r2": round(r2_val, 6) if math.isfinite(r2_val) else None,
        }
        if 0 < n < _TMJA_LOW_SAMPLE_THRESHOLD:
            entry["low_sample_warning"] = True
        results.append(entry)

    return results


# ---------------------------------------------------------------------------
# P4.1 — Calibration data (predicted vs observed scatter)
# ---------------------------------------------------------------------------

# Hard cap on the number of (obs, pred) pairs persisted in the session. The
# calibration plot only needs a representative cloud — when n grows much
# beyond 5k points the Plotly trace becomes slow to render in the browser
# and the JSON payload bloats the Redis backend. We downsample with a fixed
# seed so the plot is deterministic across reloads.
_CALIBRATION_MAX_POINTS = 5000


def _compute_calibration_data(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    max_points: int = _CALIBRATION_MAX_POINTS,
    seed: int = 1750,
) -> dict[str, Any] | None:
    """Return a JSON-serialisable {"obs", "pred", "n"} dict.

    Drops non-finite pairs and downsamples (with a fixed seed) when the
    cloud exceeds ``max_points``. Returns ``None`` when no valid pair
    survives so the caller can short-circuit to an empty-state message.
    """
    obs = np.asarray(y_true, dtype=np.float64).ravel()
    pred = np.asarray(y_pred, dtype=np.float64).ravel()
    if obs.size == 0 or obs.size != pred.size:
        return None
    finite = np.isfinite(obs) & np.isfinite(pred)
    obs = obs[finite]
    pred = pred[finite]
    if obs.size == 0:
        return None
    n_full = int(obs.size)
    if obs.size > max_points:
        rng = np.random.default_rng(seed)
        idx = rng.choice(obs.size, size=max_points, replace=False)
        idx.sort()
        obs = obs[idx]
        pred = pred[idx]
    return {
        "obs": [round(float(v), 6) for v in obs],
        "pred": [round(float(v), 6) for v in pred],
        "n": n_full,
        "n_plotted": int(obs.size),
    }


# ---------------------------------------------------------------------------
# P4.2 — Residual boxplot by functional_class
# ---------------------------------------------------------------------------

def _resolve_functional_class(df: pd.DataFrame) -> pd.Series | None:
    """Return a per-row integer ``functional_class`` series (1..5) when
    derivable from ``df``.

    Two encodings are supported:
        * a raw ``functional_class`` (or ``FunctionalClass``) numeric column;
        * the one-hot trio ``fc_1`` .. ``fc_5`` (any subset present is
          recombined into the original integer class via argmax).

    Returns ``None`` when neither encoding is present so the caller can
    skip the section gracefully.
    """
    for cand in ("functional_class", "FunctionalClass", "FC", "fc"):
        if cand in df.columns:
            s = pd.to_numeric(df[cand], errors="coerce")
            if s.notna().any():
                return s
    # One-hot fallback. We require at least two fc_* columns to recombine
    # meaningfully — a single fc_3 column tells us nothing about the rows
    # whose fc_3 == 0.
    onehot_cols = [c for c in df.columns if c.startswith("fc_") and c[3:].isdigit()]
    if len(onehot_cols) >= 2:
        try:
            mat = df[onehot_cols].apply(pd.to_numeric, errors="coerce").fillna(0).to_numpy()
            class_ids = np.array([int(c.split("_", 1)[1]) for c in onehot_cols])
            # Rows with all zeros stay NaN (no class).
            row_max = mat.max(axis=1)
            argmax_idx = mat.argmax(axis=1)
            picked = class_ids[argmax_idx].astype(float)
            picked[row_max <= 0] = np.nan
            return pd.Series(picked, index=df.index)
        except Exception:  # noqa: BLE001
            return None
    return None


def _compute_residuals_by_fc(
    df: pd.DataFrame,
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> list[dict[str, Any]]:
    """Group residuals (pred - obs) by functional_class.

    Returns an empty list when the class column cannot be resolved (caller
    renders an empty-state message). One dict per class actually present,
    ordered by class id ascending. Each dict carries the raw residuals
    array (truncated to 2000 points per class) plus pre-computed summary
    stats so the front-end can render either a boxplot or a table.
    """
    fc_series = _resolve_functional_class(df)
    if fc_series is None:
        return []

    obs = np.asarray(y_true, dtype=np.float64).ravel()
    pred = np.asarray(y_pred, dtype=np.float64).ravel()
    if obs.size == 0 or obs.size != pred.size or len(fc_series) != obs.size:
        return []

    residuals = pred - obs
    fc_vals = pd.to_numeric(fc_series, errors="coerce").to_numpy(dtype=np.float64)

    results: list[dict[str, Any]] = []
    # Iterate over classes 1..5 (canonical range) plus any extra integer
    # actually present, just in case the schema ever grows.
    unique_classes = sorted(
        {int(v) for v in fc_vals if np.isfinite(v) and float(v).is_integer()}
    )
    for fc in unique_classes:
        mask = np.isfinite(fc_vals) & (fc_vals == fc) & np.isfinite(residuals)
        if not mask.any():
            continue
        res_b = residuals[mask]
        # Cap at 2000 points to keep the JSON payload small. A 2k-point
        # box plot is visually indistinguishable from a 20k-point one.
        if res_b.size > 2000:
            rng = np.random.default_rng(1750 + fc)
            idx = rng.choice(res_b.size, size=2000, replace=False)
            idx.sort()
            res_sample = res_b[idx]
        else:
            res_sample = res_b
        results.append({
            "fc": int(fc),
            "n": int(res_b.size),
            "median": round(float(np.median(res_b)), 4),
            "mean": round(float(np.mean(res_b)), 4),
            "q1": round(float(np.percentile(res_b, 25)), 4),
            "q3": round(float(np.percentile(res_b, 75)), 4),
            "min": round(float(np.min(res_b)), 4),
            "max": round(float(np.max(res_b)), 4),
            "residuals": [round(float(v), 4) for v in res_sample],
        })
    return results


# ---------------------------------------------------------------------------
# P4.3 — Annual drift table (R², MAE, tol_in_pct per year)
# ---------------------------------------------------------------------------

_DRIFT_MIN_SAMPLES = 10


def _compute_drift_by_year(
    df: pd.DataFrame,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    year_value_mapping: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Compute per-year (R², MAE, tol_in_pct, p80) on ``year_mapped``.

    ``year_mapped`` is the encoded year feature the model actually consumes
    (1..7 in the canonical 2019..2025 mapping). ``year_value_mapping`` is
    the reverse lookup we use to label each row of the table; when None
    or missing entries, we fall back to ``"year_<n>"``.

    Returns an empty list when ``year_mapped`` is absent from ``df`` so
    the caller can render an empty-state message. Years with fewer than
    ``_DRIFT_MIN_SAMPLES`` rows are skipped.
    """
    if "year_mapped" not in df.columns:
        return []

    obs = np.asarray(y_true, dtype=np.float64).ravel()
    pred = np.asarray(y_pred, dtype=np.float64).ravel()
    if obs.size == 0 or obs.size != pred.size:
        return []

    ym = pd.to_numeric(df["year_mapped"], errors="coerce").to_numpy(dtype=np.float64)
    if ym.size != obs.size:
        return []

    # Reverse mapping for labelling. The frontend stores
    # {"2019": 1.0, "2020": 2.0, ...} → invert to {1: "2019", 2: "2020", ...}.
    inv_label: dict[int, str] = {}
    if year_value_mapping:
        for label, val in year_value_mapping.items():
            try:
                key = int(round(float(val)))
                inv_label[key] = str(label)
            except (TypeError, ValueError):
                continue

    unique_years = sorted(
        {int(round(v)) for v in ym if np.isfinite(v)}
    )
    results: list[dict[str, Any]] = []
    for year_val in unique_years:
        mask = np.isfinite(ym) & (np.round(ym).astype(int) == year_val)
        mask &= np.isfinite(obs) & np.isfinite(pred)
        n = int(mask.sum())
        if n < _DRIFT_MIN_SAMPLES:
            continue
        obs_b = obs[mask]
        pred_b = pred[mask]
        res_b = obs_b - pred_b
        mae = float(np.mean(np.abs(res_b)))

        ss_res = float(np.sum(res_b ** 2))
        ss_tot = float(np.sum((obs_b - np.mean(obs_b)) ** 2))
        r2 = (1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        # tol_in_pct: same definition as the global metric — |pred-obs|/obs
        # within 15% (the default tolerance used elsewhere in the report).
        nonzero = obs_b != 0
        tol_in_pct = float("nan")
        if nonzero.any():
            err_rel = np.abs((obs_b[nonzero] - pred_b[nonzero]) / obs_b[nonzero]) * 100.0
            tol_in_pct = 100.0 * float(np.mean(err_rel <= 15.0))

        # p80 of |obs - pred| / obs * 100.
        p80 = float("nan")
        if nonzero.any():
            err_rel = np.abs((obs_b[nonzero] - pred_b[nonzero]) / obs_b[nonzero]) * 100.0
            p80 = float(np.nanpercentile(err_rel, 80))

        results.append({
            "year_mapped": int(year_val),
            "year_label": inv_label.get(year_val, f"year_{year_val}"),
            "n_samples": n,
            "r2": round(r2, 6),
            "mae": round(mae, 4),
            "tol_in_pct": round(tol_in_pct, 2) if math.isfinite(tol_in_pct) else None,
            "p80": round(p80, 4) if math.isfinite(p80) else None,
        })
    return results


# ---------------------------------------------------------------------------
# Display-label mapping: the dataframe still stores legacy Bordeaux column
# names internally (TMJABCTV / TMJAFCDTV / TxPenTVRef) because val_renames
# aliases the FCD HERE schema onto them, but every label shown to the user
# in the HTML report must use the modern FCD HERE names.
# ---------------------------------------------------------------------------
_DISPLAY_LABELS = {
    "TMJABCTV": "TMJOBCTV",
    "TMJABCPL": "TMJOBCPL",
    "TMJAFCDTV": "TMJOFCDTV",
    "TMJAFCDPL": "TMJOFCDPL",
    "TxPenTVRef": "TxPen",
    "TxPenPLRef": "TxPenPL",
}


def _label(col: str) -> str:
    """Return the user-facing label for a (possibly legacy) column name."""
    return _DISPLAY_LABELS.get(col, col)


# ---------------------------------------------------------------------------
# HTML report generator
# ---------------------------------------------------------------------------

def _fmt(v, digits=2):
    """Format a numeric value for display, handling NaN/Inf."""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "-"
    return f"{v:.{digits}f}"


def _add_tolerance_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Compute TVrmin, TVrmax, Tolerance_IN_OUT — delegates to the
    unified service implementation (B3).
    """
    from ..services.ml.evaluation_pipeline import add_tolerance_columns
    from ..services.ml.types import TV_CONFIG
    return add_tolerance_columns(df, TV_CONFIG)


def _LEGACY_add_tolerance_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["TVr"] = pd.to_numeric(out["TVr"], errors="coerce")

    def erreur_pourcentage(tvr):
        if pd.isna(tvr):
            return np.nan
        if tvr > 10000:
            return 0.14
        if tvr > 5000:
            return 0.18
        if tvr > 2000:
            return 0.18
        return 0.25

    out["Erreur_dyn"] = out["TVr"].apply(erreur_pourcentage)
    out["TVrmin"] = out["TVr"] * (1 - out["Erreur_dyn"])
    out["TVrmax"] = out["TVr"] * (1 + out["Erreur_dyn"])

    mask10 = out["TVr"] > 10000
    out.loc[mask10, "TVrmin"] = np.round(out.loc[mask10, "TVrmin"], -2)
    out.loc[mask10, "TVrmax"] = np.round(out.loc[mask10, "TVrmax"], -2)

    mask500 = out["TVr"] < 500
    out.loc[mask500, "TVrmin"] = 10 * np.floor(out.loc[mask500, "TVrmin"] / 10)
    out.loc[mask500, "TVrmax"] = 10 * np.ceil(out.loc[mask500, "TVrmax"] / 10)

    mask_middle = out["TVr"] >= 500
    out.loc[mask_middle, "TVrmin"] = 100 * np.floor(out.loc[mask_middle, "TVrmin"] / 100)
    out.loc[mask_middle, "TVrmax"] = 100 * np.ceil(out.loc[mask_middle, "TVrmax"] / 100)

    out.loc[out["TVrmin"].notna() & (out["TVrmin"] < 100), "TVrmin"] = 0
    out.loc[out["TVrmax"].notna() & (out["TVrmax"] < 100), "TVrmax"] = 100

    for c in ["TMJABCTV", "TVrmin", "TVrmax"]:
        out[c] = pd.to_numeric(out.get(c), errors="coerce")

    tmja = out["TMJABCTV"]
    lower = np.minimum(out["TVrmin"], out["TVrmax"])
    upper = np.maximum(out["TVrmin"], out["TVrmax"])

    in_range = tmja.ge(lower) & tmja.le(upper)
    near_lower = tmja.lt(lower) & tmja.ge(0.85 * lower)
    near_upper = tmja.gt(upper) & tmja.le(1.15 * upper)
    near_bound = near_lower | near_upper

    out["Tolerance_IN_OUT"] = pd.Series(
        np.select([in_range, near_bound], [1, 2], default=3),
        index=out.index,
    ).astype("Int64")

    mask_nan = tmja.isna() | lower.isna() | upper.isna()
    out.loc[mask_nan, "Tolerance_IN_OUT"] = pd.NA
    return out


def _compute_flow_metrics(df: pd.DataFrame) -> dict:
    """Compute flow metrics — delegates to service.evaluation_pipeline (B3)."""
    from ..services.ml.evaluation_pipeline import compute_flow_metrics
    from ..services.ml.types import TV_CONFIG
    return compute_flow_metrics(df, TV_CONFIG)


def _LEGACY_compute_flow_metrics(df: pd.DataFrame) -> dict:
    d = df.copy()
    d["TMJABCTV"] = pd.to_numeric(d.get("TMJABCTV"), errors="coerce")
    d["TVr"] = pd.to_numeric(d.get("TVr"), errors="coerce")
    d["GEH"] = pd.to_numeric(d.get("GEH"), errors="coerce")
    d = d.dropna(subset=["TMJABCTV", "TVr"])

    if d.empty:
        return {
            "n": 0, "err_rel_med": np.nan, "err_abs_med": np.nan,
            "err_rel_p80": np.nan, "err_abs_p80": np.nan,
            "geh_lt5_pct": np.nan, "geh_le10_pct": np.nan,
        }

    err_abs = (d["TVr"] - d["TMJABCTV"]).abs().astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        err_rel = np.where(d["TMJABCTV"] != 0, err_abs / d["TMJABCTV"] * 100.0, np.nan)
    err_rel = pd.Series(err_rel).replace([np.inf, -np.inf], np.nan)

    geh = pd.to_numeric(d["GEH"], errors="coerce")
    valid_geh = geh.notna().sum()
    geh_lt5_pct = 100.0 * (geh < 5).sum() / valid_geh if valid_geh > 0 else np.nan
    geh_le10_pct = 100.0 * (geh <= 10).sum() / valid_geh if valid_geh > 0 else np.nan

    return {
        "n": int(len(d)),
        "err_rel_med": float(np.nanmedian(err_rel)),
        "err_abs_med": float(np.nanmedian(err_abs)),
        "err_rel_p80": float(np.nanpercentile(err_rel, 80)),
        "err_abs_p80": float(np.nanpercentile(err_abs, 80)),
        "geh_lt5_pct": float(geh_lt5_pct),
        "geh_le10_pct": float(geh_le10_pct),
    }


def _compute_tolerance_counts(df: pd.DataFrame) -> dict:
    """Count Tolerance_IN_OUT — delegates to service.evaluation_pipeline (B3)."""
    from ..services.ml.evaluation_pipeline import compute_tolerance_counts
    return compute_tolerance_counts(df)


def _make_barplot_html(df: pd.DataFrame, title: str) -> str:
    """Grouped bar chart TMJABCTV vs TVr (max 200 sensors), returns Plotly HTML fragment."""
    import plotly.graph_objects as go
    import plotly.io as pio

    d = df.copy()
    d["TMJABCTV"] = pd.to_numeric(d.get("TMJABCTV"), errors="coerce")
    d["TVr"] = pd.to_numeric(d.get("TVr"), errors="coerce")
    d = d.dropna(subset=["TMJABCTV", "TVr"])
    if d.empty:
        return f"<p>Aucune donnee ({title})</p>"

    n_sample = min(200, len(d))
    d = d.sample(n=n_sample, random_state=42).reset_index(drop=True)

    labels = d["PTM_ID"].astype(str).tolist() if "PTM_ID" in d.columns else [str(i) for i in range(len(d))]

    hover_cols = [
        c for c in [
            "PTM_ID", "Identifiant", "STA", "Type", "Commune", "Route",
            "TMJAFCDTV", "TMJAFCDPL",
            "car_count", "car_average_speed_kmh", "car_average_distance_km",
            "truck_count", "truck_average_speed_kmh", "truck_min_average_distance_km",
            "TMJABCTV", "TVr", "TP_redressement",
            "Erreur %", "Erreur absolue", "GEH",
            "TVrmin", "TVrmax", "Tolerance_IN_OUT",
        ] if c in d.columns
    ]

    def _fmtv(v):
        if v is None:
            return "-"
        try:
            if math.isnan(float(v)) or math.isinf(float(v)):
                return "-"
            if isinstance(v, float):
                return f"{v:.2f}"
        except (TypeError, ValueError):
            pass
        return str(v)

    customdata = [[_fmtv(row.get(c)) for c in hover_cols] for _, row in d.iterrows()]
    hover_lines = "".join(
        f"<b>{_label(c)}</b> : %{{customdata[{i}]}}<br>"
        for i, c in enumerate(hover_cols)
    )
    hover_template = hover_lines + "<extra></extra>"

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=d["TMJABCTV"].tolist(),
        name=f"{_label('TMJABCTV')} (validation)", marker_color="#1f77b4",
        customdata=customdata,
        hovertemplate=hover_template,
    ))
    fig.add_trace(go.Bar(
        x=labels, y=d["TVr"].tolist(),
        name="TVr (predit)", marker_color="#00b894",
        customdata=customdata,
        hovertemplate=hover_template,
    ))
    fig.update_layout(
        barmode="group",
        template="plotly_white",
        title=title,
        xaxis_title="Capteurs",
        yaxis_title="TMJA (veh/jour)",
        margin=dict(l=40, r=40, t=60, b=60),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="Manrope,sans-serif"),
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)


def _make_folium_map_html(stats_df: pd.DataFrame, model_name: str) -> str:
    """Build a folium map coloured by Tolerance_IN_OUT, returns iframe HTML."""
    import folium

    df = stats_df.copy()
    df["lat"] = pd.to_numeric(df.get("lat"), errors="coerce")
    df["lon"] = pd.to_numeric(df.get("lon"), errors="coerce")
    valid = df.dropna(subset=["lat", "lon"])
    if valid.empty:
        return "<p style='color:#888;font-style:italic;'>Aucune coordonnee geographique disponible pour afficher la carte (colonnes lat/lon absentes).</p>"

    # Tolerance_IN_OUT may be missing entirely for the new FCD HERE schema.
    # `.get()` returns None when absent; coerce to an empty numeric Series so
    # downstream `.notna()` / mask operations stay vectorised.
    tol_raw = valid.get("Tolerance_IN_OUT")
    if tol_raw is None:
        tol = pd.Series([np.nan] * len(valid), index=valid.index)
    else:
        tol = pd.to_numeric(tol_raw, errors="coerce")
    n1 = int((tol == 1).sum())
    n2 = int((tol == 2).sum())
    n3 = int((tol == 3).sum())
    n_valid = int(tol.notna().sum())

    def _color(val):
        try:
            k = int(val)
        except Exception:
            return "#808080"
        return {1: "#2ecc71", 2: "#f39c12", 3: "#e74c3c"}.get(k, "#808080")

    # Reference flow column name varies with the schema (Bordeaux: TMJABCTV,
    # Lyon: TMJOBCTV). Try both, then any column starting with TMJ as last fallback.
    ref_col_candidates = ["TMJOBCTV", "TMJABCTV"]
    s_raw = None
    for c in ref_col_candidates:
        if c in valid.columns:
            s_raw = valid[c]
            break
    if s_raw is None:
        s = pd.Series([np.nan] * len(valid), index=valid.index)
    else:
        s = pd.to_numeric(s_raw, errors="coerce")
    lo = float(np.nanquantile(s.dropna(), 0.01)) if s.notna().any() else 0.0
    hi = float(np.nanquantile(s.dropna(), 0.99)) if s.notna().any() else 1.0
    if not np.isfinite(hi) or hi <= lo:
        hi = lo + 1.0

    def _radius(v):
        try:
            v = float(v)
        except Exception:
            return 4.0
        return 3.0 + (min(max(v, lo), hi) - lo) / (hi - lo) * 9.0

    m = folium.Map(
        location=[float(valid["lat"].mean()), float(valid["lon"].mean())],
        zoom_start=11,
        tiles="cartodbpositron",
    )
    layer = folium.FeatureGroup(name="Capteurs")
    layer.add_to(m)

    info_cols = [
        c for c in [
            "PTM_ID", "Identifiant", "STA", "Type", "Commune", "Route",
            "TMJAFCDTV", "TMJAFCDPL",
            "car_count", "car_average_speed_kmh", "car_average_distance_km",
            "truck_count", "truck_average_speed_kmh", "truck_min_average_distance_km",
            "TMJABCTV", "TVr", "TP_redressement",
            "Erreur %", "Erreur absolue", "GEH",
            "TVrmin", "TVrmax", "Tolerance_IN_OUT",
            "flag_comptage",
        ] if c in valid.columns
    ]

    for _, row in valid.iterrows():
        lines = []
        for c in info_cols:
            v = row.get(c, "-")
            if isinstance(v, float):
                v = "-" if (math.isnan(v) or math.isinf(v)) else f"{v:.2f}"
            lines.append(f"<b>{_label(c)}</b> : {v}")
        popup_html = (
            "<div style='font-size:13px;font-family:Manrope,sans-serif;line-height:1.7;'>"
            + "<br>".join(lines)
            + "</div>"
        )
        tooltip_txt = str(row.get("PTM_ID", f"({row['lat']:.4f}, {row['lon']:.4f})"))
        folium.CircleMarker(
            location=(row["lat"], row["lon"]),
            radius=_radius(row.get("TMJABCTV")),
            color=_color(row.get("Tolerance_IN_OUT")),
            fill=True,
            fill_opacity=0.85,
            weight=1.2,
            popup=folium.Popup(popup_html, max_width=360),
            tooltip=tooltip_txt,
        ).add_to(layer)

    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds([
        [float(valid["lat"].min()), float(valid["lon"].min())],
        [float(valid["lat"].max()), float(valid["lon"].max())],
    ])

    pct = lambda n: (100.0 * n / n_valid) if n_valid > 0 else 0.0
    legend_html = f"""
    <div style="position:fixed;bottom:20px;left:20px;z-index:9999;background:white;
            padding:10px 14px;border:1px solid #ccc;border-radius:10px;
            box-shadow:0 2px 8px rgba(0,0,0,.18);font-size:13px;font-family:Manrope,sans-serif;">
      <div style="font-weight:700;margin-bottom:7px;">Tolerance &ndash; {_html.escape(model_name)}</div>
      <div><span style="display:inline-block;width:13px;height:13px;background:#2ecc71;border:1px solid #999;margin-right:6px;border-radius:50%;"></span>1 Inclus <b>({n1} &ndash; {pct(n1):.1f}%)</b></div>
      <div><span style="display:inline-block;width:13px;height:13px;background:#f39c12;border:1px solid #999;margin-right:6px;border-radius:50%;"></span>2 Hors &lt;15% borne <b>({n2} &ndash; {pct(n2):.1f}%)</b></div>
      <div><span style="display:inline-block;width:13px;height:13px;background:#e74c3c;border:1px solid #999;margin-right:6px;border-radius:50%;"></span>3 Hors &gt;15% borne <b>({n3} &ndash; {pct(n3):.1f}%)</b></div>
      <div style="margin-top:6px;font-size:11px;color:#666;">Total: {n_valid} | Rayon ~ TMJOBCTV</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    map_full_html = m.get_root().render()
    # Use base64 srcdoc to avoid quote-escaping issues that break the HTML
    import base64
    encoded = base64.b64encode(map_full_html.encode("utf-8")).decode("ascii")
    return (
        f'<iframe id="folium-map-frame" width="100%" height="600" '
        f'style="border:none;border-radius:12px;display:block;" '
        f'sandbox="allow-scripts allow-same-origin"></iframe>\n'
        f'<script>\n'
        f'(function(){{\n'
        f'  var iframe = document.getElementById("folium-map-frame");\n'
        f'  var html = atob("{encoded}");\n'
        f'  iframe.srcdoc = html;\n'
        f'}})();\n'
        f'</script>'
    )


def _build_sensitivity_section_html(
    df: pd.DataFrame,
    model: Any,
    mu_x: np.ndarray,
    s_x: np.ndarray,
    mu_y: np.ndarray,
    s_y: np.ndarray,
    input_cols: list[str],
    num_points: int = 60,
) -> str:
    """Build sensitivity analysis HTML section.

    For each input feature, varies it from min to max (num_points steps) while
    fixing other features at Q1, Median, Q3 baselines. Predicts TxPen via the
    model, denormalises, and computes TVr = TMJAFCDTV / TxPen * 100.

    Returns a complete HTML string (CSS + section + JS) ready to embed in the report.
    """
    import plotly.graph_objects as go
    import plotly.io as pio

    n_inputs = len(input_cols)
    # Expand mu_x/s_x if needed (for non-normalized trailing columns like year_mapped)
    if len(mu_x) < n_inputs:
        on_off_norm = np.ones(n_inputs, dtype=bool)
        n_not_normed = n_inputs - len(mu_x)
        on_off_norm[-n_not_normed:] = False
        if int(on_off_norm.sum()) == len(mu_x):
            full_mu = np.zeros(n_inputs, dtype=float)
            full_s = np.ones(n_inputs, dtype=float)
            full_mu[on_off_norm] = mu_x
            full_s[on_off_norm] = s_x
            mu_x = full_mu
            s_x = full_s

    # Cast input columns to numeric
    df_num = df[input_cols].copy()
    for c in input_cols:
        df_num[c] = pd.to_numeric(df_num[c], errors="coerce")

    # Compute Q1 / Median / Q3 baselines
    q_baselines = {
        "Q1":  df_num.quantile(0.25),
        "Med": df_num.quantile(0.50),
        "Q3":  df_num.quantile(0.75),
    }

    # Determine numerator column for TVr = numerator / TxPen * 100.
    # Modern FCD HERE schema uses TMJOFCDTV; legacy Bordeaux datasets use
    # TMJAFCDTV / TMJATV. Before this fix, only legacy names were tried —
    # so on FCD HERE models the numerator fell back to 1 and the chart
    # showed TVr = 100/TxPen (range 30-110) instead of the real
    # TMJOFCDTV/TxPen * 100 (range 0 — 50 000+).
    _numerator_col: str | None = None
    for _cand in ("TMJOFCDTV", "TMJAFCDTV", "TMJATV"):
        if _cand in input_cols:
            _numerator_col = _cand
            break

    _COLORS = {"Q1": "#6eb5ff", "Med": "#0057b7", "Q3": "#003d80"}
    _DASHES = {"Q1": "dot", "Med": "solid", "Q3": "dash"}

    plots_dict: dict[str, str] = {}
    rendered_cols: list[str] = []

    s_x_safe = np.where(s_x == 0, 1.0, s_x)

    for feat in input_cols:
        col_series = df_num[feat].dropna()
        if col_series.empty:
            continue
        vmin, vmax = float(col_series.min()), float(col_series.max())
        if not (np.isfinite(vmin) and np.isfinite(vmax)):
            continue
        if vmax == vmin:
            continue

        x_vals = np.linspace(vmin, vmax, num_points, dtype=float)

        fig = go.Figure()

        for bl_label, q_vec in q_baselines.items():
            # Build input matrix: all features at baseline
            mat = np.tile(q_vec.values.astype(float), (num_points, 1))
            df_x = pd.DataFrame(mat, columns=input_cols)
            # Vary the current feature
            df_x[feat] = x_vals

            # Normalise -> predict -> denormalise
            x_norm = ((df_x.values - mu_x) / s_x_safe).astype(np.float32)
            y_norm = model.predict(x_norm, verbose=0)
            txpen = y_norm.flatten().astype(float) * float(s_y) + float(mu_y)

            # Compute TVr
            with np.errstate(divide="ignore", invalid="ignore"):
                if feat == _numerator_col:
                    numerator = x_vals
                elif _numerator_col is not None:
                    numerator = np.full(num_points, float(q_vec[_numerator_col]), dtype=float)
                else:
                    numerator = np.ones(num_points, dtype=float)

                tvr = np.where(txpen > 0, numerator / txpen * 100.0, np.nan)
                tvr = np.where(np.isfinite(tvr), tvr, np.nan)

            # Build hover text
            other_feats = [c for c in input_cols if c != feat]
            hover_lines = [
                f"<b>{feat}</b> : %{{x:.2f}}<br>",
                f"<b>TVr</b> : %{{y:.1f}}<br>",
                f"<i>Autres features fig&#233;es &#224; {bl_label} :</i><br>",
            ] + [
                f"&nbsp;&nbsp;{c} = {q_vec[c]:.2f}<br>"
                for c in other_feats
            ]
            hover_tmpl = "".join(hover_lines) + "<extra></extra>"

            fig.add_trace(go.Scatter(
                x=x_vals.tolist(),
                y=tvr.tolist(),
                mode="lines",
                name=bl_label,
                line=dict(color=_COLORS[bl_label], dash=_DASHES[bl_label], width=2),
                hovertemplate=hover_tmpl,
            ))

        fig.update_layout(
            title=f"TVr ~ {feat}",
            xaxis_title=feat,
            yaxis_title="TVr (v&#233;h/jour)",
            template="plotly_white",
            margin=dict(l=50, r=40, t=60, b=60),
            hoverlabel=dict(bgcolor="white", font_size=12, font_family="Manrope,sans-serif"),
            legend=dict(
                orientation="h",
                yanchor="bottom", y=1.02,
                xanchor="left", x=0,
                title_text="Baseline",
            ),
        )

        plots_dict[feat] = pio.to_html(fig, include_plotlyjs=False, full_html=False)
        rendered_cols.append(feat)

    # Build the HTML section
    if not rendered_cols:
        return (
            '  <h2>Analyse de sensibilit&#233; &#8211; mod&#232;le</h2>\n'
            '  <p class="hint">Mod&#232;le ou colonnes d&#8217;entr&#233;e non disponibles '
            'pour l&#8217;analyse de sensibilit&#233;.</p>'
        )

    # Pills
    pills_html = "\n        ".join(
        f'<button class="sens-pill{" sens-pill--active" if i == 0 else ""}" '
        f'data-feat="{feat}" role="button" tabindex="0" '
        f'aria-pressed="{"true" if i == 0 else "false"}">{feat}</button>'
        for i, feat in enumerate(rendered_cols)
    )
    # Plot divs
    plot_divs_html = "\n".join(
        f'<div id="sens-plot-{feat}" class="sens-plot-slot" '
        f'style="display:{"block" if i == 0 else "none"};">'
        f'{plots_dict[feat]}</div>'
        for i, feat in enumerate(rendered_cols)
    )

    return f"""
<style>
.sens-block{{font-family:Manrope,"Segoe UI",Arial,sans-serif;color:#122033;margin-bottom:16px;}}
.sens-panel{{background:linear-gradient(180deg,#fff,#fbfdff);border:1px solid #dfe7f2;border-radius:16px;padding:20px;box-shadow:0 10px 22px rgba(12,52,103,.07);}}
.sens-header{{display:flex;align-items:flex-start;gap:12px;margin-bottom:6px;}}
.sens-icon{{flex-shrink:0;width:38px;height:38px;background:linear-gradient(135deg,#0057b7,#1a80e8);border-radius:10px;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 10px rgba(0,87,183,.22);}}
.sens-icon svg{{width:20px;height:20px;stroke:#fff;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}}
.sens-titles h2{{margin:0 0 3px;font-size:18px;font-weight:800;color:#0d1f35;}}
.sens-desc{{color:#56637a;font-size:12.5px;line-height:1.5;margin:0;max-width:680px;}}
.sens-divider{{border:none;border-top:1px solid #e8eef7;margin:14px 0;}}
.sens-controls{{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px;}}
.sens-controls-label{{font-size:11.5px;font-weight:700;color:#56637a;text-transform:uppercase;letter-spacing:.06em;white-space:nowrap;}}
.sens-pills{{display:flex;flex-wrap:wrap;gap:7px;}}
.sens-pill{{cursor:pointer;padding:5px 14px;border-radius:999px;font-size:12.5px;font-weight:600;border:1.5px solid #c8d8ef;background:#f0f5fc;color:#3d5a80;transition:background .16s,color .16s,border-color .16s,box-shadow .16s;user-select:none;line-height:1.4;white-space:nowrap;}}
.sens-pill:hover{{background:#daeaf9;border-color:#7ab3e0;color:#0b3d7a;}}
.sens-pill.sens-pill--active{{background:linear-gradient(135deg,#0057b7,#1a80e8);border-color:#0057b7;color:#fff;box-shadow:0 3px 10px rgba(0,87,183,.28);}}
.sens-legend{{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px;}}
.sens-legend-item{{display:flex;align-items:center;gap:6px;font-size:11.5px;color:#56637a;}}
.sens-legend-dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0;}}
.sens-legend-dot--q1{{background:#93c4f0;}}.sens-legend-dot--med{{background:#0057b7;}}.sens-legend-dot--q3{{background:#003a7a;}}
.sens-chart-wrap{{border-radius:10px;overflow:hidden;background:#f8fbff;border:1px solid #e8eef7;min-height:420px;}}
.sens-plot-slot{{width:100%;}}
.sens-plot-slot>div{{width:100%!important;}}
@media(max-width:600px){{.sens-pills{{display:grid;grid-template-columns:1fr 1fr;}}.sens-pill{{text-align:center;}}}}
</style>
<section class="sens-block">
  <div class="sens-panel">
    <div class="sens-header">
      <div class="sens-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><polyline points="3 17 8 12 13 15 21 7"/><line x1="3" y1="21" x2="21" y2="21"/><line x1="3" y1="3" x2="3" y2="21"/></svg>
      </div>
      <div class="sens-titles">
        <h2>Analyse de sensibilit&#233;</h2>
        <p class="sens-desc">Chaque courbe montre comment le <strong>TVr</strong> pr&#233;dit &#233;volue lorsqu&#8217;une feature varie, les autres fig&#233;es &#224; <strong>Q1</strong>, <strong>M&#233;diane</strong> et <strong>Q3</strong>. Cliquez sur une feature pour afficher son graphe.</p>
      </div>
    </div>
    <hr class="sens-divider">
    <div class="sens-controls">
      <span class="sens-controls-label">Feature</span>
      <div class="sens-pills" id="sensPills" role="group">
        {pills_html}
      </div>
    </div>
    <div class="sens-legend">
      <div class="sens-legend-item"><span class="sens-legend-dot sens-legend-dot--q1"></span><span>Q1 &#8212; 25e percentile</span></div>
      <div class="sens-legend-item"><span class="sens-legend-dot sens-legend-dot--med"></span><span>M&#233;diane &#8212; 50e percentile</span></div>
      <div class="sens-legend-item"><span class="sens-legend-dot sens-legend-dot--q3"></span><span>Q3 &#8212; 75e percentile</span></div>
    </div>
    <div class="sens-chart-wrap">
      {plot_divs_html}
    </div>
  </div>
</section>
<script>
(function() {{
  var pills = document.querySelectorAll("#sensPills .sens-pill");
  pills.forEach(function(pill) {{
    pill.addEventListener("click", function() {{
      var feat = this.getAttribute("data-feat");
      pills.forEach(function(p) {{
        p.classList.remove("sens-pill--active");
        p.setAttribute("aria-pressed", "false");
      }});
      this.classList.add("sens-pill--active");
      this.setAttribute("aria-pressed", "true");
      document.querySelectorAll(".sens-plot-slot").forEach(function(div) {{
        div.style.display = "none";
      }});
      var target = document.getElementById("sens-plot-" + feat);
      if (target) {{
        target.style.display = "block";
        var plotDiv = target.querySelector(".plotly-graph-div");
        if (plotDiv && window.Plotly) {{ window.Plotly.Plots.resize(plotDiv); }}
      }}
    }});
    pill.addEventListener("keydown", function(e) {{
      if (e.key === "Enter" || e.key === " ") {{ e.preventDefault(); this.click(); }}
    }});
  }});
}})();
</script>"""


def _make_calibration_plot_html(
    calibration_data: dict[str, Any] | None,
) -> str:
    """Render the P4.1 calibration scatter (pred vs obs) + y=x reference.

    Returns an empty-state ``<p>`` when ``calibration_data`` is None or empty.
    """
    if not calibration_data:
        return (
            '<p style="color:#888;font-style:italic;">'
            'Donnees indisponibles &mdash; vecteurs obs/pred vides.</p>'
        )
    obs = calibration_data.get("obs") or []
    pred = calibration_data.get("pred") or []
    if not obs or not pred:
        return (
            '<p style="color:#888;font-style:italic;">'
            'Donnees indisponibles &mdash; vecteurs obs/pred vides.</p>'
        )

    import plotly.graph_objects as go
    import plotly.io as pio

    obs_arr = np.asarray(obs, dtype=np.float64)
    pred_arr = np.asarray(pred, dtype=np.float64)
    finite = np.isfinite(obs_arr) & np.isfinite(pred_arr)
    if not finite.any():
        return (
            '<p style="color:#888;font-style:italic;">'
            'Donnees indisponibles &mdash; aucune paire (obs, pred) finie.</p>'
        )
    obs_arr = obs_arr[finite]
    pred_arr = pred_arr[finite]

    lo = float(min(obs_arr.min(), pred_arr.min()))
    hi = float(max(obs_arr.max(), pred_arr.max()))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        hi = lo + 1.0

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=obs_arr.tolist(),
        y=pred_arr.tolist(),
        mode="markers",
        name="Capteurs",
        marker=dict(
            size=6,
            color="#0057b7",
            opacity=0.55,
            line=dict(width=0),
        ),
        hovertemplate=(
            "<b>Observe</b> : %{x:.2f}<br>"
            "<b>Predit</b> : %{y:.2f}<extra></extra>"
        ),
    ))
    fig.add_trace(go.Scatter(
        x=[lo, hi],
        y=[lo, hi],
        mode="lines",
        name="y = x (parfait)",
        line=dict(color="#e74c3c", width=2, dash="dash"),
        hoverinfo="skip",
    ))
    n_full = int(calibration_data.get("n", len(obs_arr)))
    n_plotted = int(calibration_data.get("n_plotted", len(obs_arr)))
    subtitle = ""
    if n_plotted < n_full:
        subtitle = f" (echantillon {n_plotted} sur {n_full})"
    fig.update_layout(
        template="plotly_white",
        title=f"Calibration : predit vs observe{subtitle}",
        xaxis_title="Observe (y_true)",
        yaxis_title="Predit (y_pred)",
        margin=dict(l=50, r=40, t=60, b=60),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="Manrope,sans-serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return pio.to_html(fig, include_plotlyjs=False, full_html=False)


def _make_residuals_by_fc_html(
    residuals_by_fc: list[dict[str, Any]] | None,
) -> str:
    """Render the P4.2 residual boxplot grouped by functional_class."""
    if not residuals_by_fc:
        return (
            '<p style="color:#888;font-style:italic;">'
            'Donnees indisponibles &mdash; colonne <code>functional_class</code> '
            '(ou one-hot <code>fc_1..fc_5</code>) absente du jeu de validation.</p>'
        )

    import plotly.graph_objects as go
    import plotly.io as pio

    fig = go.Figure()
    palette = ["#0057b7", "#1a80e8", "#16a085", "#f39c12", "#e74c3c", "#6c5ce7", "#444"]
    for i, entry in enumerate(residuals_by_fc):
        fc = entry.get("fc", "?")
        residuals = entry.get("residuals") or []
        if not residuals:
            continue
        fig.add_trace(go.Box(
            y=residuals,
            name=f"FC {fc}",
            marker_color=palette[i % len(palette)],
            boxmean=True,
            hovertemplate=(
                f"<b>Classe fonctionnelle</b> : {fc}<br>"
                "<b>Residu</b> : %{y:.4f}<extra></extra>"
            ),
        ))
    if not fig.data:
        return (
            '<p style="color:#888;font-style:italic;">'
            'Donnees indisponibles &mdash; aucun residu calculable par classe.</p>'
        )
    fig.add_shape(
        type="line", xref="paper", yref="y",
        x0=0, x1=1, y0=0, y1=0,
        line=dict(color="#999", width=1, dash="dot"),
    )
    fig.update_layout(
        template="plotly_white",
        title="Residus par classe fonctionnelle",
        xaxis_title="Classe fonctionnelle",
        yaxis_title="Residu (pred &minus; obs)",
        showlegend=False,
        margin=dict(l=50, r=40, t=60, b=60),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="Manrope,sans-serif"),
    )
    return pio.to_html(fig, include_plotlyjs=False, full_html=False)


def _make_drift_by_year_html(
    drift_by_year: list[dict[str, Any]] | None,
) -> str:
    """Render the P4.3 annual drift table."""
    if not drift_by_year:
        return (
            '<p style="color:#888;font-style:italic;">'
            'Donnees indisponibles &mdash; colonne <code>year_mapped</code> absente '
            'ou aucune annee n a au moins 10 echantillons.</p>'
        )
    headers = [
        "Annee", "N", "R&sup2;", "MAE", "Tol. inclus (%)", "p80 err.rel (%)",
    ]
    thead = "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"
    rows: list[str] = []
    for entry in drift_by_year:
        label = _html.escape(str(entry.get("year_label", "-")))
        ym = entry.get("year_mapped")
        if ym is not None:
            label += (
                f' <small style="color:#56637a;font-weight:500;">'
                f'(year_mapped={ym})</small>'
            )
        rows.append(
            "<tr>"
            f"<td>{label}</td>"
            f"<td>{int(entry.get('n_samples', 0))}</td>"
            f"<td>{_fmt(entry.get('r2'), digits=4)}</td>"
            f"<td>{_fmt(entry.get('mae'))}</td>"
            f"<td>{_fmt(entry.get('tol_in_pct'))}</td>"
            f"<td>{_fmt(entry.get('p80'))}</td>"
            "</tr>"
        )
    return (
        '<table id="driftByYearTable" class="display" style="width:100%">'
        f'<thead>{thead}</thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
    )


def _generate_html_report(
    metrics: MetricsResult,
    model_name: str,
    training_config: dict[str, Any] | None,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    df: pd.DataFrame | None = None,
    sensitivity_html: str | None = None,
    metrics_ci95: dict[str, list[float] | None] | None = None,
    metrics_by_tmja_bucket: list[dict[str, Any]] | None = None,
    calibration_data: dict[str, Any] | None = None,
    residuals_by_fc: list[dict[str, Any]] | None = None,
    drift_by_year: list[dict[str, Any]] | None = None,
) -> str:
    """Generate a self-contained HTML evaluation report matching the original Streamlit style.

    Parameters
    ----------
    metrics : MetricsResult
        Pre-computed global metrics (RMSE, MAE, R2, ...).
    model_name : str
        Name of the evaluated model.
    training_config : dict | None
        Training configuration (architecture, input_cols, etc.).
    y_true, y_pred : np.ndarray
        True and predicted values (TxPen or output col).
    df : pd.DataFrame | None
        Full evaluation DataFrame with columns like TMJAFCDTV, TMJABCTV, TVr,
        Tolerance_IN_OUT, Erreur %, GEH, lat, lon, etc.  When provided, the
        report includes the barplot, outlier table and Folium map.
    sensitivity_html : str | None
        Pre-built sensitivity analysis HTML section. When provided, inserted
        after the Folium map section.
    metrics_ci95 : dict | None
        Bootstrap CI95 intervals (P1.1) keyed by ``tol_in_pct`` / ``p80`` /
        ``r2``. Each value is ``[ci_low, ci_high]`` or ``None`` when skipped.
    calibration_data : dict | None
        P4.1 — {"obs": [...], "pred": [...], "n": int} for the predicted
        vs observed scatter. None falls back to an empty-state message.
    residuals_by_fc : list[dict] | None
        P4.2 — per-functional-class residual summaries. Empty list falls
        back to an empty-state message.
    drift_by_year : list[dict] | None
        P4.3 — per-year metrics rows. Empty list falls back to an
        empty-state message.
    """

    # --- Build stats row (same structure as original rows[]) ---
    if df is not None and "TVr" in df.columns and "TMJABCTV" in df.columns:
        flow_metrics = _compute_flow_metrics(df)
        tol_counts = _compute_tolerance_counts(df)

        err_pct = pd.to_numeric(df.get("Erreur %"), errors="coerce")
        n_total_pct = int(err_pct.notna().sum())
        n_err_lt10 = int((err_pct < 10).sum())
        n_err_lt15 = int((err_pct < 15).sum())
        n_err_lt20 = int((err_pct < 20).sum())

        row = {
            "model": model_name,
            "n": flow_metrics["n"],
            "err_rel_med": flow_metrics["err_rel_med"],
            "err_abs_med": flow_metrics["err_abs_med"],
            "err_rel_p80": flow_metrics["err_rel_p80"],
            "err_abs_p80": flow_metrics["err_abs_p80"],
            "geh_lt5_pct": flow_metrics["geh_lt5_pct"],
            "geh_le10_pct": flow_metrics["geh_le10_pct"],
            "n_err_lt10": n_err_lt10,
            "pct_err_lt10": 100.0 * n_err_lt10 / n_total_pct if n_total_pct > 0 else float("nan"),
            "n_err_lt15": n_err_lt15,
            "pct_err_lt15": 100.0 * n_err_lt15 / n_total_pct if n_total_pct > 0 else float("nan"),
            "n_err_lt20": n_err_lt20,
            "pct_err_lt20": 100.0 * n_err_lt20 / n_total_pct if n_total_pct > 0 else float("nan"),
            **tol_counts,
        }
    else:
        # Fallback: compute basic stats from y_true / y_pred arrays
        nonzero = y_true != 0
        if nonzero.any():
            rel_errors = np.abs((y_true[nonzero] - y_pred[nonzero]) / y_true[nonzero]) * 100
            n_total_pct = len(rel_errors)
            n_err_lt10 = int((rel_errors < 10).sum())
            n_err_lt15 = int((rel_errors < 15).sum())
            n_err_lt20 = int((rel_errors < 20).sum())
        else:
            n_total_pct = 0
            n_err_lt10 = n_err_lt15 = n_err_lt20 = 0

        geh_vals = _geh(y_true, y_pred)
        row = {
            "model": model_name,
            "n": len(y_true),
            "err_rel_med": float(metrics.median_relative_error) if metrics.median_relative_error is not None else float("nan"),
            "err_abs_med": float(metrics.mae),
            "err_rel_p80": float("nan"),
            "err_abs_p80": float("nan"),
            "geh_lt5_pct": float(metrics.geh_pct_below_5),
            "geh_le10_pct": float(np.mean(geh_vals < 10) * 100),
            "n_err_lt10": n_err_lt10,
            "pct_err_lt10": 100.0 * n_err_lt10 / n_total_pct if n_total_pct > 0 else float("nan"),
            "n_err_lt15": n_err_lt15,
            "pct_err_lt15": 100.0 * n_err_lt15 / n_total_pct if n_total_pct > 0 else float("nan"),
            "n_err_lt20": n_err_lt20,
            "pct_err_lt20": 100.0 * n_err_lt20 / n_total_pct if n_total_pct > 0 else float("nan"),
            "tol_total": 0,
            "tol_in": 0,
            "tol_near": 0,
            "tol_out": 0,
        }

    # --- Card styling helpers ---
    def _card_style(v, good_thresh, mid_thresh, higher_is_better=False):
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return ""
        if higher_is_better:
            good = v >= good_thresh
            mid = v >= mid_thresh
        else:
            good = v <= good_thresh
            mid = v <= mid_thresh
        if good:
            return "background:linear-gradient(145deg,#f1fff7,#e6f9ef);border-color:#b8e9cf;"
        if mid:
            return "background:linear-gradient(145deg,#fff9ec,#fff2d9);border-color:#f2ddb0;"
        return "background:linear-gradient(145deg,#fff0f0,#ffe4e4);border-color:#efc0c0;"

    tol_ratio = row["tol_in"] / max(row["tol_total"], 1)
    tol_style = _card_style(tol_ratio, 0.75, 0.60, higher_is_better=True)
    err_style = _card_style(row.get("err_rel_med"), 12.0, 20.0)

    pct10 = row.get("pct_err_lt10", float("nan"))
    pct15 = row.get("pct_err_lt15", float("nan"))
    pct20 = row.get("pct_err_lt20", float("nan"))
    n10 = row.get("n_err_lt10", "-")
    n15 = row.get("n_err_lt15", "-")
    n20 = row.get("n_err_lt20", "-")

    pct10_style = _card_style(pct10, 60.0, 40.0, higher_is_better=True)
    pct15_style = _card_style(pct15, 70.0, 50.0, higher_is_better=True)
    pct20_style = _card_style(pct20, 80.0, 60.0, higher_is_better=True)

    # P1.1 - CI95 helper for inline display next to metric values
    def _ci_span(key: str, digits: int = 2, suffix: str = "") -> str:
        if not metrics_ci95:
            return ""
        ci = metrics_ci95.get(key)
        if not ci or len(ci) != 2:
            return ""
        lo, hi = ci
        if lo is None or hi is None:
            return ""
        return (
            f' <small style="font-size:11px;color:#56637a;font-weight:600;">'
            f'(CI95 [{lo:.{digits}f}{suffix}, {hi:.{digits}f}{suffix}])</small>'
        )

    tol_in_pct_val = (100.0 * row["tol_in"] / row["tol_total"]) if row.get("tol_total") else float("nan")
    r2_val = metrics.r_squared

    # --- Barplot ---
    if df is not None and "TVr" in df.columns and "TMJABCTV" in df.columns:
        bar_html = _make_barplot_html(df, title=f"{model_name} - validation")
    else:
        bar_html = "<p>Aucune donnee disponible.</p>"

    # --- Folium map ---
    if df is not None and "lat" in df.columns and "lon" in df.columns:
        map_html = _make_folium_map_html(df, model_name)
    else:
        map_html = "<p style='color:#888;font-style:italic;'>Donnees non disponibles pour la carte.</p>"

    # --- Outlier table (Erreur % > 15%) ---
    if df is not None and "Erreur %" in df.columns:
        out_df = df.copy()
        out_df["Erreur %"] = pd.to_numeric(out_df.get("Erreur %"), errors="coerce")
        out_df = out_df[out_df["Erreur %"] > 15].sort_values("Erreur %", ascending=False)
        outlier_cols = [c for c in out_df.columns if c not in ("geometry", "__geometry")]
        if not out_df.empty:
            _oth = "<tr>" + "".join(f"<th>{c}</th>" for c in outlier_cols) + "</tr>"
            _otrows = []
            for _, r in out_df.iterrows():
                err = r.get("Erreur %", float("nan"))
                if isinstance(err, float) and not math.isnan(err) and err > 50:
                    style = ' style="background:#fff0f0;"'
                elif isinstance(err, float) and not math.isnan(err) and err > 30:
                    style = ' style="background:#fff7ec;"'
                else:
                    style = ""
                cells = []
                for c in outlier_cols:
                    v = r.get(c, "-")
                    if isinstance(v, float):
                        v = "-" if (math.isnan(v) or math.isinf(v)) else f"{v:.2f}"
                    cells.append(f"<td>{v}</td>")
                _otrows.append(f"<tr{style}>" + "".join(cells) + "</tr>")
            outlier_html = (
                f'<table id="outlierTable" class="display" style="width:100%">'
                f'<thead>{_oth}</thead>'
                f'<tbody>{"".join(_otrows)}</tbody>'
                f'</table>'
            )
            outlier_count = len(out_df)
        else:
            outlier_html = "<p style='color:#2ecc71;font-weight:600;'>Aucun capteur avec une erreur &gt; 15%.</p>"
            outlier_count = 0
    else:
        outlier_html = "<p style='color:#888;font-style:italic;'>Donnees non disponibles.</p>"
        outlier_count = 0

    # --- Comparison table (single model row, same 18 columns as original) ---
    header_cells = [
        "Modele", "N", "Err.rel med (%)", "Err.abs med",
        "Err.rel p80 (%)", "Err.abs p80", "GEH<5 (%)", "GEH<=10 (%)",
        "Err<10% N", "Err<10% %", "Err<15% N", "Err<15% %", "Err<20% N", "Err<20% %",
        "Tol 1 Inclus", "Tol 2 Hors<15%", "Tol 3 Hors>15%", "Tol Total",
    ]
    thead = "<tr>" + "".join(f"<th>{h}</th>" for h in header_cells) + "</tr>"

    tag = ' <span style="background:#d7f5e8;color:#0a7a4b;border-radius:6px;padding:2px 6px;font-size:11px;">Meilleur</span>'
    cells = [
        f'{_html.escape(row["model"])}{tag}',
        str(row.get("n", "-")),
        _fmt(row.get("err_rel_med")),
        _fmt(row.get("err_abs_med")),
        _fmt(row.get("err_rel_p80")),
        _fmt(row.get("err_abs_p80")),
        _fmt(row.get("geh_lt5_pct")),
        _fmt(row.get("geh_le10_pct")),
        str(row.get("n_err_lt10", "-")),
        _fmt(row.get("pct_err_lt10")),
        str(row.get("n_err_lt15", "-")),
        _fmt(row.get("pct_err_lt15")),
        str(row.get("n_err_lt20", "-")),
        _fmt(row.get("pct_err_lt20")),
        str(row.get("tol_in", "-")),
        str(row.get("tol_near", "-")),
        str(row.get("tol_out", "-")),
        str(row.get("tol_total", "-")),
    ]
    tbody_row = '<tr style="background:#eafaf2;font-weight:700;">' + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    # --- P1.2 Stratification table per TMJOBCTV bucket ---
    if metrics_by_tmja_bucket:
        _bucket_headers = [
            "Bucket TMJOBCTV", "N", "Tol. inclus (N)", "Tol. inclus (%)",
            "p80 err.rel (%)", "R&sup2;",
        ]
        _bucket_thead = (
            "<tr>" + "".join(f"<th>{h}</th>" for h in _bucket_headers) + "</tr>"
        )
        _bucket_rows: list[str] = []
        for _b in metrics_by_tmja_bucket:
            _warn = bool(_b.get("low_sample_warning"))
            _row_style = (
                ' style="background:#fff7ec;"' if _warn else ""
            )
            _label_cell = _html.escape(str(_b.get("bucket", "-")))
            if _warn:
                _label_cell += (
                    ' <small style="color:#b97a00;font-weight:600;" '
                    'title="Moins de 10 echantillons — fiabilite limitee.">'
                    '(n&lt;10)</small>'
                )
            _bucket_rows.append(
                f"<tr{_row_style}>"
                f"<td>{_label_cell}</td>"
                f"<td>{int(_b.get('n_samples', 0))}</td>"
                f"<td>{int(_b.get('tol_in_n', 0))}</td>"
                f"<td>{_fmt(_b.get('tol_in_pct'))}</td>"
                f"<td>{_fmt(_b.get('p80'))}</td>"
                f"<td>{_fmt(_b.get('r2'), digits=4)}</td>"
                f"</tr>"
            )
        bucket_table_html = (
            '  <h2>Metriques stratifiees par tranche de TMJOBCTV</h2>\n'
            '  <p class="hint">Memes metriques recalculees sur 4 buckets de '
            'volume de trafic observe. Permet de detecter un modele performant '
            'globalement mais defaillant sur les capteurs faible/forte densite. '
            'Une ligne sur fond orange indique moins de 10 echantillons '
            '(metriques peu fiables).</p>\n'
            '  <div class="panel">\n'
            '    <table id="tmjaBucketTable" class="display" style="width:100%">\n'
            f'      <thead>{_bucket_thead}</thead>\n'
            f'      <tbody>{"".join(_bucket_rows)}</tbody>\n'
            '    </table>\n'
            '  </div>\n'
        )
    else:
        bucket_table_html = (
            '  <h2>Metriques stratifiees par tranche de TMJOBCTV</h2>\n'
            '  <p class="hint" style="color:#888;font-style:italic;">'
            'Stratification indisponible : colonne TMJOBCTV (ou TMJABCTV) '
            'absente des donnees de validation.</p>\n'
        )

    # --- P4.1 Calibration plot ---
    calibration_plot_inner = _make_calibration_plot_html(calibration_data)
    calibration_section_html = (
        '  <h2>Calibration : predit vs observe</h2>\n'
        '  <p class="hint">Chaque point est un capteur. La diagonale rouge '
        '<code>y = x</code> represente une prediction parfaite. Un nuage '
        'systematiquement en dessous (resp. au-dessus) indique un biais de '
        'sous-estimation (resp. sur-estimation).</p>\n'
        '  <div class="panel plot-wrap">\n'
        f'    {calibration_plot_inner}\n'
        '  </div>\n'
    )

    # --- P4.2 Residual boxplot by functional_class ---
    residuals_plot_inner = _make_residuals_by_fc_html(residuals_by_fc)
    residuals_section_html = (
        '  <h2>Residus par classe fonctionnelle</h2>\n'
        '  <p class="hint">Distribution des residus <code>pred &minus; obs</code> '
        'pour chaque classe fonctionnelle (FC). Une boite centree sur 0 indique '
        'un modele non biaise sur cette classe ; une boite decalee revele un '
        'biais systematique propre a la classe.</p>\n'
        '  <div class="panel plot-wrap">\n'
        f'    {residuals_plot_inner}\n'
        '  </div>\n'
    )

    # --- P4.3 Drift by year ---
    drift_inner = _make_drift_by_year_html(drift_by_year)
    drift_section_html = (
        '  <h2>Derive annuelle (metriques par annee)</h2>\n'
        '  <p class="hint">Memes metriques recalculees pour chaque annee '
        'presente dans le jeu de validation (au moins 10 echantillons). Une '
        'forte variation du R&sup2; ou du tol_in entre annees suggere une '
        'derive temporelle du modele.</p>\n'
        '  <div class="panel">\n'
        f'    {drift_inner}\n'
        '  </div>\n'
    )

    # --- Assemble full HTML ---
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Evaluation - {_html.escape(model_name)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdn.datatables.net/1.13.8/css/jquery.dataTables.min.css"/>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  <style>
    body{{font-family:Manrope,"Segoe UI",Arial,sans-serif;margin:0;background:radial-gradient(circle at 10% 0%,#e7f0ff 0%,#f2f7ff 28%,#ecf3fb 62%,#e8f0f8 100%);color:#122033;}}
    .wrap{{max-width:1600px;margin:0 auto;padding:24px 22px 30px;}}
    h1{{margin:0 0 6px;font-size:28px;font-weight:800;color:#0f2f57;}}
    .subtitle{{color:#56637a;font-size:13px;margin-bottom:16px;}}
    .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:18px;}}
    .card{{background:linear-gradient(180deg,#fff,#f9fcff);border-radius:16px;padding:14px;box-shadow:0 10px 22px rgba(13,61,120,.08);border:1px solid #dfe8f3;}}
    .k{{font-size:12px;color:#6b778c;font-weight:600;}}
    .v{{font-size:22px;font-weight:800;margin-top:6px;color:#0d3b66;}}
    .best-tag{{display:inline-block;padding:4px 10px;border-radius:999px;background:#d7f5e8;color:#0a7a4b;font-weight:700;font-size:12px;}}
    .panel{{background:linear-gradient(180deg,#fff,#fbfdff);border:1px solid #dfe7f2;border-radius:16px;padding:14px;box-shadow:0 10px 22px rgba(12,52,103,.07);margin-bottom:16px;overflow-x:auto;}}
    h2{{margin:20px 0 10px;font-size:18px;font-weight:800;}}
    table.dataTable thead th{{background:#f0f6ff;color:#12345a;font-weight:700;}}
    table.dataTable tbody td{{font-size:12px;}}
    table.dataTable tbody tr:hover{{background:#f4f9ff!important;}}
    .plot-wrap{{margin-top:14px;}}
    .hint{{color:#56637a;font-size:12px;margin-top:4px;}}
  </style>
</head>
<body>
<div class="wrap">
  <h1>Evaluation sur donnees de validation</h1>
  <div class="subtitle">Modele : <code>{_html.escape(model_name)}</code> | {row['n']} capteurs</div>

  <div class="cards">
    <div class="card" style="background:linear-gradient(145deg,#eef6ff,#e6f0ff);border-color:#bfd5f3;">
      <div class="k">Modele evalue</div>
      <div class="v" style="font-size:18px;overflow-wrap:anywhere;">{_html.escape(model_name)}</div>
      <div class="best-tag">Tolerance max + erreurs minimisees</div>
    </div>
    <div class="card" style="{tol_style}">
      <div class="k">Capteurs tolerance inclus</div>
      <div class="v">{row['tol_in']}/{row['tol_total']} <small style="font-size:13px;color:#56637a;">({_fmt(tol_in_pct_val)}%)</small>{_ci_span('tol_in_pct', digits=2, suffix='%')}</div>
    </div>
    <div class="card" style="{err_style}">
      <div class="k">Err. rel. mediane</div>
      <div class="v">{_fmt(row.get('err_rel_med'))}%</div>
    </div>
    <div class="card">
      <div class="k">Err. rel. p80</div>
      <div class="v">{_fmt(row.get('err_rel_p80'))}%{_ci_span('p80', digits=2, suffix='%')}</div>
    </div>
    <div class="card">
      <div class="k">R&sup2;</div>
      <div class="v">{_fmt(r2_val, digits=4)}{_ci_span('r2', digits=4)}</div>
    </div>
    <div class="card">
      <div class="k">GEH &lt; 5</div>
      <div class="v">{_fmt(row.get('geh_lt5_pct'))}%</div>
    </div>
    <div class="card" style="{pct10_style}">
      <div class="k">Capteurs erreur &lt; 10%</div>
      <div class="v">{n10} <small style="font-size:14px;color:#56637a;">({_fmt(pct10)}%)</small></div>
    </div>
    <div class="card" style="{pct15_style}">
      <div class="k">Capteurs erreur &lt; 15%</div>
      <div class="v">{n15} <small style="font-size:14px;color:#56637a;">({_fmt(pct15)}%)</small></div>
    </div>
    <div class="card" style="{pct20_style}">
      <div class="k">Capteurs erreur &lt; 20%</div>
      <div class="v">{n20} <small style="font-size:14px;color:#56637a;">({_fmt(pct20)}%)</small></div>
    </div>
  </div>

  <h2>Tableau des metriques detaillees</h2>
  <p class="hint">Metriques calculees sur les donnees de validation. Tolerance : 1 = inclus, 2 = hors &lt;15% borne, 3 = hors &gt;15% borne.</p>
  <div class="panel">
    <table id="valTable" class="display" style="width:100%">
      <thead>{thead}</thead>
      <tbody>{tbody_row}</tbody>
    </table>
  </div>

{bucket_table_html}
{calibration_section_html}
{residuals_section_html}
{drift_section_html}
  <h2>Barplot - TMJOBCTV vs TVr (validation)</h2>
  <div class="panel plot-wrap">
    {bar_html}
  </div>

  <h2>Capteurs avec ecart &gt; 15% ({outlier_count} capteur(s))</h2>
  <p class="hint">Liste triee par erreur decroissante. Fond rose = erreur &gt; 50%, fond orange clair = erreur &gt; 30%.</p>
  <div class="panel">
    {outlier_html}
  </div>

  <h2>Carte des capteurs (validation)</h2>
  <p class="hint">Cliquez sur un capteur pour voir toutes ses informations. Couleur = tolerance (vert = inclus, orange = hors &lt;15%, rouge = hors &gt;15%). Taille = TMJOBCTV.</p>
  <div class="panel" style="padding:6px;overflow:hidden;">
    {map_html}
  </div>

  {sensitivity_html if sensitivity_html else ""}

</div>
<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
<script src="https://cdn.datatables.net/1.13.8/js/jquery.dataTables.min.js"></script>
<script>
$(document).ready(function(){{
  $('#valTable').DataTable({{
    pageLength: 25,
    order: [[14, 'desc'], [2, 'asc'], [4, 'asc']],
  }});
  if ($('#outlierTable').length) {{
    $('#outlierTable').DataTable({{
      pageLength: 25,
      order: [[7, 'desc']],
    }});
  }}
  if ($('#tmjaBucketTable').length) {{
    // 4 buckets total — no pagination / search / info needed.
    $('#tmjaBucketTable').DataTable({{
      paging: false,
      searching: false,
      info: false,
      ordering: false,
    }});
  }}
  if ($('#driftByYearTable').length) {{
    // Up to 7 rows — no pagination / search / info needed; allow sorting.
    $('#driftByYearTable').DataTable({{
      paging: false,
      searching: false,
      info: false,
      order: [[0, 'asc']],
    }});
  }}
}});
</script>
</body>
</html>"""
    return html


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
    renames = {
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
    for old, new in renames.items():
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
        # Load from disk
        model_path = Path(body.model_dir) / body.model_name
        if not model_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Dossier modele introuvable : {model_path}",
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
    val_renames = {
        # FCD throughput aliases
        "TMJATV": "TMJAFCDTV", "TMJFCDTV": "TMJAFCDTV", "TMJOFCDTV": "TMJAFCDTV",
        "TMJAPL": "TMJAFCDPL", "TMJFCDPL": "TMJAFCDPL", "TMJOFCDPL": "TMJAFCDPL",
        # Sensor counts (Boucle Comptage)
        "TMJOBCTV": "TMJABCTV", "TMJOBCPL": "TMJABCPL",
        # Penetration rates
        "TxPen": "TxPenTVRef", "TxPenPL": "TxPenPLRef",
    }
    for old, new in val_renames.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]

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
    flows: np.ndarray | None = None
    for flow_col in ("TMJOBCTV", "TMJABCTV"):
        if flow_col in sub.columns:
            flows = pd.to_numeric(sub[flow_col], errors="coerce").to_numpy(dtype=np.float64)
            break
    if flows is None:
        logger.warning(
            "HD/LD split disabled: ni TMJOBCTV ni TMJABCTV trouve dans les donnees de validation"
        )
    metrics = _compute_metrics(y_true, y_pred, body.high_flow_threshold, flows=flows)

    # --- Build enriched DataFrame for the HTML report ---
    # Add TVr, tolerance, error columns (same logic as evaluate_best_model.py)
    report_df = sub.copy()
    report_df["TP_redressement"] = pd.to_numeric(y_pred, errors="coerce")

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
        # Fallback: treat y_pred directly as TVr
        report_df["TVr"] = pd.to_numeric(y_pred, errors="coerce")

    # Ensure TMJABCTV is numeric
    if "TMJABCTV" in report_df.columns:
        report_df["TMJABCTV"] = pd.to_numeric(report_df["TMJABCTV"], errors="coerce")

    # Erreur absolue & Erreur %
    if "TVr" in report_df.columns and "TMJABCTV" in report_df.columns:
        report_df["Erreur absolue"] = (report_df["TVr"] - report_df["TMJABCTV"]).abs().round(1)
        denom = report_df["TMJABCTV"].replace([np.inf, -np.inf], np.nan)
        report_df["Erreur %"] = (
            report_df["Erreur absolue"] / denom * 100.0
        ).replace([np.inf, -np.inf], np.nan)
    else:
        report_df["Erreur absolue"] = np.nan
        report_df["Erreur %"] = np.nan

    # GEH
    if "TVr" in report_df.columns and "TMJABCTV" in report_df.columns:
        a = report_df["TVr"] / 24.0
        b = report_df["TMJABCTV"] / 24.0
        with np.errstate(divide="ignore", invalid="ignore"):
            geh_vals = np.sqrt(2.0 * (a - b) ** 2 / (a + b))
        report_df["GEH"] = pd.to_numeric(geh_vals, errors="coerce").replace([np.inf, -np.inf], np.nan)

    # lat/lon from __lat/__lon if needed
    if "__lat" in report_df.columns and "lat" not in report_df.columns:
        report_df["lat"] = pd.to_numeric(report_df["__lat"], errors="coerce")
    if "__lon" in report_df.columns and "lon" not in report_df.columns:
        report_df["lon"] = pd.to_numeric(report_df["__lon"], errors="coerce")

    # Tolerance columns (TVrmin, TVrmax, Tolerance_IN_OUT)
    if "TVr" in report_df.columns and "TMJABCTV" in report_df.columns:
        report_df = _add_tolerance_columns(report_df)

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

    # Build sensitivity analysis section
    sensitivity_html = None
    try:
        if model is not None and input_cols:
            mu_x_arr = np.array(x_mean, dtype=np.float64)
            s_x_arr = np.array(x_std, dtype=np.float64)
            mu_y_arr = np.array(y_mean, dtype=np.float64)
            s_y_arr = np.array(y_std, dtype=np.float64)
            sensitivity_html = _build_sensitivity_section_html(
                df=report_df,
                model=model,
                mu_x=mu_x_arr,
                s_x=s_x_arr,
                mu_y=mu_y_arr,
                s_y=s_y_arr,
                input_cols=input_cols,
            )
    except Exception as exc:
        logger.warning("Sensitivity analysis failed (non-blocking): %s", exc)
        sensitivity_html = None

    # Generate HTML report
    report_html = _generate_html_report(
        metrics=metrics,
        model_name=model_name,
        training_config=training_config,
        y_true=y_true,
        y_pred=y_pred,
        df=report_df,
        sensitivity_html=sensitivity_html,
        metrics_ci95=metrics_ci95,
        metrics_by_tmja_bucket=metrics_by_tmja_bucket,
        calibration_data=calibration_data,
        residuals_by_fc=residuals_by_fc,
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

        report_html = _generate_html_report(
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

    model_path = Path(model_dir) / model_name
    if not model_path.exists() or not model_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Dossier modele introuvable : {model_path}")

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
    # 3. Determine the model type (TV / PL) from the target column.
    # ──────────────────────────────────────────────────────────────────────
    from ..services.ml.types import PL_CONFIG, TV_CONFIG

    output_cols = training_config.get("output_cols") or []
    target = (output_cols[0] if output_cols else "TxPen").lower()
    type_config = PL_CONFIG if "pl" in target else TV_CONFIG

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
