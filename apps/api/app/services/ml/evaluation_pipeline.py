"""Unified evaluation pipeline for TV and PL models.

Reproduces the exact logic from ``xScripts/evaluate_best_model.py`` and
``evaluate_best_model_PL.py``, operating entirely in memory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from .normalize import denormalize, simple_norm
from .types import ModelTypeConfig

if TYPE_CHECKING:
    from .training_pipeline import TrainedModelArtifact


# ---------------------------------------------------------------------------
# Column alias resolution for evaluation data
# ---------------------------------------------------------------------------


def _resolve_eval_aliases(df: pd.DataFrame, type_config: ModelTypeConfig) -> pd.DataFrame:
    """Apply column aliases + derive flag_comptage on evaluation data."""
    for src, dst in type_config.column_aliases.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = pd.to_numeric(df[src], errors="coerce").round(4 if "TxPen" in dst else 2)

    # Reverse aliases for convenience
    fcd = type_config.eval_numerator_fcd  # TMJAFCDTV or TMJAFCDPL
    if fcd not in df.columns:
        for src, dst in type_config.column_aliases.items():
            if dst == fcd and src in df.columns:
                df[fcd] = pd.to_numeric(df[src], errors="coerce").round(2)
                break

    if "flag_comptage" not in df.columns:
        if "Type" in df.columns:
            types = df["Type"].astype(str).str.strip().str.lower()
            df["flag_comptage"] = types.isin(["per", "tou"]).astype(int)
        else:
            df["flag_comptage"] = 0

    return df


# ---------------------------------------------------------------------------
# Test-time augmentation (TTA) — P4.7
# ---------------------------------------------------------------------------


def apply_model_tta(
    model: Any,
    x_norm: np.ndarray,
    n_iter: int = 5,
    noise_std: float = 0.01,
    seed: int = 1750,
) -> np.ndarray:
    """Run inference with test-time augmentation (Gaussian noise + averaging).

    The model is queried ``n_iter`` times. For ``n_iter == 1`` (the default
    used by the API when TTA is OFF) the function performs a single
    noise-free ``model.predict`` call and is therefore numerically identical
    to vanilla inference — that's how we keep TTA fully backward-compatible.

    When ``n_iter > 1``, each iteration adds zero-mean Gaussian noise of std
    ``noise_std`` to the normalized input ``x_norm``. The seed sequence is
    derived from ``seed + i`` so the result is fully reproducible across
    runs. Predictions are averaged across iterations.

    Parameters
    ----------
    model : keras.Model
        A trained Keras/TF model accepting a ``(batch, n_features)`` array.
    x_norm : np.ndarray
        Input features ALREADY normalized (z-scored). Noise is therefore
        expressed in units of one standard deviation: ``noise_std=0.01``
        means a 1% smoothing of each feature.
    n_iter : int, default 5
        Number of forward passes. Must be ``>= 1``.
    noise_std : float, default 0.01
        Standard deviation of the additive Gaussian noise (in normalized
        space). Ignored when ``n_iter == 1``.
    seed : int, default 1750
        Base seed for ``np.random.default_rng`` — matches the project-wide
        reproducibility seed.

    Returns
    -------
    np.ndarray
        Mean prediction across the ``n_iter`` forward passes, with shape
        ``model.predict(x_norm).shape``.
    """
    if n_iter < 1:
        raise ValueError(f"n_iter must be >= 1, got {n_iter}")

    x_norm = np.asarray(x_norm, dtype=np.float32)

    # Fast path: a single noise-free call. Must be bit-identical to the
    # legacy `model.predict(x_norm, verbose=0)` so TTA stays opt-in.
    if n_iter == 1:
        return model.predict(x_norm, verbose=0)

    preds_sum: np.ndarray | None = None
    for i in range(n_iter):
        rng = np.random.default_rng(seed + i)
        noise = rng.normal(0.0, noise_std, x_norm.shape).astype(np.float32)
        x_aug = x_norm + noise
        y_i = model.predict(x_aug, verbose=0)
        preds_sum = y_i if preds_sum is None else preds_sum + y_i

    assert preds_sum is not None  # n_iter >= 2 guarantees this
    return preds_sum / float(n_iter)


# ---------------------------------------------------------------------------
# apply_model (unified TV / PL)
# ---------------------------------------------------------------------------


def apply_model(
    data: pd.DataFrame,
    artifact: TrainedModelArtifact,
    type_config: ModelTypeConfig,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Apply a trained model to *data* and compute predicted flow + errors.

    For TV: TVr = TMJAFCDTV / TxPen_pred * 100
    For PL: DPL = TMJAFCDPL / TxPen_pred * 100
    """
    config = config or {}
    df = data.copy()
    df = _resolve_eval_aliases(df, type_config)

    input_cols = artifact.input_cols
    mu_x = artifact.mu_x.copy()
    s_x = artifact.sigma_x.copy()
    mu_y = artifact.mu_y.copy()
    s_y = artifact.sigma_y.copy()

    # Bug 7 — replay feature engineering on the evaluation df. The artifact's
    # training_config carries the exact set of derivations applied at train
    # time (ratio_PLTV, log_<col>, fc_*) so the same columns are present in
    # the X matrix. Without this, models trained with feature_engineering
    # would crash with KeyError on ratio_PLTV / log_TMJOBCTV / fc_1...
    _tc = getattr(artifact, "training_config", None) or {}
    _fe = dict(_tc.get("feature_engineering") or {})
    # Allow the caller's `config` to override the artifact's echo — useful
    # when the artifact was trained before the echo existed.
    _fe.update(dict(config.get("feature_engineering") or {}))

    if _fe:
        # Import locally to avoid pulling sklearn/data_prep at module import.
        from .data_prep import (
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

    # Year mapping. Falls back to common column names ("Annee", "annee",
    # "Year", "year") when the caller forgot to set year_column_name in the
    # evaluation config — fixes the "modele avec annee ne marche pas" bug
    # reported on Lyon, where the training config carried the mapping but the
    # eval call didn't echo it back.
    if "year_mapped" in input_cols and "year_mapped" not in df.columns:
        year_mapping = config.get("year_value_mapping", {})
        year_col = config.get("year_column_name", "") or ""
        if not year_col:
            for cand in ("Annee", "annee", "Year", "year"):
                if cand in df.columns:
                    year_col = cand
                    break
        if year_col and year_col in df.columns and year_mapping:
            df["year_mapped"] = df[year_col].astype(str).map(year_mapping)
            if df["year_mapped"].isna().any():
                df["year_mapped"] = df["year_mapped"].fillna(df["year_mapped"].mean())
        elif year_col and year_col in df.columns:
            # No explicit mapping — coerce the year column to numeric directly.
            df["year_mapped"] = pd.to_numeric(df[year_col], errors="coerce")
            df["year_mapped"] = df["year_mapped"].fillna(df["year_mapped"].median())
        else:
            median_value = (
                sorted(year_mapping.values())[len(year_mapping) // 2] if year_mapping else 0
            )
            df["year_mapped"] = median_value

    # Fill missing input cols with NaN
    missing = [c for c in input_cols if c not in df.columns]
    for c in missing:
        df[c] = np.nan

    x = df[input_cols].apply(pd.to_numeric, errors="coerce")
    x = x.fillna(x.median(numeric_only=True))

    # Handle on_off_norm expansion
    n_inputs = len(input_cols)
    if len(mu_x) < n_inputs:
        on_off_norm = None
        if config and "on_off_norm" in config:
            candidate = np.array(config["on_off_norm"], dtype=bool)
            if len(candidate) == n_inputs:
                on_off_norm = candidate
        if on_off_norm is None:
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

    x_norm = simple_norm(x.values, mu_x, s_x)
    y_norm = artifact.model.predict(x_norm.astype(np.float32), verbose=0)
    y = denormalize(y_norm, mu_y, s_y)

    # TxPen predicted
    df["TP_redressement"] = pd.to_numeric(y[:, 0], errors="coerce")

    # Predicted flow: numerator_fcd / TxPen * 100
    pred_col = type_config.eval_predicted_col  # "TVr" or "DPL"
    ref_col = type_config.eval_reference_col  # "TMJABCTV" or "TMJABCPL"
    fcd_col = type_config.eval_numerator_fcd  # "TMJAFCDTV" or "TMJAFCDPL"

    df[pred_col] = pd.to_numeric(df[fcd_col], errors="coerce") / df["TP_redressement"] * 100.0

    for col in [pred_col, ref_col]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Errors
    df["Erreur absolue"] = (df[pred_col] - df[ref_col]).abs().round(1)
    denom = df[ref_col].replace([np.inf, -np.inf], np.nan)
    df["Erreur %"] = (df["Erreur absolue"] / denom * 100.0).replace([np.inf, -np.inf], np.nan)

    # GEH on daily flows (TMJA already daily — no /24 conversion)
    a = df[pred_col]
    b = df[ref_col]
    with np.errstate(divide="ignore", invalid="ignore"):
        geh = np.sqrt(2.0 * (a - b) ** 2 / (a + b))
    df["GEH"] = pd.to_numeric(geh, errors="coerce").replace([np.inf, -np.inf], np.nan)

    # Coordinates
    if "__lat" in df.columns and "__lon" in df.columns:
        df["lat"] = pd.to_numeric(df["__lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["__lon"], errors="coerce")

    return df


# ---------------------------------------------------------------------------
# Dynamic tolerance (identical for TV and PL)
# ---------------------------------------------------------------------------


def add_tolerance_columns(
    df: pd.DataFrame,
    type_config: ModelTypeConfig,
) -> pd.DataFrame:
    """Add dynamic tolerance bands and Tolerance_IN_OUT classification.

    Works for both TV (using TVr) and PL (using DPL).
    """
    out = df.copy()
    pred_col = type_config.eval_predicted_col
    ref_col = type_config.eval_reference_col

    out[pred_col] = pd.to_numeric(out[pred_col], errors="coerce")

    def erreur_pourcentage(val: float) -> float:
        if pd.isna(val):
            return np.nan
        if val > 10000:
            return 0.14
        if val > 5000:
            return 0.18
        if val > 2000:
            return 0.18
        return 0.25

    out["Erreur_dyn"] = out[pred_col].apply(erreur_pourcentage)
    min_col = f"{pred_col}min"
    max_col = f"{pred_col}max"
    out[min_col] = out[pred_col] * (1 - out["Erreur_dyn"])
    out[max_col] = out[pred_col] * (1 + out["Erreur_dyn"])

    mask10k = out[pred_col] > 10000
    out.loc[mask10k, min_col] = np.round(out.loc[mask10k, min_col], -2)
    out.loc[mask10k, max_col] = np.round(out.loc[mask10k, max_col], -2)

    mask500 = out[pred_col] < 500
    out.loc[mask500, min_col] = 10 * np.floor(out.loc[mask500, min_col] / 10)
    out.loc[mask500, max_col] = 10 * np.ceil(out.loc[mask500, max_col] / 10)

    mask_middle = out[pred_col] >= 500
    out.loc[mask_middle, min_col] = 100 * np.floor(out.loc[mask_middle, min_col] / 100)
    out.loc[mask_middle, max_col] = 100 * np.ceil(out.loc[mask_middle, max_col] / 100)

    out.loc[out[min_col].notna() & (out[min_col] < 100), min_col] = 0
    out.loc[out[max_col].notna() & (out[max_col] < 100), max_col] = 100

    for c in [ref_col, min_col, max_col]:
        out[c] = pd.to_numeric(out[c], errors="coerce")

    tmja = out[ref_col]
    lower = np.minimum(out[min_col], out[max_col])
    upper = np.maximum(out[min_col], out[max_col])

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


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def compute_flow_metrics(
    df: pd.DataFrame,
    type_config: ModelTypeConfig,
    above: bool | None = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    """Compute error and GEH metrics on evaluated data."""
    d = df.copy()
    pred_col = type_config.eval_predicted_col
    ref_col = type_config.eval_reference_col

    d[ref_col] = pd.to_numeric(d.get(ref_col), errors="coerce")
    d[pred_col] = pd.to_numeric(d.get(pred_col), errors="coerce")
    d["GEH"] = pd.to_numeric(d.get("GEH"), errors="coerce")

    if above is not None and threshold is not None:
        mask = d[ref_col] > threshold if above else d[ref_col] < threshold
        d = d.loc[mask]
    d = d.dropna(subset=[ref_col, pred_col])

    if d.empty:
        return {
            "n": 0,
            "err_rel_med": np.nan,
            "err_abs_med": np.nan,
            "err_rel_p80": np.nan,
            "err_abs_p80": np.nan,
            "geh_lt5_pct": np.nan,
            "geh_le10_pct": np.nan,
        }

    err_abs = (d[pred_col] - d[ref_col]).abs().astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        err_rel = np.where(d[ref_col] != 0, err_abs / d[ref_col] * 100.0, np.nan)
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


def compute_tolerance_counts(df: pd.DataFrame) -> dict[str, int]:
    """Count Tolerance_IN_OUT categories."""
    tol = pd.to_numeric(df.get("Tolerance_IN_OUT"), errors="coerce")
    return {
        "tol_total": int(tol.notna().sum()),
        "tol_in": int((tol == 1).sum()),
        "tol_near": int((tol == 2).sum()),
        "tol_out": int((tol == 3).sum()),
    }


def choose_best_model(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Select best model by tolerance then errors (same ranking as original)."""
    df_rows = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan).fillna(999999.0)
    ranked = df_rows.sort_values(
        by=["tol_in", "err_rel_med", "err_rel_p80", "err_abs_med", "err_abs_p80"],
        ascending=[False, True, True, True, True],
    )
    return ranked.iloc[0].to_dict()


# ---------------------------------------------------------------------------
# Full evaluation pipeline
# ---------------------------------------------------------------------------


def run_evaluation(
    models: dict[str, TrainedModelArtifact],
    val_df: pd.DataFrame,
    type_config: ModelTypeConfig,
    config: dict[str, Any] | None = None,
    stats_scope: str = "flag1",
) -> dict[str, Any]:
    """Evaluate all trained models on validation data.

    Parameters
    ----------
    models : dict from ``run_training()``.
    val_df : validation DataFrame.
    type_config : TV_CONFIG or PL_CONFIG.
    config : optional config dict (for year mapping etc.).
    stats_scope : "flag1" (permanent/tournant only) or "global".

    Returns
    -------
    Dict with keys:
        - "rows": list of per-model metric dicts
        - "best_model": name of best model
        - "best_metrics": metric dict of best model
        - "model_results": dict[run_name -> evaluated DataFrame]
    """
    config = config or {}
    rows: list[dict[str, Any]] = []
    model_results: dict[str, pd.DataFrame] = {}

    for name, artifact in models.items():
        try:
            results = apply_model(val_df, artifact, type_config, config=config)
            results = add_tolerance_columns(results, type_config)

            # Filter scope
            if stats_scope == "flag1":
                if "flag_comptage" in results.columns:
                    stats_df = results[results["flag_comptage"] == 1].copy()
                elif "Type" in results.columns:
                    stats_df = results[
                        results["Type"].astype(str).str.strip().isin(["Per", "Tou"])
                    ].copy()
                else:
                    stats_df = results.copy()
            else:
                stats_df = results.copy()

            metrics = compute_flow_metrics(stats_df, type_config)
            tol = compute_tolerance_counts(stats_df)

            err_pct = pd.to_numeric(stats_df.get("Erreur %"), errors="coerce")
            n_total_pct = int(err_pct.notna().sum())
            n_lt10 = int((err_pct < 10).sum())
            n_lt15 = int((err_pct < 15).sum())
            n_lt20 = int((err_pct < 20).sum())

            row = {
                "model": name,
                **metrics,
                "n_err_lt10": n_lt10,
                "pct_err_lt10": 100.0 * n_lt10 / n_total_pct if n_total_pct > 0 else float("nan"),
                "n_err_lt15": n_lt15,
                "pct_err_lt15": 100.0 * n_lt15 / n_total_pct if n_total_pct > 0 else float("nan"),
                "n_err_lt20": n_lt20,
                "pct_err_lt20": 100.0 * n_lt20 / n_total_pct if n_total_pct > 0 else float("nan"),
                **tol,
            }
            rows.append(row)
            model_results[name] = results

        except Exception:
            import traceback

            traceback.print_exc()
            continue

    if not rows:
        raise RuntimeError("No model could be evaluated successfully.")

    best = choose_best_model(rows)
    best_name = str(best["model"])

    return {
        "rows": rows,
        "best_model": best_name,
        "best_metrics": best,
        "model_results": model_results,
    }


# ---------------------------------------------------------------------------
# K-fold cross-validation (P1.3)
# ---------------------------------------------------------------------------
# The implementation lives in services/ml/kfold.py to keep the import graph
# clean (kfold pulls run_training, which is heavy). We re-export it here so
# callers can keep their `from .evaluation_pipeline import kfold_train_eval`
# imports stable as the audit plan expects.


def kfold_train_eval(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """K-fold cross-validation on a trained-model configuration.

    See ``services.ml.kfold.kfold_train_eval`` for the full signature and
    semantics. This thin re-export lets external callers import from
    ``evaluation_pipeline`` (P1.3 surface) without dragging in
    ``run_training`` at module import time.
    """
    from .kfold import kfold_train_eval as _impl

    return _impl(*args, **kwargs)
