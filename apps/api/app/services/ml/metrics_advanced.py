"""Advanced evaluation metrics (bootstrap, stratification, calibration, drift).

Extracted from ``apps/api/app/routers/evaluation.py`` during the T2 refactor.
This module groups the per-axis post-processing computations that augment
the base ``MetricsResult`` (RMSE/MAE/R²/GEH) with:

* P1.1 — Bootstrap 95% confidence intervals on tol_in_pct / p80 / R².
* P1.2 — Stratification of (tol_in_pct, p80, r2, n_samples) by TMJOBCTV bucket.
* P4.1 — Calibration scatter data (pred vs obs).
* P4.2 — Residuals grouped by functional_class (raw + summary stats).
* P4.3 — Annual drift table (R² / MAE / tol_in_pct / p80 per year_mapped).

The metric adapters (``_metric_*``) all follow the signature
``(obs, pred, weights | None) -> float`` so :func:`bootstrap_ci95` can reuse
the same sampler regardless of the underlying statistic.

Everything in this module is pure-numpy / pure-pandas and has zero
side effects — easy to unit-test on synthetic frames.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__all__ = [
    "bootstrap_ci95",
    "_metric_r2",
    "_metric_p80_err_rel",
    "_metric_tol_in_pct",
    "_stratify_by_tmja",
    "_compute_calibration_data",
    "_resolve_functional_class",
    "_compute_residuals_by_fc",
    "_compute_drift_by_year",
    "_BOOTSTRAP_MIN_SAMPLES",
    "_TMJA_BUCKETS",
    "_TMJA_LOW_SAMPLE_THRESHOLD",
    "_CALIBRATION_MAX_POINTS",
    "_DRIFT_MIN_SAMPLES",
]


# ---------------------------------------------------------------------------
# P1.1 — Bootstrap CI95 on tol_in_pct, p80, R-squared
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
        ss_res = float(np.sum(w * residuals**2))
        ss_tot = float(np.sum(w * (obs - mean_obs) ** 2))
    else:
        ss_res = float(np.sum(residuals**2))
        ss_tot = float(np.sum((obs - np.mean(obs)) ** 2))
    if ss_tot <= 0:
        return 0.0
    return 1.0 - ss_res / ss_tot


def _metric_p80_err_rel(obs: np.ndarray, pred: np.ndarray, w: np.ndarray | None) -> float:
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


def _metric_tol_in_pct(obs: np.ndarray, pred: np.ndarray, w: np.ndarray | None) -> float:
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
        tol_codes = pd.to_numeric(df["Tolerance_IN_OUT"], errors="coerce").to_numpy(
            dtype=np.float64
        )

    obs_p80_arr: np.ndarray | None = None
    pred_p80_arr: np.ndarray | None = None
    if "TMJABCTV" in df.columns and "TVr" in df.columns:
        obs_p80_arr = pd.to_numeric(df["TMJABCTV"], errors="coerce").to_numpy(dtype=np.float64)
        pred_p80_arr = pd.to_numeric(df["TVr"], errors="coerce").to_numpy(dtype=np.float64)

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
            n_valid = int(valid.sum())
            if n_valid > 0:
                tol_in_n_val = int((codes_b[valid] == 1).sum())
                tol_in_pct_val = 100.0 * tol_in_n_val / n_valid

        # p80 of |obs - pred| / obs * 100. Use the dedicated TVr/TMJABCTV
        # columns when available; fall back to (y_true, y_pred).
        p80_val: float = float("nan")
        if n > 0:
            if obs_p80_arr is not None and pred_p80_arr is not None:
                obs_b = obs_p80_arr[mask]
                pred_b = pred_p80_arr[mask]
            else:
                obs_b = y_true[mask]
                pred_b = y_pred[mask]
            with np.errstate(divide="ignore", invalid="ignore"):
                nonzero = (obs_b != 0) & np.isfinite(obs_b) & np.isfinite(pred_b)
                if nonzero.any():
                    err_rel = np.abs((obs_b[nonzero] - pred_b[nonzero]) / obs_b[nonzero]) * 100.0
                    p80_val = float(np.nanpercentile(err_rel, 80))

        # R-squared on (y_true, y_pred) restricted to the bucket.
        r2_val: float = float("nan")
        if n > 1:
            obs_r = y_true[mask]
            pred_r = y_pred[mask]
            finite = np.isfinite(obs_r) & np.isfinite(pred_r)
            if int(finite.sum()) > 1:
                obs_r = obs_r[finite]
                pred_r = pred_r[finite]
                ss_res = float(np.sum((obs_r - pred_r) ** 2))
                ss_tot = float(np.sum((obs_r - np.mean(obs_r)) ** 2))
                if ss_tot > 0:
                    r2_val = 1.0 - ss_res / ss_tot

        entry = {
            "bucket": label,
            "range": range_repr,
            "n_samples": n,
            "tol_in_n": tol_in_n_val,
            "tol_in_pct": (round(tol_in_pct_val, 2) if math.isfinite(tol_in_pct_val) else None),
            "p80": (round(p80_val, 4) if math.isfinite(p80_val) else None),
            "r2": round(r2_val, 6) if math.isfinite(r2_val) else None,
            "low_sample_warning": 0 < n < _TMJA_LOW_SAMPLE_THRESHOLD,
        }
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
    unique_classes = sorted({int(v) for v in fc_vals if np.isfinite(v) and float(v).is_integer()})
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
        results.append(
            {
                "fc": int(fc),
                "n": int(res_b.size),
                "median": round(float(np.median(res_b)), 4),
                "mean": round(float(np.mean(res_b)), 4),
                "q1": round(float(np.percentile(res_b, 25)), 4),
                "q3": round(float(np.percentile(res_b, 75)), 4),
                "min": round(float(np.min(res_b)), 4),
                "max": round(float(np.max(res_b)), 4),
                "residuals": [round(float(v), 4) for v in res_sample],
            }
        )
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

    unique_years = sorted({int(round(v)) for v in ym if np.isfinite(v)})
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

        ss_res = float(np.sum(res_b**2))
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

        results.append(
            {
                "year_mapped": int(year_val),
                "year_label": inv_label.get(year_val, f"year_{year_val}"),
                "n_samples": n,
                "r2": round(r2, 6),
                "mae": round(mae, 4),
                "tol_in_pct": round(tol_in_pct, 2) if math.isfinite(tol_in_pct) else None,
                "p80": round(p80, 4) if math.isfinite(p80) else None,
            }
        )
    return results
