"""Training router — grid search training, SSE streaming, cancellation."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import get_settings
from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/training", tags=["training"])

SEED = 1750

# ---------------------------------------------------------------------------
# Task registry (in-memory)
# ---------------------------------------------------------------------------

class TrainingTask:
    def __init__(self, task_id: str, session_id: str, config: dict[str, Any]) -> None:
        self.task_id = task_id
        self.session_id = session_id
        self.config = config
        self.status: str = "pending"
        self.progress: list[dict] = []
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self.started_at: float = time.time()
        self._cancel_event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def cancel(self) -> None:
        self._cancel_event.set()


_tasks: dict[str, TrainingTask] = {}
_tasks_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TrainingConfig(BaseModel):
    session_id: str
    output_dir: str | None = None

    # Grid search params (from frontend config-form)
    model_type: str = "TV"
    input_cols: list[str] = [
        "TMJAFCDTV", "TMJAFCDPL",
        "car_average_distance_km", "car_average_speed_kmh",
        "truck_min_average_distance_km", "truck_average_speed_kmh",
    ]
    output_cols: list[str] = ["TxPenTVRef"]
    on_off_norm: list[bool] = []
    activations: list[str] = ["elu"]
    learning_rates: list[float] = [0.01]
    losses: list[str] = ["mse"]
    min_nb_epochs_list: list[int] = [500, 1000]
    max_epochs: int = 2050
    test_size: float = 0.0
    neurons_factors_list: list[list[float]] = [[1.0, 1.0]]
    use_batch_norm: bool = False
    dropouts: list[float] = [0.05]
    batch_sizes: list[int] = [256]
    seed: int = SEED

    # Optional
    mandatory_input_cols: list[str] = []
    min_input_count: int = 0
    feature_subset_grid: bool = False
    use_flag_comptage_weighting: bool = False
    flag_priority_weight: float = 4.0

    class Config:
        extra = "allow"


class TrainingStartResponse(BaseModel):
    task_id: str
    session_id: str
    status: str
    total_combinations: int
    output_dir: str | None = None


class TrainingStatusResponse(BaseModel):
    task_id: str
    status: str
    progress_pct: float
    current_epoch: int
    total_epochs: int
    current_model: int
    total_models: int
    current_model_name: str
    loss: float | None = None
    val_loss: float | None = None
    best_val_loss: float | None = None
    error: str | None = None


class TrainingCancelResponse(BaseModel):
    task_id: str
    status: str


# ---------------------------------------------------------------------------
# Column name translation
# ---------------------------------------------------------------------------

_COL_RENAMES = {
    "TMJATV": "TMJAFCDTV",
    "TMJAPL": "TMJAFCDPL",
    "TxPen": "TxPenTVRef",
    "TxPenPL": "TxPenPLRef",
}


# ---------------------------------------------------------------------------
# Grid search: generate all combinations
# ---------------------------------------------------------------------------

def _feature_mask_name(feature_cols: list[str], all_input_cols: list[str]) -> str:
    """Compact bitmask identifier, e.g. ``fmask_111010``.

    Exact replica of ``feature_mask_name()`` from ``xScripts/CreateMDL_TV.py``.
    """
    feature_set = set(feature_cols)
    bits = "".join("1" if c in feature_set else "0" for c in all_input_cols)
    return f"fmask_{bits}"


def _build_feature_sets(
    all_input_cols: list[str],
    mandatory_cols: list[str],
    min_input_count: int,
    enable_feature_subset_grid: bool,
) -> list[list[str]]:
    """Generate all valid feature subsets.

    Exact replica of ``build_feature_sets()`` from ``xScripts/CreateMDL_TV.py``.
    """
    mandatory_cols = [c for c in mandatory_cols if c]
    missing_mandatory = [c for c in mandatory_cols if c not in all_input_cols]
    if missing_mandatory:
        raise ValueError(
            f"Mandatory columns are not part of input-cols: {missing_mandatory}"
        )

    if min_input_count < len(mandatory_cols):
        raise ValueError(
            f"min-input-count={min_input_count} cannot be less than "
            f"number of mandatory columns={len(mandatory_cols)}"
        )

    if not enable_feature_subset_grid:
        return [all_input_cols.copy()]

    optional_cols = [c for c in all_input_cols if c not in mandatory_cols]
    min_optional = max(0, min_input_count - len(mandatory_cols))

    feature_sets: list[list[str]] = []
    for k in range(min_optional, len(optional_cols) + 1):
        for subset in itertools.combinations(optional_cols, k):
            chosen = set(mandatory_cols).union(subset)
            ordered = [c for c in all_input_cols if c in chosen]
            feature_sets.append(ordered)

    if not feature_sets:
        raise ValueError("No valid feature-set generated with current constraints.")
    return feature_sets


def _build_combinations(cfg: dict) -> list[dict]:
    """Build all hyperparameter combinations for grid search.

    When ``feature_subset_grid`` is enabled, generates feature subsets from
    mandatory/optional columns (exactly like ``xScripts/CreateMDL_TV.py``),
    then takes the cartesian product with the 7 other hyper-parameter axes.
    Each combination carries its own ``feature_cols`` and ``feature_mask``.
    """
    all_input_cols: list[str] = cfg.get("input_cols", [
        "TMJAFCDTV", "TMJAFCDPL",
        "car_average_distance_km", "car_average_speed_kmh",
        "truck_min_average_distance_km", "truck_average_speed_kmh",
    ])
    mandatory_input_cols: list[str] = cfg.get("mandatory_input_cols", [])
    min_input_count: int = int(cfg.get("min_input_count", 0))
    feature_subset_grid: bool = bool(cfg.get("feature_subset_grid", False))

    feature_sets = _build_feature_sets(
        all_input_cols=all_input_cols,
        mandatory_cols=mandatory_input_cols,
        min_input_count=min_input_count,
        enable_feature_subset_grid=feature_subset_grid,
    )

    combos: list[dict] = []
    for feature_cols in feature_sets:
        fmask = _feature_mask_name(feature_cols, all_input_cols)
        for activation in cfg.get("activations", ["elu"]):
            for lr in cfg.get("learning_rates", [0.01]):
                for min_ep in cfg.get("min_nb_epochs_list", [500]):
                    for loss_fn in cfg.get("losses", ["mse"]):
                        for dropout in cfg.get("dropouts", [0.05]):
                            for nf in cfg.get("neurons_factors_list", [[1.0, 1.0]]):
                                for bs in cfg.get("batch_sizes", [256]):
                                    nf_label = "x".join(str(f) for f in nf)
                                    run_name = (
                                        f"{activation}_lr{lr}_ep{min_ep}_{loss_fn}"
                                        f"_drp{dropout}_nf{nf_label}"
                                        f"_bs{bs}_{fmask}"
                                    )
                                    combos.append({
                                        "run_name": run_name,
                                        "feature_cols": feature_cols,
                                        "feature_mask": fmask,
                                        "activation": activation,
                                        "learning_rate": lr,
                                        "min_nb_epochs": min_ep,
                                        "loss": loss_fn,
                                        "dropout": dropout,
                                        "neurons_factors": nf,
                                        "batch_size": bs,
                                    })
    return combos


# ---------------------------------------------------------------------------
# Background training worker
# ---------------------------------------------------------------------------

def _normalize(
    x: np.ndarray,
    on_off_mask: np.ndarray,
    mu: np.ndarray | None = None,
    sigma: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Z-score normalisation — exact replica of ``normalize()`` in CreateMDL_TV.py."""
    if mu is None or sigma is None:
        mu = np.mean(x[:, on_off_mask], axis=0)
        sigma = np.std(x[:, on_off_mask], axis=0)
    sigma = np.where(sigma == 0, 1.0, sigma)

    x_norm = np.zeros_like(x, dtype=float)
    x_norm[:, on_off_mask] = (x[:, on_off_mask] - mu) / sigma
    x_norm[:, ~on_off_mask] = x[:, ~on_off_mask]
    return x_norm, mu, sigma


def _training_worker(task: TrainingTask) -> None:
    """Runs grid search training in a separate thread.

    Feature subsets are grouped so that the (expensive) normalisation
    statistics ``mu_x / sigma_x`` are computed only once per feature set,
    exactly like the outer loop in ``CreateMDL_TV.run_training()``.
    """
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
    os.environ.setdefault("TF_XLA_FLAGS", "--tf_xla_enable_xla_devices=false")

    try:
        import tensorflow as tf
        from tensorflow.keras.models import Sequential
        from tensorflow.keras.layers import Dense, Dropout, BatchNormalization
        from tensorflow.keras.optimizers import Adam
        from tensorflow.keras.losses import MeanSquaredError, Huber, MeanAbsoluteError

        # These settings can only be applied before TF initializes. On the
        # second training run (or any run after model_builder.py imported TF)
        # they raise "cannot be modified after initialization" — ignore it.
        for _setter, _label in (
            (lambda: tf.config.threading.set_intra_op_parallelism_threads(4), "intra_op_threads"),
            (lambda: tf.config.threading.set_inter_op_parallelism_threads(2), "inter_op_threads"),
            (lambda: tf.config.optimizer.set_jit(False), "jit_disable"),
        ):
            try:
                _setter()
            except RuntimeError as exc:
                logger.debug("TF setter %s skipped (already initialised): %s", _label, exc)

        task.status = "running"
        cfg = task.config

        # -- Get learning DataFrame -------------------------------------------
        session = session_manager.get_session(task.session_id)
        if session is None:
            raise RuntimeError("Session expiree.")
        learning_df: pd.DataFrame | None = session.data.get("learning_df")
        if learning_df is None:
            raise RuntimeError("Pas de DataFrame d'apprentissage dans la session.")

        df = learning_df.copy()
        for old_name, new_name in _COL_RENAMES.items():
            if old_name in df.columns and new_name not in df.columns:
                df[new_name] = df[old_name]

        all_input_cols: list[str] = cfg["input_cols"]
        output_col: str = (
            cfg.get("output_cols", ["TxPenTVRef"])[0]
            if isinstance(cfg.get("output_cols"), list)
            else cfg.get("output_col", "TxPenTVRef")
        )

        # Check all candidate columns exist
        missing = [c for c in all_input_cols + [output_col] if c not in df.columns]
        if missing:
            raise RuntimeError(f"Colonnes manquantes dans le DF: {missing}")

        # Drop rows with NaN in ANY candidate column (union of all feature sets)
        sub = df[all_input_cols + [output_col]].dropna()
        if len(sub) < 5:
            raise RuntimeError(f"Trop peu de lignes valides ({len(sub)}).")

        seed = cfg.get("seed", SEED)
        from ..services.ml.seeding import seed_everything
        seed_everything(seed)

        # ON_OFF_NORM mask — mapped per column name so subsets can derive theirs
        on_off_norm_list = cfg.get("on_off_norm", [True] * len(all_input_cols))
        if len(on_off_norm_list) != len(all_input_cols):
            on_off_norm_list = [True] * len(all_input_cols)
        col_to_mask: dict[str, bool] = {
            c: bool(v) for c, v in zip(all_input_cols, on_off_norm_list)
        }

        # Full y (output) array — shared across all feature sets
        y_full = sub[output_col].values.astype(np.float64).reshape(-1, 1)
        y_on_off = np.ones(y_full.shape[1], dtype=bool)

        # Train/valid split on *indices* (shared across feature sets)
        test_size = cfg.get("test_size", 0.0)
        indices = np.arange(len(sub))
        if test_size > 0:
            from sklearn.model_selection import train_test_split as _tts
            idx_train, idx_valid = _tts(indices, test_size=test_size, random_state=seed)
        else:
            idx_train = indices
            idx_valid = None

        y_train = y_full[idx_train]
        y_valid = y_full[idx_valid] if idx_valid is not None else None

        # Normalise y (once — independent of feature set)
        y_train_norm, mu_y, sigma_y = _normalize(y_train, y_on_off)
        y_valid_norm = None
        if y_valid is not None:
            y_valid_norm, _, _ = _normalize(y_valid, y_on_off, mu_y, sigma_y)
        y_all_norm, _, _ = _normalize(y_full, y_on_off, mu_y, sigma_y)

        # Generate all combinations (now includes feature_cols & feature_mask)
        combos = _build_combinations(cfg)
        total_models = len(combos)
        max_epochs = cfg.get("max_epochs", 2050)
        use_batch_norm = cfg.get("use_batch_norm", False)
        output_dir = cfg.get("output_dir")

        # Skip already-trained models
        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            pending_combos = [
                c for c in combos
                if not (out_path / c["run_name"] / "NNweights.weights.h5").exists()
                and not (out_path / c["run_name"] / "NNweights.h5").exists()
            ]
        else:
            pending_combos = combos

        total_pending = len(pending_combos)

        logger.info(
            "Training worker started: task=%s | input_cols=%s | output_dir=%s | "
            "max_epochs=%s | total_combinations=%d | pending=%d | "
            "feature_subset_grid=%s | mandatory_input_cols=%s | min_input_count=%s",
            task.task_id,
            cfg.get("input_cols"),
            cfg.get("output_dir"),
            cfg.get("max_epochs"),
            total_models,
            total_pending,
            cfg.get("feature_subset_grid"),
            cfg.get("mandatory_input_cols"),
            cfg.get("min_input_count"),
        )

        if output_dir:
            logger.info("Output directory created/verified: %s", out_path.resolve())
        else:
            logger.warning("No output_dir specified — models will NOT be saved to disk!")

        task.progress.append({
            "type": "info",
            "message": (
                f"Demarrage du grid search : {total_pending} combinaisons "
                f"({total_models - total_pending} deja entraines, ignores)"
            ),
            "total_models": total_pending,
        })

        if total_pending == 0:
            task.result = {
                "total_models": 0,
                "skipped": total_models,
                "best_model": "",
                "best_val_loss": None,
                "output_dir": output_dir,
                "results": [],
            }
            task.status = "completed"
            return

        # -- Group pending combos by feature_mask for normalisation reuse ------
        from collections import OrderedDict

        groups: OrderedDict[str, list[dict]] = OrderedDict()
        for combo in pending_combos:
            fmask = combo["feature_mask"]
            groups.setdefault(fmask, []).append(combo)

        best_global_val_loss = float("inf")
        best_model_name = ""
        results_list: list[dict] = []
        model_counter = 0

        for fmask_idx, (fmask, group_combos) in enumerate(groups.items()):
            # Clear TF session between feature set groups to prevent memory bloat
            if fmask_idx > 0:
                try:
                    tf.keras.backend.clear_session()
                except Exception as exc:
                    logger.warning("clear_session between groups failed: %s", exc, exc_info=True)
            if task.cancelled:
                task.status = "cancelled"
                return

            # -- Per-feature-set normalisation (computed once per group) --------
            feature_cols = group_combos[0]["feature_cols"]
            on_off_subset = np.array(
                [col_to_mask[c] for c in feature_cols], dtype=bool
            )

            x_subset = sub[feature_cols].values.astype(np.float64)
            x_tr = x_subset[idx_train]
            x_va = x_subset[idx_valid] if idx_valid is not None else None

            x_train_norm, mu_x, sigma_x = _normalize(x_tr, on_off_subset)
            x_valid_norm = None
            if x_va is not None:
                x_valid_norm, _, _ = _normalize(x_va, on_off_subset, mu_x, sigma_x)
            x_all_norm, _, _ = _normalize(x_subset, on_off_subset, mu_x, sigma_x)

            # Use validation set for eval; fall back to all data if no split
            if x_valid_norm is not None and y_valid_norm is not None:
                X_eval, y_eval = x_valid_norm, y_valid_norm
            else:
                X_eval, y_eval = x_all_norm, y_all_norm

            # Only use validation_data if we have a real split (like original Streamlit)
            # When test_size == 0, do NOT pass validation_data — avoids doubling compute per epoch
            X_val_fit = x_valid_norm  # None if no split
            y_val_fit = y_valid_norm  # None if no split
            has_validation = X_val_fit is not None and y_val_fit is not None

            input_dim = len(feature_cols)

            for combo in group_combos:
                if task.cancelled:
                    task.status = "cancelled"
                    return

                run_name = combo["run_name"]
                model_counter += 1

                task.progress.append({
                    "type": "model_start",
                    "model_index": model_counter - 1,
                    "total_models": total_pending,
                    "model_name": run_name,
                })

                # Build model — architecture mirrors build_model() in CreateMDL_TV.py
                nf = combo["neurons_factors"]
                activation = combo["activation"]
                dropout = combo["dropout"]
                initializer = "lecun_normal" if activation == "selu" else "he_normal"

                layers_list = []
                for i, factor in enumerate(nf):
                    n_units = max(2, int(round(input_dim * factor)))
                    if i == 0:
                        layers_list.append(Dropout(dropout, input_shape=(input_dim,)))
                    else:
                        layers_list.append(Dropout(dropout))
                    if use_batch_norm:
                        layers_list.append(BatchNormalization())
                    layers_list.append(
                        Dense(n_units, activation=activation, kernel_initializer=initializer)
                    )
                layers_list.append(Dense(1, activation="linear"))
                model = Sequential(layers_list)

                # Loss
                loss_name = combo["loss"]
                if loss_name == "huber":
                    loss_fn = Huber(delta=1.0, name="huber")
                elif loss_name == "mae":
                    loss_fn = MeanAbsoluteError(name="mae_loss")
                else:
                    loss_fn = MeanSquaredError(name="mse")

                model.compile(
                    optimizer=Adam(learning_rate=combo["learning_rate"]),
                    loss=loss_fn,
                    metrics=["mae"],
                )

                # Callbacks
                min_ep = combo["min_nb_epochs"]
                patience = max(30, max_epochs // 10)

                # Capture loop vars for the callback closure
                _model_counter = model_counter
                _run_name = run_name

                class GridProgressCallback(tf.keras.callbacks.Callback):
                    def on_epoch_end(cb_self, epoch, logs=None):
                        if task.cancelled:
                            cb_self.model.stop_training = True
                            return
                        logs = logs or {}
                        task.progress.append({
                            "type": "epoch",
                            "model_index": _model_counter - 1,
                            "total_models": total_pending,
                            "model_name": _run_name,
                            "epoch": epoch + 1,
                            "total_epochs": max_epochs,
                            "loss": float(logs.get("loss", 0)),
                            "val_loss": float(logs.get("val_loss", logs.get("loss", 0))),
                            "elapsed": time.time() - task.started_at,
                        })

                # Monitor val_loss if we have validation, otherwise monitor loss
                monitor_metric = "val_loss" if has_validation else "loss"
                callbacks_list = [
                    tf.keras.callbacks.EarlyStopping(
                        monitor=monitor_metric,
                        patience=patience,
                        restore_best_weights=True,
                        start_from_epoch=min_ep,
                    ),
                    GridProgressCallback(),
                ]

                # Train — only pass validation_data if we have a real split
                fit_kwargs: dict = {
                    "x": x_train_norm,
                    "y": y_train_norm,
                    "epochs": max_epochs,
                    "batch_size": min(combo["batch_size"], len(x_train_norm)),
                    "verbose": 0,
                    "callbacks": callbacks_list,
                }
                if has_validation:
                    fit_kwargs["validation_data"] = (X_val_fit, y_val_fit)
                history = model.fit(**fit_kwargs)

                if task.cancelled:
                    task.status = "cancelled"
                    return

                # Evaluate
                val_loss = float(model.evaluate(X_eval, y_eval, verbose=0)[0])
                epochs_trained = len(history.history.get("loss", []))

                if val_loss < best_global_val_loss:
                    best_global_val_loss = val_loss
                    best_model_name = run_name

                results_list.append({
                    "run_name": run_name,
                    "val_loss": val_loss,
                    "epochs_trained": epochs_trained,
                    **combo,
                })

                task.progress.append({
                    "type": "model_end",
                    "model_index": model_counter - 1,
                    "model_name": run_name,
                    "val_loss": val_loss,
                    "epochs_trained": epochs_trained,
                    "best_val_loss": best_global_val_loss,
                    "best_model_name": best_model_name,
                })

                # Save model to output_dir
                if output_dir:
                    model_dir = Path(output_dir) / run_name
                    model_dir.mkdir(parents=True, exist_ok=True)

                    (model_dir / "NNarchitecture.json").write_text(
                        model.to_json(), encoding="utf-8"
                    )
                    model.save_weights(str(model_dir / "NNweights.weights.h5"))

                    # Normalisation coefficients — per feature set
                    norm_json = json.dumps({
                        "muX": [mu_x.tolist()],
                        "SX": [sigma_x.tolist()],
                        "muY": [mu_y.tolist()],
                        "SY": [sigma_y.tolist()],
                    }, indent=2)
                    (model_dir / "NNnormCoefficients.json").write_text(
                        norm_json, encoding="utf-8"
                    )

                    train_cfg = json.dumps({
                        "run_name": run_name,
                        "input_cols": feature_cols,
                        "output_col": output_col,
                        "feature_mask": fmask,
                        "epochs_requested": max_epochs,
                        "epochs_trained": epochs_trained,
                        "batch_size": int(min(combo["batch_size"], len(x_train_norm))),
                        "test_size": test_size,
                        "learning_rate": combo["learning_rate"],
                        "activation": combo["activation"],
                        "dropout": combo["dropout"],
                        "loss": combo["loss"],
                        "neurons_factors": combo["neurons_factors"],
                        "use_batch_norm": use_batch_norm,
                        "start_from_epoch": min_ep,
                        "patience": patience,
                        "seed": seed,
                        "train_rows": int(len(x_train_norm)),
                        "val_rows": int(len(X_val_fit)) if X_val_fit is not None else 0,
                    }, indent=2)
                    (model_dir / "training_config.json").write_text(
                        train_cfg, encoding="utf-8"
                    )

                    metrics_json = json.dumps({
                        "val_loss": val_loss,
                        "epochs_trained": epochs_trained,
                    }, indent=2)
                    (model_dir / "training_metrics.json").write_text(
                        metrics_json, encoding="utf-8"
                    )

                    logger.info(
                        "Model %d/%d saved: %s (NNarchitecture.json, NNweights.weights.h5, "
                        "NNnormCoefficients.json, training_config.json, training_metrics.json)",
                        model_counter, total_pending, model_dir,
                    )
                else:
                    logger.warning(
                        "Model %d/%d NOT saved (no output_dir): %s",
                        model_counter, total_pending, run_name,
                    )

                logger.info(
                    "Model %d/%d done: %s val_loss=%.6f epochs=%d",
                    model_counter, total_pending, run_name, val_loss, epochs_trained,
                )

        # Done
        task.result = {
            "total_models": total_pending,
            "skipped": total_models - total_pending,
            "best_model": best_model_name,
            "best_val_loss": best_global_val_loss,
            "output_dir": output_dir,
            "results": results_list,
        }
        task.status = "completed"
        logger.info(
            "Grid search completed: %d models trained (%d skipped), best=%s (%.6f)",
            total_pending, total_models - total_pending,
            best_model_name, best_global_val_loss,
        )

    except Exception as exc:
        task.status = "failed"
        task.error = str(exc)
        logger.exception("Training failed: task=%s", task.task_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/start", response_model=TrainingStartResponse)
async def start_training(body: TrainingConfig) -> TrainingStartResponse:
    session = session_manager.get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")
    if session.data.get("learning_df") is None:
        raise HTTPException(
            status_code=400,
            detail="Pas de DataFrame d'apprentissage dans cette session. "
                   "Retournez a l'etape Donnees, importez un fichier et validez le mapping. "
                   "Si le backend a ete redémarre, les sessions en memoire sont perdues.",
        )

    # SaaS deployment: API runs in the cloud and cannot write to the user's
    # local disk. Keep the user-supplied value only as a display label; always
    # resolve the actual write path to the server-side workspace so models
    # persist on the backend and can be downloaded via /api/export/models-all.
    config_dict = body.model_dump()
    settings = get_settings()
    user_label = config_dict.get("output_dir") or ""
    server_output = str(Path(settings.WORKSPACE_ROOT) / body.session_id / "models")
    config_dict["output_dir"] = server_output
    config_dict["output_label"] = user_label
    logger.info(
        "Training output — user label=%r, server path=%s",
        user_label, server_output,
    )

    # Store in session via the manager (session.data is a read proxy with the
    # Redis backend — direct assignment only updates the local cache, not Redis)
    session_manager.store_data(body.session_id, "output_dir", server_output)
    session_manager.store_data(body.session_id, "output_label", user_label)

    combos = _build_combinations(config_dict)
    total = len(combos)
    if total > settings.MAX_GRID_COMBINATIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Grid search demanderait {total} combinaisons, "
                f"limite serveur MAX_GRID_COMBINATIONS={settings.MAX_GRID_COMBINATIONS}. "
                "Reduisez les axes (activations, learning_rates, neurons_factors_list, batch_sizes, ...) "
                "ou desactivez feature_subset_grid."
            ),
        )

    task_id = uuid.uuid4().hex[:12]
    task = TrainingTask(
        task_id=task_id,
        session_id=body.session_id,
        config=config_dict,
    )

    with _tasks_lock:
        _tasks[task_id] = task

    thread = threading.Thread(target=_training_worker, args=(task,), daemon=True)
    thread.start()

    logger.info(
        "Grid search started: task=%s session=%s combos=%d output_dir=%s max_epochs=%d",
        task_id, body.session_id, total, config_dict.get("output_dir"), body.max_epochs,
    )

    return TrainingStartResponse(
        task_id=task_id,
        session_id=body.session_id,
        status="pending",
        total_combinations=total,
        output_dir=config_dict.get("output_dir"),
    )


@router.get("/stream/{task_id}")
async def stream_training(task_id: str) -> StreamingResponse:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trouvee.")

    async def event_generator():
        last_idx = 0
        while True:
            current_progress = task.progress[last_idx:]
            for entry in current_progress:
                yield f"data: {json.dumps(entry)}\n\n"
                last_idx += 1

            if task.status in ("completed", "failed", "cancelled"):
                final = {
                    "type": "complete",
                    "status": task.status,
                    "result": task.result,
                    "error": task.error,
                }
                yield f"data: {json.dumps(final)}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/status/{task_id}", response_model=TrainingStatusResponse)
async def training_status(task_id: str) -> TrainingStatusResponse:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trouvee.")

    # Find latest epoch entry
    last_epoch = {}
    last_model_end = {}
    current_model = 0
    total_models = 1
    model_name = ""

    for entry in reversed(task.progress):
        if entry.get("type") == "epoch" and not last_epoch:
            last_epoch = entry
        if entry.get("type") == "model_end" and not last_model_end:
            last_model_end = entry
        if entry.get("type") in ("model_start", "epoch") and not model_name:
            current_model = entry.get("model_index", 0)
            total_models = entry.get("total_models", 1)
            model_name = entry.get("model_name", "")
        # Also pick up total_models from the initial info entry
        if entry.get("type") == "info" and total_models <= 1 and "total_models" in entry:
            total_models = entry["total_models"]
        if last_epoch and last_model_end and model_name:
            break

    return TrainingStatusResponse(
        task_id=task_id,
        status=task.status,
        progress_pct=round(
            ((current_model + (last_epoch.get("epoch", 0) / max(last_epoch.get("total_epochs", 1), 1)))
             / max(total_models, 1)) * 100, 1
        ),
        current_epoch=last_epoch.get("epoch", 0),
        total_epochs=last_epoch.get("total_epochs", 0),
        current_model=current_model,
        total_models=total_models,
        current_model_name=model_name,
        loss=last_epoch.get("loss"),
        val_loss=last_epoch.get("val_loss"),
        best_val_loss=last_model_end.get("best_val_loss"),
        error=task.error,
    )


@router.post("/cancel/{task_id}", response_model=TrainingCancelResponse)
async def cancel_training(task_id: str) -> TrainingCancelResponse:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trouvee.")
    task.cancel()
    return TrainingCancelResponse(task_id=task_id, status="cancelling")
