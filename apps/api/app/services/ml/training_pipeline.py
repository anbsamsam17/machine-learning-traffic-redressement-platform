"""Unified training pipeline for TV and PL models.

Runs the full grid search loop entirely in memory and returns a dict
of trained model artifacts (weights, norm coefficients, config, metrics).
No disk I/O is performed.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable

# GPU disabled before any TF import
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow import keras

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
    use_flag_comptage_weighting: bool,
    flag_comptage_col: str,
    flag_priority_weight: float,
    use_batch_norm: bool,
    progress_callback: Callable[[ProgressPayload], None] | None,
    total_models: int,
    model_idx: int,
    test_size: float,
) -> TrainedModelArtifact:
    """Train one model and return an in-memory artifact."""

    model = build_model(
        input_size=x_train_norm.shape[1],
        output_size=y_train_norm.shape[1],
        learning_rate=combo.learning_rate,
        activation=combo.activation,
        dropout=combo.dropout,
        loss=combo.loss,
        neurons_factors=combo.neurons_factors,
        use_batch_norm=use_batch_norm,
    )

    # EarlyStopping — patience=50 fixed (audit ML P0-3). start_from_epoch
    # is capped at min(50, min_nb_epochs // 4) so divergent runs can still
    # bail out before the soft `min_nb_epochs` floor.
    patience = 50
    start_from = min(50, max(1, combo.min_nb_epochs // 4))

    early_stop = keras.callbacks.EarlyStopping(
        monitor="val_loss",
        patience=patience,
        restore_best_weights=True,
        start_from_epoch=start_from,
    )
    reduce_lr = keras.callbacks.ReduceLROnPlateau(
        monitor="val_loss",
        factor=0.5,
        patience=20,
        min_lr=1e-5,
        verbose=0,
    )

    callbacks_list: list = [early_stop, reduce_lr]
    if progress_callback is not None:
        callbacks_list.append(
            TrainingProgressCallback(
                callback=progress_callback,
                run_name=combo.run_name,
                total_epochs=max_epochs,
                total_models=total_models,
                model_idx=model_idx,
            )
        )

    fit_kwargs: dict[str, Any] = {
        "x": x_train_norm,
        "y": y_train_norm,
        "epochs": max_epochs,
        "batch_size": min(combo.batch_size, len(x_train_norm)),
        "verbose": 0,
        "callbacks": callbacks_list,
    }
    if train_sample_weight is not None:
        fit_kwargs["sample_weight"] = train_sample_weight
    if x_valid_norm is not None and y_valid_norm is not None:
        if valid_sample_weight is not None:
            fit_kwargs["validation_data"] = (
                x_valid_norm, y_valid_norm, valid_sample_weight
            )
        else:
            fit_kwargs["validation_data"] = (x_valid_norm, y_valid_norm)

    history = model.fit(**fit_kwargs)

    # Evaluate
    if analysis_scope == "all":
        eval_x, eval_y = x_all_norm, y_all_norm
    else:
        eval_x, eval_y = x_valid_norm, y_valid_norm
        if eval_x is None or eval_y is None:
            eval_x, eval_y = x_all_norm, y_all_norm

    eval_values = model.evaluate(eval_x, eval_y, verbose=0)
    metrics = {
        name: float(np.round(value, 6))
        for name, value in zip(model.metrics_names, eval_values)
    }

    config_dict = {
        "run_name": combo.run_name,
        "input_cols": combo.feature_cols,
        "output_cols": output_cols,
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
        "start_from_epoch": start_from,
        "patience": patience,
        "reduce_lr_factor": 0.5,
        "reduce_lr_patience": 20,
        "reduce_lr_min": 1e-5,
        "analysis_scope": analysis_scope,
        "seed": seed,
        "train_rows": int(len(x_train_norm)),
        "valid_rows": int(0 if x_valid_norm is None else len(x_valid_norm)),
        "eval_rows": int(len(eval_x)),
        "use_flag_comptage_weighting": bool(use_flag_comptage_weighting),
        "flag_comptage_col": flag_comptage_col,
        "flag_priority_weight": float(flag_priority_weight),
    }

    return TrainedModelArtifact(
        run_name=combo.run_name,
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
# Full grid search pipeline
# ---------------------------------------------------------------------------

def run_training(
    df: pd.DataFrame,
    config: dict[str, Any],
    type_config: ModelTypeConfig,
    progress_callback: Callable[[ProgressPayload], None] | None = None,
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

    # Prepare data
    prepared = prepare_training_data(df, type_config, config=config)

    # Split
    test_size = float(config.get("test_size", type_config.default_test_size))
    use_weighting = bool(config.get("use_flag_comptage_weighting", False))
    flag_col = config.get("flag_comptage_col", "flag_comptage")
    flag_weight = float(config.get("flag_priority_weight", 4.0))

    split = split_train_valid(
        prepared,
        input_cols=input_cols,
        output_cols=output_cols,
        test_size=test_size,
        seed=seed,
        use_flag_comptage_weighting=use_weighting,
        flag_comptage_col=flag_col,
        flag_priority_weight=flag_weight,
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
    )

    total_models = len(combinations)
    if total_models == 0:
        return {}

    results: dict[str, TrainedModelArtifact] = {}

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

        x_train_norm, mu_x, sigma_x = normalize(x_tr, on_off_subset)
        x_valid_norm = None
        if x_va is not None:
            x_valid_norm, _, _ = normalize(x_va, on_off_subset, mu_x, sigma_x)
        x_all_norm, _, _ = normalize(x_subset, on_off_subset, mu_x, sigma_x)

        for combo in combos:
            model_idx += 1
            # Reseed before each fit so model-init / shuffles are reproducible
            seed_everything(seed, enable_op_determinism=False)
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
                seed=seed,
                train_sample_weight=split["train_sample_weight"],
                valid_sample_weight=split["valid_sample_weight"],
                use_flag_comptage_weighting=use_weighting,
                flag_comptage_col=flag_col,
                flag_priority_weight=flag_weight,
                use_batch_norm=use_batch_norm,
                progress_callback=progress_callback,
                total_models=total_models,
                model_idx=model_idx,
                test_size=test_size,
            )
            results[combo.run_name] = artifact

    return results
