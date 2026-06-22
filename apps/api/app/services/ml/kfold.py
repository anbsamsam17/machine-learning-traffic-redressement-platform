"""K-fold cross-validation helper for trained models (P1.3).

Re-trains a model k times on different folds of the same dataset using the
exact same hyper-parameters as the original training run, then computes
held-out metrics per fold. This gives a measure of variance — a model whose
``tol_in_pct`` swings by ±10pts across folds is not robust, even if its
single-split score looks good.

The implementation calls the existing public training pipeline
(`run_training`) so the same callbacks, seeding and TF state management
apply. Each fold passes a row-filtered DataFrame and forces `test_size=0`
so the pipeline does not carve out its own internal validation split —
the held-out fold itself plays that role.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from .evaluation_pipeline import (
    add_tolerance_columns,
    apply_model,
    compute_flow_metrics,
    compute_tolerance_counts,
)
from .training_pipeline import run_training
from .types import ModelTypeConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _single_combo_config(training_config: dict[str, Any]) -> dict[str, Any]:
    """Collapse a saved training_config into a single-combo grid config.

    The original ``training_config.json`` stores the *resolved* hyper-parameters
    for one specific model (one learning_rate, one activation, ...). We re-feed
    them into ``run_training`` as 1-element grid axes so exactly one model is
    trained per fold — same architecture, same regularisation, same loss.
    """
    cfg: dict[str, Any] = {
        # Architecture / regularisation
        "input_cols": list(training_config.get("input_cols", [])),
        "output_cols": list(training_config.get("output_cols", [])),
        "on_off_norm": list(training_config.get("on_off_norm", [])),
        "activations": [training_config.get("activation", "elu")],
        "learning_rates": [float(training_config.get("learning_rate", 0.01))],
        "min_nb_epochs_list": [int(training_config.get("start_from_epoch", 100))],
        "max_epochs": int(training_config.get("epochs_requested", 500)),
        "losses": [training_config.get("loss", "mse")],
        "dropouts": [float(training_config.get("dropout", 0.05))],
        "neurons_factors_list": [list(training_config.get("neurons_factors", [1.0, 1.0]))],
        "use_batch_norm": bool(training_config.get("use_batch_norm", False)),
        "batch_sizes": [int(training_config.get("batch_size", 256))],
        # Disable feature-subset grid: we re-train ONE specific architecture.
        "feature_subset_grid": False,
        "mandatory_input_cols": list(training_config.get("input_cols", [])),
        "min_input_count": len(training_config.get("input_cols", [])),
        # Force NO internal validation split — the held-out fold plays
        # that role. The EarlyStopping callback inside the pipeline falls
        # back to monitoring train loss when test_size == 0.
        "test_size": 0.0,
        "analysis_scope": "all",
        # Seed + weighting are inherited so each fold is reproducible relative
        # to itself (offset by run_idx like the main pipeline does internally).
        "seed": int(training_config.get("seed", 1750)),
        "use_flag_comptage_weighting": bool(
            training_config.get("use_flag_comptage_weighting", False)
        ),
        "flag_comptage_col": training_config.get("flag_comptage_col", "flag_comptage"),
        "flag_priority_weight": float(training_config.get("flag_priority_weight", 4.0)),
        # Year mapping must be replayed identically.
        "year_column_name": training_config.get("year_column_name", "") or "",
        "year_value_mapping": dict(training_config.get("year_value_mapping") or {}),
        # Safety cap (mirrors run_training's default).
        "_max_grid_combinations": 4,
    }
    return cfg


def _fold_metrics(
    artifact: Any,
    val_df: pd.DataFrame,
    type_config: ModelTypeConfig,
    config: dict[str, Any],
) -> dict[str, float]:
    """Compute (tol_in_pct, p80, r2) on the held-out fold."""
    results = apply_model(val_df, artifact, type_config, config=config)
    results = add_tolerance_columns(results, type_config)

    # Restrict the metric scope to permanent/tournant sensors when the
    # column is available — same convention as run_evaluation(stats_scope="flag1").
    # flag_comptage == 1 = capteurs Siredo de reference (stations permanentes /
    # tournantes a comptage continu fiable) : ce sont les seuls points pour
    # lesquels une "verite terrain" mesuree existe, donc les seuls sur lesquels
    # tol_in_pct / p80 / r2 ont un sens metier. Les autres points (estimes /
    # interpoles) sont exclus du scoring de validation croisee pour ne pas
    # diluer la variance par-fold avec des cibles non observees. Repli sur
    # l'ensemble des lignes si le sous-ensemble flag==1 est vide.
    if "flag_comptage" in results.columns:
        stats_df = results[results["flag_comptage"] == 1].copy()
        if stats_df.empty:
            stats_df = results.copy()
    else:
        stats_df = results.copy()

    flow_metrics = compute_flow_metrics(stats_df, type_config)
    tol = compute_tolerance_counts(stats_df)

    # tol_in_pct: percentage of held-out rows whose Tolerance_IN_OUT == 1.
    tol_total = float(tol.get("tol_total") or 0)
    tol_in_pct = (
        100.0 * float(tol.get("tol_in") or 0) / tol_total if tol_total > 0 else float("nan")
    )

    # R² on the predicted flow (TVr / DPL) vs reference flow.
    ref_col = type_config.eval_reference_col
    pred_col = type_config.eval_predicted_col
    sub = stats_df[[ref_col, pred_col]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(sub) >= 2:
        y_true = sub[ref_col].to_numpy(dtype=np.float64)
        y_pred = sub[pred_col].to_numpy(dtype=np.float64)
        ss_res = float(np.sum((y_true - y_pred) ** 2))
        ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    else:
        r2 = float("nan")

    p80 = float(flow_metrics.get("err_rel_p80", float("nan")))

    return {
        "tol_in_pct": float(tol_in_pct),
        "p80": float(p80),
        "r2": float(r2),
        "n_val_samples": int(len(stats_df)),
    }


def _summary(values: list[float]) -> dict[str, float]:
    """Return mean / std over fold values (NaN-safe)."""
    arr = np.array(
        [v for v in values if v is not None and not np.isnan(v)],
        dtype=np.float64,
    )
    if arr.size == 0:
        return {"mean": float("nan"), "std": float("nan")}
    return {
        "mean": float(np.mean(arr)),
        # ddof=1 — sample std (k=5 folds is small, prefer unbiased estimator).
        "std": float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def kfold_train_eval(
    df: pd.DataFrame,
    training_config: dict[str, Any],
    type_config: ModelTypeConfig,
    *,
    k: int = 5,
    shuffle_seed: int = 1750,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Run k-fold cross-validation on a trained-model configuration.

    Parameters
    ----------
    df : full DataFrame containing both inputs and target (the same one used
        for the original training).
    training_config : the model's persisted ``training_config.json`` content.
    type_config : TV_CONFIG or PL_CONFIG.
    k : number of folds (must be in [2, 10]; caller validates).
    shuffle_seed : KFold random_state.
    cancel_event : optional ``threading.Event`` — checked between folds.
        When set, the loop aborts and returns whatever folds were finished.

    Returns
    -------
    Dict with keys:
        - "k": int
        - "folds": list of per-fold metric dicts
        - "summary": dict of {metric: {mean, std}}
        - "cancelled": bool

    Raises
    ------
    ValueError if the dataframe is too small (< 2*k usable rows) or the
        training config is missing required keys.
    """
    if df is None or df.empty:
        raise ValueError("DataFrame d'entrainement vide.")
    if not training_config:
        raise ValueError("training_config absent ou vide.")

    if k < 2 or k > 10:
        raise ValueError(f"k doit etre dans [2, 10] (recu={k}).")

    # Prepare a single-combo config from the original training_config.
    base_cfg = _single_combo_config(training_config)

    # ────────────────────────────────────────────────────────────────────
    # KFold over the dataframe's row positions. StratifiedKFold would
    # require a categorical column; the spec says "StratifiedKFold-style
    # if a stratification column is set, else KFold" — we keep KFold for
    # the default path since no stratification column is currently exposed
    # by the API surface.
    # ────────────────────────────────────────────────────────────────────
    n = len(df)
    if n < 2 * k:
        raise ValueError(f"Pas assez de lignes ({n}) pour {k} folds (minimum {2 * k}).")
    kf = KFold(n_splits=k, shuffle=True, random_state=int(shuffle_seed))

    folds_out: list[dict[str, Any]] = []
    df_idx = df.reset_index(drop=True)
    indices = np.arange(n)

    cancelled = False
    for fold_idx, (train_idx, val_idx) in enumerate(kf.split(indices)):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break

        train_df = df_idx.iloc[train_idx].reset_index(drop=True)
        val_df = df_idx.iloc[val_idx].reset_index(drop=True)

        # Bump the seed offset per fold so each fold initialises its NN
        # differently — otherwise all 5 folds train from the same random
        # weights and the variance estimate would be optimistic.
        fold_cfg = {**base_cfg, "seed": int(base_cfg["seed"]) + fold_idx}

        try:
            results = run_training(
                df=train_df,
                config=fold_cfg,
                type_config=type_config,
                progress_callback=None,
                cancel_event=cancel_event,
            )
        except Exception as exc:  # noqa: BLE001 — fold-level fault is non-fatal
            logger.exception("Fold %d training failed: %s", fold_idx, exc)
            folds_out.append(
                {
                    "fold_idx": fold_idx,
                    "tol_in_pct": float("nan"),
                    "p80": float("nan"),
                    "r2": float("nan"),
                    "n_val_samples": int(len(val_df)),
                    "error": str(exc),
                }
            )
            continue

        if not results:
            folds_out.append(
                {
                    "fold_idx": fold_idx,
                    "tol_in_pct": float("nan"),
                    "p80": float("nan"),
                    "r2": float("nan"),
                    "n_val_samples": int(len(val_df)),
                    "error": "no_artifact",
                }
            )
            continue

        # Single artifact (we collapsed the grid to one combo).
        artifact = next(iter(results.values()))
        try:
            metrics = _fold_metrics(artifact, val_df, type_config, fold_cfg)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Fold %d metrics failed: %s", fold_idx, exc)
            metrics = {
                "tol_in_pct": float("nan"),
                "p80": float("nan"),
                "r2": float("nan"),
                "n_val_samples": int(len(val_df)),
                "error": str(exc),
            }

        folds_out.append({"fold_idx": fold_idx, **metrics})
        logger.info(
            "kfold fold %d/%d done: tol_in_pct=%.2f p80=%.2f r2=%.3f n_val=%d",
            fold_idx + 1,
            k,
            metrics.get("tol_in_pct", float("nan")),
            metrics.get("p80", float("nan")),
            metrics.get("r2", float("nan")),
            metrics.get("n_val_samples", 0),
        )

    summary = {
        "tol_in_pct": _summary([f.get("tol_in_pct", float("nan")) for f in folds_out]),
        "p80": _summary([f.get("p80", float("nan")) for f in folds_out]),
        "r2": _summary([f.get("r2", float("nan")) for f in folds_out]),
    }

    return {
        "k": int(k),
        "folds": folds_out,
        "summary": summary,
        "cancelled": cancelled,
    }
