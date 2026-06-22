"""Unified training pipeline for TV and PL models.

Runs the full grid search loop entirely in memory and returns a dict
of trained model artifacts (weights, norm coefficients, config, metrics).
No disk I/O is performed.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime
from pathlib import Path
import threading  # noqa: F401 -- used in type hint string
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ...training_guard import TrainingDeadline

_logger = logging.getLogger(__name__)

# GPU disabled before any TF import
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow import keras

from . import losses as _losses  # noqa: F401 — registers custom loss aliases on import
from .data_prep import prepare_training_data, split_train_valid
from .grid_search import (
    GridCombination,
    build_feature_sets,
    feature_mask_name,
    generate_all_combinations,
)
from .model_builder import build_model
from .normalize import normalize
from .progress import ProgressPayload, TrainingProgressCallback
from .seeding import seed_everything
from .types import ModelTypeConfig

SEED = 1750


# ---------------------------------------------------------------------------
# In-memory model artifact
# ---------------------------------------------------------------------------

class TrainedModelArtifact:
    """Container for a single trained model kept in memory."""

    __slots__ = (
        "run_name",
        "model",
        "mu_x", "sigma_x",
        "mu_y", "sigma_y",
        "input_cols", "output_cols",
        "on_off_norm_subset",
        "training_config",
        "training_metrics",
        "history",
    )

    def __init__(self, **kwargs: Any):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# P4.5 — Hard example mining callback
# ---------------------------------------------------------------------------

class HardExampleMiningCallback(keras.callbacks.Callback):
    """Boost sample_weight on hard training examples mid-training.

    After ``start_epoch`` (default 30), every ``period`` epochs (default 10)
    the callback re-predicts on the (normalized) train set, denormalizes
    predictions back to TxPen-space, and multiplies ``sample_weight`` of
    rows where ``|pred - obs| / max(obs, eps) > threshold`` by ``boost_factor``.

    The cumulative boost on any individual sample is capped at ``max_boost``
    so a few persistently-hard rows cannot completely dominate the loss.

    The ``sample_weight`` array must be the same Python object that the
    caller passed into ``model.fit(sample_weight=...)`` — Keras keeps a
    reference to it, so in-place mutation propagates to the training loop.
    """

    def __init__(
        self,
        x_train_norm: np.ndarray,
        y_train_obs: np.ndarray,
        mu_y: np.ndarray,
        sigma_y: np.ndarray,
        sample_weight: np.ndarray,
        *,
        start_epoch: int = 30,
        period: int = 10,
        threshold: float = 0.15,
        boost_factor: float = 1.5,
        max_boost: float = 3.0,
        target_log_transform: bool = False,
    ):
        super().__init__()
        self._x = x_train_norm
        # y_train_obs MUST be in denormalized "TxPen" space — i.e. the raw
        # observed target values (post-expm1 if log-transformed). The
        # threshold compares relative error in that natural unit.
        self._y_obs = y_train_obs.astype(float).reshape(-1)
        self._mu_y = np.asarray(mu_y, dtype=float).reshape(-1)
        self._sigma_y = np.asarray(sigma_y, dtype=float).reshape(-1)
        self._sw = sample_weight  # mutated in place
        self._initial_sw = sample_weight.copy()
        self._start_epoch = int(start_epoch)
        self._period = max(1, int(period))
        self._threshold = float(threshold)
        self._boost_factor = float(boost_factor)
        self._max_boost = float(max_boost)
        self._target_log_transform = bool(target_log_transform)

    def on_epoch_end(self, epoch, logs=None):  # noqa: D401, ARG002
        # epoch is 0-indexed in Keras → trigger when (epoch+1) >= start_epoch
        if (epoch + 1) < self._start_epoch:
            return
        if ((epoch + 1) - self._start_epoch) % self._period != 0:
            return

        try:
            preds_norm = self.model.predict(self._x, verbose=0)
        except Exception as exc:  # noqa: BLE001 — defensive
            _logger.warning("HardExampleMining predict failed: %s", exc)
            return

        # Predictions come out z-scored; denormalize using the saved moments
        # for the FIRST output (TxPen). For multi-output (e.g. quantile head)
        # we only use the median column.
        preds_norm = np.asarray(preds_norm)
        if preds_norm.ndim == 2 and preds_norm.shape[1] >= 1:
            preds_col = preds_norm[:, 0]
        else:
            preds_col = preds_norm.reshape(-1)

        mu0 = float(self._mu_y[0]) if self._mu_y.size > 0 else 0.0
        sg0 = float(self._sigma_y[0]) if self._sigma_y.size > 0 else 1.0
        preds_natural = preds_col * sg0 + mu0
        if self._target_log_transform:
            preds_natural = np.expm1(preds_natural)

        obs = self._y_obs
        denom = np.where(np.abs(obs) > 1e-6, np.abs(obs), 1e-6)
        rel_err = np.abs(preds_natural - obs) / denom
        hard_mask = rel_err > self._threshold

        if not hard_mask.any():
            return

        # Cap cumulative boost: never exceed max_boost * initial weight.
        cap = self._initial_sw * self._max_boost
        new_sw = self._sw.copy()
        new_sw[hard_mask] = np.minimum(
            new_sw[hard_mask] * self._boost_factor,
            cap[hard_mask],
        )
        # In-place write so Keras sees the update (it holds a reference).
        self._sw[:] = new_sw


# ---------------------------------------------------------------------------
# Single model training (in memory)
# ---------------------------------------------------------------------------

def _train_single(
    x_train_norm: np.ndarray,
    y_train_norm: np.ndarray,
    x_valid_norm: np.ndarray | None,
    y_valid_norm: np.ndarray | None,
    x_all_norm: np.ndarray,
    y_all_norm: np.ndarray,
    mu_x: np.ndarray,
    sigma_x: np.ndarray,
    mu_y: np.ndarray,
    sigma_y: np.ndarray,
    combo: GridCombination,
    max_epochs: int,
    analysis_scope: str,
    output_cols: list[str],
    on_off_subset: np.ndarray,
    seed: int,
    train_sample_weight: np.ndarray | None,
    valid_sample_weight: np.ndarray | None,
    use_flag_permanent_weighting: bool,
    flag_permanent_col: str,
    flag_priority_weight: float,
    use_flag_recent_year_weighting: bool,
    recent_year_priority_weight: float,
    use_batch_norm: bool,
    progress_callback: Callable[[ProgressPayload], None] | None,
    total_models: int,
    model_idx: int,
    test_size: float,
    year_column_name: str | None = None,
    year_value_mapping: dict[str, float] | None = None,
    cancel_event: "threading.Event | None" = None,
    deadline: "TrainingDeadline | None" = None,
    reduce_lr_patience: int = 10,
    reduce_lr_factor: float = 0.5,
    reduce_lr_min: float = 1e-5,
    # --- P4.4 / P4.5 / P4.6 ----------------------------------------------
    run_name_override: str | None = None,
    use_hard_example_mining: bool = False,
    use_curriculum: bool = False,
    flow_for_curriculum: np.ndarray | None = None,
    y_train_obs: np.ndarray | None = None,
    target_log_transform: bool = False,
    # --- Phase 5 bug-fix plumbing -----------------------------------------
    # These three were ignored by the previous pipeline: the request body
    # carried them all the way to /api/training but the training pipeline
    # never read them, so they no-op'd silently. Echoed on the artifact so
    # downstream tooling (evaluation, kfold, metrics.json) can replay them.
    use_log_flow_weighting: bool = False,
    log_flow_weighting_col: str = "TMJOBCTV",
    scaler: str = "standard",
    # --- Bug 5 — year embedding plumbing ---------------------------------
    use_year_embedding: bool = False,
    year_embedding_dim: int = 3,
    # --- Bug 7 — feature engineering echo (resolved by run_training) ------
    feature_engineering_echo: dict[str, Any] | None = None,
) -> TrainedModelArtifact:
    """Train one model and return an in-memory artifact."""

    run_name_effective = run_name_override or combo.run_name

    # Bug 5 — derive year-embedding indices from the combo's feature_cols.
    # build_model requires (year_feature_idx, year_n_categories) when
    # year_embedding=True. We only enable it when the model actually
    # consumes `year_mapped` AND a non-empty year_value_mapping was passed.
    _year_emb_active = bool(use_year_embedding) and ("year_mapped" in combo.feature_cols)
    _year_feature_idx = (
        combo.feature_cols.index("year_mapped") if _year_emb_active else None
    )
    # n_categories falls back to 7 (the default in build_model) when the
    # caller didn't pass a mapping — keeps the layer width consistent with
    # the original P2B.7 reference implementation.
    _year_n_cats = (
        len(year_value_mapping) if (year_value_mapping and _year_emb_active) else 7
    )

    model = build_model(
        input_size=x_train_norm.shape[1],
        output_size=y_train_norm.shape[1],
        learning_rate=combo.learning_rate,
        activation=combo.activation,
        dropout=combo.dropout,
        loss=combo.loss,
        neurons_factors=combo.neurons_factors,
        use_batch_norm=use_batch_norm,
        # P3 axes — propagate combo-level architecture choices so the
        # grid actually varies the model (was previously silently
        # ignored, making `optimizer=adamw`, `use_skip_connection`, etc.
        # cosmetic-only on the resulting artifact).
        optimizer=getattr(combo, "optimizer", "adam"),
        weight_decay=float(getattr(combo, "weight_decay", 0.0) or 0.0),
        use_skip_connection=bool(getattr(combo, "use_skip_connection", False)),
        dropout_schedule=getattr(combo, "dropout_schedule", "uniform"),
        clipnorm=getattr(combo, "clipnorm", None),
        norm_layer=getattr(combo, "norm_layer", None),
        use_quantile_head=bool(getattr(combo, "use_quantile_head", False)),
        # Bug 5 — year embedding.
        year_embedding=_year_emb_active,
        year_feature_idx=_year_feature_idx,
        year_n_categories=int(_year_n_cats),
        year_embedding_dim=int(year_embedding_dim),
    )

    # EarlyStopping — patience=30. start_from = combo.min_nb_epochs so we
    # NEVER bail before the user-asked minimum (was previously capped at 20,
    # which made min_nb_epochs cosmetic — the user reported runs configured
    # for "200 epochs" actually stopping at ~40 with degenerate metrics).
    patience = 30
    start_from = max(20, combo.min_nb_epochs)

    # EarlyStopping monitors val_loss when a validation split exists,
    # otherwise falls back to train loss (cannot discriminate overfitting,
    # but avoids a hard callback failure when test_size == 0).
    has_validation = x_valid_norm is not None and y_valid_norm is not None
    early_stop_monitor = "val_loss" if has_validation else "loss"

    # P0.3 — min_delta=1e-4 avoids stopping on noisy oscillations of the
    # small (5%) validation set. Combined with start_from_epoch (= the
    # user-requested minimum) so the model always trains the asked minimum
    # before EarlyStopping can trip.
    early_stop = keras.callbacks.EarlyStopping(
        monitor=early_stop_monitor,
        patience=patience,
        restore_best_weights=True,
        start_from_epoch=start_from,
        min_delta=1e-4,
    )
    # P3.6: patience=10 (was 20) so LR drops earlier when plateau hits — gives
    # the model more time to recover with a smaller LR before EarlyStopping fires.
    reduce_lr = keras.callbacks.ReduceLROnPlateau(
        monitor=early_stop_monitor,
        factor=reduce_lr_factor,
        patience=reduce_lr_patience,
        min_lr=reduce_lr_min,
        verbose=0,
    )

    callbacks_list: list = [early_stop, reduce_lr]
    if cancel_event is not None:
        class _CancelCallback(keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                if cancel_event.is_set():
                    self.model.stop_training = True
        callbacks_list.append(_CancelCallback())
    # A9 (training_guard) — wall-clock deadline. Aborts the run cleanly at
    # MAX_TRAINING_MINUTES so a single grid cannot monopolise the (2-core ARM)
    # API indefinitely. No-op for short/test trainings (default 30-60 min).
    if deadline is not None:
        class _DeadlineCallback(keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                if deadline.should_stop():
                    self.model.stop_training = True
                    _logger.warning(
                        "Training deadline reached (max %d min) — stopping "
                        "run %s at epoch %d.",
                        deadline.max_minutes, run_name_effective, epoch,
                    )
        callbacks_list.append(_DeadlineCallback())
    if progress_callback is not None:
        callbacks_list.append(
            TrainingProgressCallback(
                callback=progress_callback,
                run_name=run_name_effective,
                total_epochs=max_epochs,
                total_models=total_models,
                model_idx=model_idx,
            )
        )

    # P4.5 — Hard example mining: needs a *mutable* sample_weight array so
    # the callback can boost rows mid-training. We ALWAYS materialize the
    # array (defaulting to uniform 1s) when mining is requested.
    effective_train_sw = train_sample_weight
    hem_active = bool(use_hard_example_mining) and y_train_obs is not None
    if hem_active:
        if effective_train_sw is None:
            effective_train_sw = np.ones(len(x_train_norm), dtype=float)
        else:
            # Copy so we don't mutate the caller's array across seeds.
            effective_train_sw = np.asarray(effective_train_sw, dtype=float).copy()
        hem_cb = HardExampleMiningCallback(
            x_train_norm=x_train_norm,
            y_train_obs=np.asarray(y_train_obs).reshape(-1),
            mu_y=mu_y,
            sigma_y=sigma_y,
            sample_weight=effective_train_sw,
            start_epoch=30,
            period=10,
            threshold=0.15,
            boost_factor=1.5,
            max_boost=3.0,
            target_log_transform=bool(target_log_transform),
        )
        callbacks_list.append(hem_cb)

    fit_kwargs: dict[str, Any] = {
        "x": x_train_norm,
        "y": y_train_norm,
        "epochs": max_epochs,
        "batch_size": min(combo.batch_size, len(x_train_norm)),
        "verbose": 0,
        "callbacks": callbacks_list,
    }
    if effective_train_sw is not None:
        fit_kwargs["sample_weight"] = effective_train_sw
    if x_valid_norm is not None and y_valid_norm is not None:
        if valid_sample_weight is not None:
            fit_kwargs["validation_data"] = (
                x_valid_norm, y_valid_norm, valid_sample_weight
            )
        else:
            fit_kwargs["validation_data"] = (x_valid_norm, y_valid_norm)

    # P4.6 — Curriculum learning. We split max_epochs into two phases:
    #   Phase A: ceil(max_epochs * 0.3) epochs on the easiest 50% (lowest
    #            TMJOBCTV) of the training set.
    #   Phase B: remaining epochs on the full training set.
    # `flow_for_curriculum` must be aligned with x_train_norm (same row
    # order). EarlyStopping is shared across both phases (same callback
    # instance), so start_from_epoch counts from phase-A epoch 0 — this is
    # acceptable because phase A is at most 30% of max_epochs, well under
    # the typical start_from of 200+.
    curriculum_active = bool(use_curriculum) and (
        flow_for_curriculum is not None and len(flow_for_curriculum) == len(x_train_norm)
    )
    if bool(use_curriculum) and not curriculum_active:
        _logger.warning(
            "Curriculum learning requested for %s but flow_for_curriculum is "
            "missing or misaligned — disabling curriculum for this combo.",
            run_name_effective,
        )

    if curriculum_active:
        flow = np.asarray(flow_for_curriculum, dtype=float).reshape(-1)
        order = np.argsort(flow, kind="stable")
        half = max(1, len(order) // 2)
        easy_idx = order[:half]

        phase_a_epochs = max(1, math.ceil(max_epochs * 0.3))
        phase_b_epochs = max(0, max_epochs - phase_a_epochs)

        # Phase A — easy subset
        phase_a_kwargs = dict(fit_kwargs)
        phase_a_kwargs["x"] = x_train_norm[easy_idx]
        phase_a_kwargs["y"] = y_train_norm[easy_idx]
        phase_a_kwargs["epochs"] = phase_a_epochs
        phase_a_kwargs["batch_size"] = min(combo.batch_size, len(easy_idx))
        if "sample_weight" in phase_a_kwargs and phase_a_kwargs["sample_weight"] is not None:
            phase_a_kwargs["sample_weight"] = phase_a_kwargs["sample_weight"][easy_idx]

        history_a = model.fit(**phase_a_kwargs)

        if phase_b_epochs > 0 and not (
            cancel_event is not None and cancel_event.is_set()
        ):
            fit_kwargs["epochs"] = phase_b_epochs
            history_b = model.fit(**fit_kwargs)
            # Merge histories so downstream code sees both phases.
            merged: dict[str, list] = {}
            for k in set(history_a.history) | set(history_b.history):
                merged[k] = list(history_a.history.get(k, [])) + list(
                    history_b.history.get(k, [])
                )
            history = type(history_a)()
            history.history = merged
        else:
            history = history_a
    else:
        history = model.fit(**fit_kwargs)

    # Evaluate
    if analysis_scope == "all":
        eval_x, eval_y = x_all_norm, y_all_norm
    else:
        eval_x, eval_y = x_valid_norm, y_valid_norm
        if eval_x is None or eval_y is None:
            eval_x, eval_y = x_all_norm, y_all_norm

    eval_values = model.evaluate(eval_x, eval_y, verbose=0)
    # model.evaluate returns a scalar when metrics=[] (quantile head path) and
    # a list otherwise. Normalise to a list so zip() always succeeds.
    if not isinstance(eval_values, (list, tuple)):
        eval_values = [eval_values]
    metrics = {
        name: float(np.round(value, 6))
        for name, value in zip(model.metrics_names, eval_values)
    }

    config_dict = {
        "run_name": run_name_effective,
        "input_cols": combo.feature_cols,
        "output_cols": output_cols,
        # Stored so evaluation knows which features were z-scored vs left raw.
        # muX/SX only carry as many entries as `sum(on_off_norm)` so this mask
        # is required to reconstruct the full-length mu/sigma at inference.
        "on_off_norm": [bool(v) for v in on_off_subset.tolist()],
        "epochs_requested": max_epochs,
        "epochs_trained": len(history.history.get("loss", [])),
        "batch_size": int(min(combo.batch_size, len(x_train_norm))),
        "test_size": test_size,
        "learning_rate": combo.learning_rate,
        "activation": combo.activation,
        "dropout": combo.dropout,
        "loss": combo.loss,
        "neurons_factors": combo.neurons_factors,
        "use_batch_norm": use_batch_norm,
        # P3 architecture axes — echoed so downstream tooling and metrics.json
        # report which variant was actually trained.
        "optimizer": getattr(combo, "optimizer", "adam"),
        "weight_decay": float(getattr(combo, "weight_decay", 0.0) or 0.0),
        "use_skip_connection": bool(getattr(combo, "use_skip_connection", False)),
        "dropout_schedule": getattr(combo, "dropout_schedule", "uniform"),
        "clipnorm": getattr(combo, "clipnorm", None),
        "norm_layer": getattr(combo, "norm_layer", None),
        # Bug 4 — use_quantile_head must be echoed so downstream code can tell
        # apart a regression artifact (1 output unit) from a quantile head
        # (3 outputs, q=0.2/0.5/0.8). The grid combo already carries the flag.
        "use_quantile_head": bool(getattr(combo, "use_quantile_head", False)),
        "start_from_epoch": start_from,
        "patience": patience,
        "reduce_lr_factor": float(reduce_lr_factor),
        "reduce_lr_patience": int(reduce_lr_patience),
        "reduce_lr_min": float(reduce_lr_min),
        "analysis_scope": analysis_scope,
        "seed": seed,
        "train_rows": int(len(x_train_norm)),
        "valid_rows": int(0 if x_valid_norm is None else len(x_valid_norm)),
        "eval_rows": int(len(eval_x)),
        "use_flag_permanent_weighting": bool(use_flag_permanent_weighting),
        "flag_permanent_col": flag_permanent_col,
        "flag_priority_weight": float(flag_priority_weight),
        "use_flag_recent_year_weighting": bool(use_flag_recent_year_weighting),
        "recent_year_priority_weight": float(recent_year_priority_weight),
        # Legacy aliases kept in the artifact for downstream tooling (eval
        # router, kfold) that still reads the old keys.
        "use_flag_comptage_weighting": bool(use_flag_permanent_weighting),
        "flag_comptage_col": flag_permanent_col,
        # Year-feature config — required at eval time to replay the same
        # encoding when the model uses year_mapped. Without it, eval feeds
        # raw years (2019, 2020) instead of the trained-on small integers
        # → garbage predictions (rmse ~ 1700, R² ~ -2M on Lyon).
        "year_column_name": year_column_name or "",
        "year_value_mapping": year_value_mapping or {},
        # P4.4/4.5/4.6 — echo so the report shows which flags were active.
        "use_hard_example_mining": bool(use_hard_example_mining),
        "hard_example_mining_note": (
            "Train sample_weight is boosted x1.5 (cap x3) every 10 epochs "
            "after epoch 30 on rows where |pred-obs|/obs > 0.15."
            if use_hard_example_mining
            else ""
        ),
        "use_curriculum": bool(curriculum_active),
        "curriculum_phase_a_epochs": (
            int(math.ceil(max_epochs * 0.3)) if curriculum_active else 0
        ),
        # Phase 5 — flags previously dropped on the floor.
        "target_log_transform": bool(target_log_transform),
        "use_log_flow_weighting": bool(use_log_flow_weighting),
        "log_flow_weighting_col": str(log_flow_weighting_col),
        "scaler": str(scaler),
        "use_year_embedding": bool(_year_emb_active),
        "year_feature_idx": (
            int(_year_feature_idx) if _year_feature_idx is not None else None
        ),
        "year_n_categories": int(_year_n_cats),
        "year_embedding_dim": int(year_embedding_dim),
        # P2B feature engineering — echoed so evaluation can replay the
        # derivations on the validation df (Bug 7 fix on the consumer side).
        "feature_engineering": dict(feature_engineering_echo or {}),
    }

    return TrainedModelArtifact(
        run_name=run_name_effective,
        model=model,
        mu_x=mu_x,
        sigma_x=sigma_x,
        mu_y=mu_y,
        sigma_y=sigma_y,
        input_cols=combo.feature_cols,
        output_cols=output_cols,
        on_off_norm_subset=on_off_subset,
        training_config=config_dict,
        training_metrics=metrics,
        history=history.history,
    )


# ---------------------------------------------------------------------------
# Per-artifact TF serialization (must run BEFORE tf.keras.backend.clear_session)
# ---------------------------------------------------------------------------

def _persist_tf_artifact(
    artifact: "TrainedModelArtifact",
    out_root: Path,
    *,
    run_name: str,
) -> Path:
    """Serialize the TF model + weights + architecture to disk for one artifact.

    AUDIT BUG P0-5 — Originally `tf.keras.backend.clear_session()` ran in the
    grid-search loop right after the artifact was stored in ``results``. The
    Python reference to ``artifact.model`` survived, but the underlying TF
    graph was destroyed, so any later ``artifact.model.save("model.keras")``
    in the caller (``training.py:_serialise_artifact_to_disk``) raised — and
    the exception was swallowed by a broad ``except: pass``. Net effect:
    the native ``.keras`` format was silently lost for the whole grid.

    Fix: write every TF-backed file (``model.keras``, ``NNweights.weights.h5``,
    ``NNarchitecture.json``) here, *inside the loop, before* clear_session.
    The caller still writes the pure-JSON metadata (training_config, metrics,
    norm coefficients, meta) — those don't touch the TF graph and are safe
    to defer.

    Returns the directory the artifact was written to. The path is also
    stamped on ``artifact.training_config["_persisted_dir"]`` so the caller
    knows the TF files are already on disk and must skip re-saving them.
    """
    model_dir = out_root / run_name
    model_dir.mkdir(parents=True, exist_ok=True)

    # Native .keras (TF 2.15+ recommended single-file format). Must be written
    # while the TF graph is alive.
    try:
        artifact.model.save(str(model_dir / "model.keras"))
    except Exception as exc:  # noqa: BLE001 — log loudly, never swallow.
        _logger.error(
            "model.save(.keras) failed for %s in %s: %s",
            run_name, model_dir, exc,
        )

    # Architecture (JSON, also requires a live graph for to_json()).
    try:
        (model_dir / "NNarchitecture.json").write_text(
            artifact.model.to_json(), encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        _logger.error(
            "model.to_json() failed for %s: %s", run_name, exc,
        )

    # Legacy h5 weights (kept for backward compat with downstream code that
    # still loads weights-only artifacts).
    try:
        artifact.model.save_weights(str(model_dir / "NNweights.weights.h5"))
    except Exception as exc:  # noqa: BLE001
        _logger.error(
            "model.save_weights failed for %s: %s", run_name, exc,
        )

    return model_dir


# ---------------------------------------------------------------------------
# Full grid search pipeline
# ---------------------------------------------------------------------------

def run_training(
    df: pd.DataFrame,
    config: dict[str, Any],
    type_config: ModelTypeConfig,
    progress_callback: Callable[[ProgressPayload], None] | None = None,
    cancel_event=None,
) -> dict[str, TrainedModelArtifact]:
    """Execute the full grid search training pipeline in memory.

    Parameters
    ----------
    df : pre-loaded raw DataFrame (already read from file / upload).
    config : user configuration dict (same keys as the original CLI args).
    type_config : TV_CONFIG or PL_CONFIG.
    progress_callback : optional callable invoked per epoch.

    Returns
    -------
    Dict mapping ``run_name`` -> ``TrainedModelArtifact``.
    """
    input_cols = list(config.get("input_cols", type_config.input_cols))
    output_cols = list(config.get("output_cols", type_config.output_cols))
    on_off_norm = np.array(
        config.get("on_off_norm", type_config.on_off_norm), dtype=bool
    )

    if len(on_off_norm) != len(input_cols):
        raise ValueError(
            f"on_off_norm length ({len(on_off_norm)}) != input_cols length ({len(input_cols)})"
        )

    seed: int = int(config.get("seed", SEED))
    seed_everything(seed)

    # A9 (training_guard) — wall-clock deadline for the WHOLE grid search.
    # Instantiated once at the start so the per-run _DeadlineCallback aborts
    # cleanly when MAX_TRAINING_MINUTES is exceeded (cumulative across the
    # grid, not reset per model). Lazy import keeps the heavy TF module free
    # of a hard FastAPI dependency at import time. Callers may inject their
    # own via ``config["_deadline"]`` (e.g. tests with max_minutes=0).
    deadline = config.get("_deadline")
    if deadline is None:
        from ...training_guard import make_deadline
        deadline = make_deadline()

    # Enable TF op-level determinism once for the whole grid. Idempotent —
    # safe to call again per run, but doing it here avoids any redundant
    # overhead per training. Combined with per-run set_random_seed below,
    # this guarantees each (run_idx) yields a reproducible outcome.
    try:
        tf.config.experimental.enable_op_determinism()
    except Exception as exc:  # noqa: BLE001 — non-fatal on older TF
        _logger.debug(
            "enable_op_determinism unavailable on this TF build: %s", exc,
        )

    # Prepare data
    prepared = prepare_training_data(df, type_config, config=config)

    # Split
    test_size = float(config.get("test_size", type_config.default_test_size))

    # Resolve flag_permanent weighting — accept the legacy key as an alias
    # so existing session-config dicts keep working. New key wins if both
    # are present.
    use_weighting = bool(
        config.get(
            "use_flag_permanent_weighting",
            config.get(
                "use_flag_comptage_weighting",
                type_config.default_use_flag_permanent_weighting,
            ),
        )
    )
    if (
        "use_flag_comptage_weighting" in config
        and "use_flag_permanent_weighting" not in config
    ):
        _logger.warning(
            "training config: 'use_flag_comptage_weighting' is deprecated; "
            "renamed to 'use_flag_permanent_weighting'."
        )

    flag_col = str(
        config.get(
            "flag_permanent_col",
            config.get("flag_comptage_col", "flag_permanent"),
        )
    )
    flag_weight = float(
        config.get(
            "flag_priority_weight", type_config.default_flag_priority_weight
        )
    )

    # Recent-year boost (new, opt-in). Auto-detected MAX(year_mapped).
    use_recent_year = bool(
        config.get(
            "use_flag_recent_year_weighting",
            type_config.default_use_flag_recent_year_weighting,
        )
    )
    recent_year_weight = float(
        config.get(
            "recent_year_priority_weight",
            type_config.default_recent_year_priority_weight,
        )
    )

    # Bug 1 / Bug 2 — propagate target_log_transform and log_flow weighting to
    # split_train_valid. These were previously read by HardMining (Bug 1) but
    # never forwarded to the split function, so the training target stayed in
    # linear space and the log_flow weighting silently fell back to uniform.
    target_log_transform_cfg = bool(config.get("target_log_transform", False))
    use_log_flow_weighting = bool(config.get("use_log_flow_weighting", False))
    log_flow_weighting_col = str(config.get("log_flow_weighting_col", "TMJOBCTV"))

    # Bug 6 — scaler choice. Default "standard" preserves byte-identical
    # behaviour for callers that don't pass the flag. "robust" routes the
    # input-feature normalisation through median / (IQR/1.349) so heavy-
    # tailed traffic counts (TMJOBCTV…) are less affected by extreme values.
    # The target is always standard-normalised (legacy behaviour).
    scaler_cfg = str(config.get("scaler", "standard"))
    if scaler_cfg not in ("standard", "robust"):
        _logger.warning(
            "Unknown scaler '%s'; falling back to 'standard'.", scaler_cfg
        )
        scaler_cfg = "standard"

    # AUDIT BUG P0-5 — Optional in-loop TF persistence. When `_persist_dir`
    # is set, every artifact's TF-backed files (.keras, .weights.h5,
    # NNarchitecture.json) are serialised *inside* the grid loop, BEFORE
    # `tf.keras.backend.clear_session()` runs. This is the only safe moment
    # to write them: clear_session destroys the TF graph behind every model
    # already accumulated in `results`, so any deferred `model.save(...)`
    # by the caller silently fails.
    #
    # `_persist_prefix` mirrors the historical kind-prefix convention
    # (model_HPM_* / model_HPS_*) so the caller can keep its routing logic.
    _persist_dir_cfg = config.get("_persist_dir") or config.get("output_dir")
    _persist_prefix_cfg = str(config.get("_persist_prefix", "") or "")
    _persist_root: Path | None = None
    if _persist_dir_cfg:
        try:
            _persist_root = Path(str(_persist_dir_cfg))
            _persist_root.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001 — log + disable, never crash training
            _logger.error(
                "Failed to prepare TF persist dir %s: %s — TF saves will be "
                "skipped, caller will fall back to the legacy (and broken) path.",
                _persist_dir_cfg, exc,
            )
            _persist_root = None

    # Bug 5 — year_embedding plumbing. The request body field is
    # `use_year_embedding`; legacy callers used `year_embedding`. Accept both.
    use_year_embedding_cfg = bool(
        config.get(
            "use_year_embedding",
            config.get("year_embedding", False),
        )
    )
    year_embedding_dim_cfg = int(
        config.get("year_embedding_dim", 3)
    )

    # Bug 7 — feature engineering echo. Resolved here so we can stamp the
    # artifact's training_config (and have evaluation_pipeline replay them
    # on the validation df).
    _fe_block = dict(config.get("feature_engineering") or {})
    # Top-level keys win when both forms are present (matches data_prep._fe_settings).
    for _key in ("add_pl_tv_ratio", "log_transform_cols", "one_hot_functional_class"):
        if _key in config and _key not in _fe_block:
            _fe_block[_key] = config[_key]

    split = split_train_valid(
        prepared,
        input_cols=input_cols,
        output_cols=output_cols,
        test_size=test_size,
        seed=seed,
        use_flag_permanent_weighting=use_weighting,
        flag_permanent_col=flag_col,
        flag_priority_weight=flag_weight,
        use_flag_recent_year_weighting=use_recent_year,
        recent_year_priority_weight=recent_year_weight,
        target_log_transform=target_log_transform_cfg,
        use_log_flow_weighting=use_log_flow_weighting,
        log_flow_weighting_col=log_flow_weighting_col,
    )

    y = split["y"]
    y_train = split["y_train"]
    y_valid = split["y_valid"]
    idx_train = split["idx_train"]
    idx_valid = split["idx_valid"]

    # Normalize Y (always all columns)
    y_train_norm, mu_y, sigma_y = normalize(
        y_train, np.ones(y.shape[1], dtype=bool)
    )
    y_valid_norm = None
    if y_valid is not None:
        y_valid_norm, _, _ = normalize(
            y_valid, np.ones(y.shape[1], dtype=bool), mu_y, sigma_y
        )
    y_all_norm, _, _ = normalize(
        y, np.ones(y.shape[1], dtype=bool), mu_y, sigma_y
    )

    # Build feature sets
    mandatory = list(
        config.get("mandatory_input_cols", type_config.mandatory_input_cols)
    )
    min_input_count = int(
        config.get("min_input_count", type_config.min_input_count)
    )
    feature_subset_grid = bool(config.get("feature_subset_grid", True))
    mode = config.get("mode", "grid")

    feature_sets = build_feature_sets(
        all_input_cols=input_cols,
        mandatory_cols=mandatory,
        min_input_count=min_input_count,
        enable_feature_subset_grid=feature_subset_grid if mode == "grid" else False,
    )

    col_to_mask = {
        c: bool(v) for c, v in zip(input_cols, on_off_norm.tolist())
    }

    # Grid params
    activations = list(config.get("activations", type_config.default_activations))
    learning_rates = [
        float(v)
        for v in config.get("learning_rates", type_config.default_learning_rates)
    ]
    min_nb_epochs_list = [
        int(v)
        for v in config.get("min_nb_epochs_list", type_config.default_min_nb_epochs)
    ]
    max_epochs = int(config.get("max_epochs", type_config.default_max_epochs))
    dropout = float(config.get("dropout", type_config.default_dropout))
    analysis_scope = config.get("analysis_scope", "all")

    losses = list(config.get("losses", ["mse"]))
    dropouts = [float(v) for v in config.get("dropouts", [dropout])]
    neurons_factors_list = config.get("neurons_factors_list", [[1.0, 1.0]])
    use_batch_norm = bool(config.get("use_batch_norm", False))
    batch_sizes = [
        int(v)
        for v in config.get(
            "batch_sizes", [int(config.get("batch_size", type_config.default_batch_size))]
        )
    ]

    # P4.4 — multi-seed runs. Validated to a sane range so a typo cannot
    # accidentally explode the grid into hundreds of replicas.
    n_seeds = int(
        config.get("n_seeds", getattr(type_config, "default_n_seeds", 1))
    )
    if not (1 <= n_seeds <= 10):
        raise ValueError(
            f"n_seeds must be in [1, 10], got {n_seeds}."
        )

    # P4.5 / P4.6 — feature flags (combo-wide for now).
    use_hard_example_mining = bool(
        config.get(
            "use_hard_example_mining",
            getattr(type_config, "default_use_hard_example_mining", False),
        )
    )
    use_curriculum = bool(
        config.get(
            "use_curriculum",
            getattr(type_config, "default_use_curriculum", False),
        )
    )

    # P3 axes — pulled from config (preferred) or single defaults so any
    # caller that just passes a single value (e.g. optimizer="adamw") still
    # ends up with that value applied. Lists override singletons.
    def _as_list(key_list: str, key_single: str | None, default):
        if key_list in config and config[key_list] is not None:
            return list(config[key_list])
        if key_single is not None and key_single in config and config[key_single] is not None:
            return [config[key_single]]
        return list(default)

    optimizers = _as_list("optimizers", "optimizer", ["adam"])
    weight_decays = _as_list("weight_decays", "weight_decay", [0.0])
    skip_connection_options = _as_list(
        "skip_connection_options", "use_skip_connection", [False]
    )
    dropout_schedules = _as_list(
        "dropout_schedules", "dropout_schedule", ["uniform"]
    )
    clipnorms_list = _as_list("clipnorms", "clipnorm", [None])
    norm_layers_list = _as_list("norm_layers", "norm_layer", [None])
    # Bug 4 — wire `use_quantile_head` into the grid so each combo carries
    # the flag (build_model needs combo.use_quantile_head). Accept both the
    # singular form (`use_quantile_head=True`) and the list form.
    quantile_head_options = _as_list(
        "quantile_head_options", "use_quantile_head", [False]
    )

    combinations = generate_all_combinations(
        feature_sets=feature_sets,
        all_input_cols=input_cols,
        activations=activations,
        learning_rates=learning_rates,
        min_nb_epochs_list=min_nb_epochs_list,
        losses=losses,
        dropouts=dropouts,
        neurons_factors_list=neurons_factors_list,
        batch_sizes=batch_sizes,
        optimizers=optimizers,
        weight_decays=weight_decays,
        skip_connection_options=skip_connection_options,
        dropout_schedules=dropout_schedules,
        clipnorms=clipnorms_list,
        norm_layers=norm_layers_list,
        quantile_head_options=quantile_head_options,
    )

    # Multiply combo count by n_seeds so the progress UI receives an
    # accurate total (e.g. 5 combos x 3 seeds -> total_models == 15).
    total_models = len(combinations) * n_seeds
    if total_models == 0:
        return {}
    _hard_cap = int(config.get("_max_grid_combinations", 100))
    if total_models > _hard_cap:
        raise ValueError(
            f"Grid search would expand to {total_models} combinations "
            f"(combos={len(combinations)} x n_seeds={n_seeds}); "
            f"refuse to launch (hard cap = {_hard_cap})."
        )

    results: dict[str, TrainedModelArtifact] = {}

    # P4.6 — Flow array for curriculum learning. We read the BC denominator
    # column (TMJOBCTV for TV, TMJOBCPL for PL) from the prepared df. The
    # idx_train indices are aligned with the prepared df row order so this
    # gives us per-train-row flow values directly.
    flow_full: np.ndarray | None = None
    if use_curriculum:
        bc_col = type_config.target_denominator_bc
        if bc_col in prepared.columns:
            flow_full = pd.to_numeric(
                prepared[bc_col], errors="coerce"
            ).fillna(0.0).values.astype(float)
        else:
            _logger.warning(
                "Curriculum learning requested but column %s is absent — "
                "feature will be disabled on a per-combo basis.",
                bc_col,
            )

    # P4.5 — Observed y_train in *natural* (denormalized, pre-log-transform)
    # space, required to compute the relative-error threshold. We invert
    # log1p when target_log_transform was applied so the comparison is in
    # TxPen %, not log-space.
    target_log_transform = bool(prepared is not None and config.get("target_log_transform", False))
    if y_train.ndim == 2 and y_train.shape[1] >= 1:
        y_train_obs_raw = y_train[:, 0].astype(float).copy()
    else:
        y_train_obs_raw = np.asarray(y_train, dtype=float).reshape(-1).copy()
    if target_log_transform:
        # y_train was log1p()-transformed inside split_train_valid -> reverse.
        y_train_obs_natural = np.expm1(y_train_obs_raw)
    else:
        y_train_obs_natural = y_train_obs_raw

    # Group by feature mask to share normalization
    from collections import defaultdict

    by_mask: dict[str, list[GridCombination]] = defaultdict(list)
    for combo in combinations:
        by_mask[combo.feature_mask].append(combo)

    model_idx = 0

    for fmask, combos in by_mask.items():
        feature_cols = combos[0].feature_cols
        on_off_subset = np.array(
            [col_to_mask[c] for c in feature_cols], dtype=bool
        )

        x_subset = prepared[feature_cols].values.astype(float)
        x_tr = x_subset[idx_train]
        x_va = x_subset[idx_valid] if idx_valid is not None else None

        # Bug 6 — apply the configured scaler ("standard"|"robust") to the
        # input features. valid/all reuse the train-fitted mu/sigma so the
        # scaler argument is moot on those calls (kept for symmetry).
        x_train_norm, mu_x, sigma_x = normalize(
            x_tr, on_off_subset, scaler=scaler_cfg
        )
        x_valid_norm = None
        if x_va is not None:
            x_valid_norm, _, _ = normalize(x_va, on_off_subset, mu_x, sigma_x)
        x_all_norm, _, _ = normalize(x_subset, on_off_subset, mu_x, sigma_x)

        # P4.6 — pre-slice flow array to align with the train indices used
        # by *this* feature group. idx_train is the same for every feature
        # group (only the column subset varies), so we slice once per group.
        flow_train_for_curriculum: np.ndarray | None = None
        if flow_full is not None:
            flow_train_for_curriculum = flow_full[idx_train]

        for combo in combos:
            if cancel_event is not None and cancel_event.is_set():
                return results
            # P4.4 — replicate each combo `n_seeds` times. When n_seeds == 1
            # the run_name is unchanged (back-compat); otherwise a
            # `_seed<i>` suffix disambiguates the artifacts.
            for seed_idx in range(n_seeds):
                if cancel_event is not None and cancel_event.is_set():
                    return results
                model_idx += 1
                # Per-run deterministic seeding: each run gets a unique
                # offset so the grid no longer collapses onto a handful of
                # repeated (tol, p80) tuples. enable_op_determinism() was
                # already activated once above; it is idempotent.
                run_idx = model_idx - 1
                run_seed = seed + run_idx
                seed_everything(run_seed, enable_op_determinism=False)
                tf.keras.utils.set_random_seed(run_seed)

                run_name_eff = (
                    combo.run_name if n_seeds == 1
                    else f"{combo.run_name}_seed{seed_idx}"
                )

                artifact = _train_single(
                    x_train_norm=x_train_norm,
                    y_train_norm=y_train_norm,
                    x_valid_norm=x_valid_norm,
                    y_valid_norm=y_valid_norm,
                    x_all_norm=x_all_norm,
                    y_all_norm=y_all_norm,
                    mu_x=mu_x,
                    sigma_x=sigma_x,
                    mu_y=mu_y,
                    sigma_y=sigma_y,
                    combo=combo,
                    max_epochs=max_epochs,
                    analysis_scope=analysis_scope,
                    output_cols=output_cols,
                    on_off_subset=on_off_subset,
                    seed=run_seed,
                    train_sample_weight=split["train_sample_weight"],
                    valid_sample_weight=split["valid_sample_weight"],
                    use_flag_permanent_weighting=use_weighting,
                    flag_permanent_col=flag_col,
                    flag_priority_weight=flag_weight,
                    use_flag_recent_year_weighting=use_recent_year,
                    recent_year_priority_weight=recent_year_weight,
                    use_batch_norm=use_batch_norm,
                    progress_callback=progress_callback,
                    total_models=total_models,
                    model_idx=model_idx,
                    test_size=test_size,
                    year_column_name=str(config.get("year_column_name") or ""),
                    year_value_mapping=dict(config.get("year_value_mapping") or {}),
                    cancel_event=cancel_event,
                    deadline=deadline,
                    reduce_lr_patience=int(config.get("reduce_lr_patience", 10)),
                    reduce_lr_factor=float(config.get("reduce_lr_factor", 0.5)),
                    reduce_lr_min=float(config.get("reduce_lr_min", 1e-5)),
                    run_name_override=run_name_eff,
                    use_hard_example_mining=use_hard_example_mining,
                    use_curriculum=use_curriculum,
                    flow_for_curriculum=flow_train_for_curriculum,
                    y_train_obs=y_train_obs_natural,
                    target_log_transform=target_log_transform,
                    # Phase 5 bug-fix plumbing — see Bug 1/2/5/6/7.
                    use_log_flow_weighting=use_log_flow_weighting,
                    log_flow_weighting_col=log_flow_weighting_col,
                    scaler=scaler_cfg,
                    use_year_embedding=use_year_embedding_cfg,
                    year_embedding_dim=year_embedding_dim_cfg,
                    feature_engineering_echo=_fe_block,
                )
                # Stamp multi-seed metadata in the echo for downstream code.
                # Failing here would corrupt downstream reporting, so log
                # explicitly rather than swallowing silently (audit bonus).
                try:
                    artifact.training_config["n_seeds"] = int(n_seeds)
                    artifact.training_config["seed_index"] = int(seed_idx)
                    artifact.training_config["base_run_name"] = combo.run_name
                except Exception as exc:  # noqa: BLE001 — defensive
                    _logger.error(
                        "Failed to stamp multi-seed metadata on %s: %s",
                        run_name_eff, exc,
                    )

                # AUDIT BUG P0-5 — Persist TF-backed files NOW, while the
                # graph is still alive. clear_session() below will destroy
                # the graph behind every model already in `results`, so any
                # later artifact.model.save(...) call by the caller will
                # raise. Writing here (and stamping `_persisted_dir` on the
                # config) lets the caller skip the broken re-save path.
                if _persist_root is not None:
                    disk_run_name = f"{_persist_prefix_cfg}{run_name_eff}"
                    try:
                        persisted_dir = _persist_tf_artifact(
                            artifact, _persist_root, run_name=disk_run_name,
                        )
                        artifact.training_config["_persisted_dir"] = str(persisted_dir)
                        artifact.training_config["_persisted_run_name"] = disk_run_name
                    except Exception as exc:  # noqa: BLE001 — never crash the grid
                        _logger.error(
                            "TF persistence failed for %s: %s — caller will "
                            "fall back to legacy save (likely broken).",
                            run_name_eff, exc,
                        )

                results[run_name_eff] = artifact
                # C7: free TF state between every model (not just between
                # feature groups) — long grids otherwise leak ~hundreds of
                # MB on CPU. SAFE here because _persist_tf_artifact() above
                # already wrote every TF-backed file to disk.
                import gc as _gc
                del artifact
                _gc.collect()
                try:
                    tf.keras.backend.clear_session()
                except Exception as exc:  # noqa: BLE001 — defensive
                    _logger.warning(
                        "clear_session after model failed: %s", exc,
                    )

    return results
