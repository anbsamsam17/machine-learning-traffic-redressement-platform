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

def _build_combinations(cfg: dict) -> list[dict]:
    """Build all hyperparameter combinations for grid search."""
    combos = []
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
                                    f"_drp{dropout}_nf{nf_label}_bs{bs}"
                                )
                                combos.append({
                                    "run_name": run_name,
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

def _training_worker(task: TrainingTask) -> None:
    """Runs grid search training in a separate thread."""
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

    try:
        import tensorflow as tf
        from tensorflow.keras.models import Sequential
        from tensorflow.keras.layers import Dense, Dropout, BatchNormalization
        from tensorflow.keras.optimizers import Adam
        from tensorflow.keras.losses import MeanSquaredError, Huber, MeanAbsoluteError
        from tensorflow.keras.metrics import R2Score, MeanAbsolutePercentageError

        tf.config.threading.set_intra_op_parallelism_threads(4)
        tf.config.threading.set_inter_op_parallelism_threads(2)

        task.status = "running"
        cfg = task.config

        # Log received config for debugging
        combos_preview = _build_combinations(cfg)
        logger.info(
            "Training worker started: task=%s | input_cols=%s | output_dir=%s | "
            "max_epochs=%s | activations=%s | learning_rates=%s | losses=%s | "
            "min_nb_epochs_list=%s | dropouts=%s | batch_sizes=%s | "
            "neurons_factors_list=%s | total_combinations=%d",
            task.task_id,
            cfg.get("input_cols"),
            cfg.get("output_dir"),
            cfg.get("max_epochs"),
            cfg.get("activations"),
            cfg.get("learning_rates"),
            cfg.get("losses"),
            cfg.get("min_nb_epochs_list"),
            cfg.get("dropouts"),
            cfg.get("batch_sizes"),
            cfg.get("neurons_factors_list"),
            len(combos_preview),
        )

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

        input_cols: list[str] = cfg["input_cols"]
        output_col: str = cfg.get("output_cols", ["TxPenTVRef"])[0] if isinstance(cfg.get("output_cols"), list) else cfg.get("output_col", "TxPenTVRef")

        # Check columns
        missing = [c for c in input_cols + [output_col] if c not in df.columns]
        if missing:
            raise RuntimeError(f"Colonnes manquantes dans le DF: {missing}")

        # Build X, y
        sub = df[input_cols + [output_col]].dropna()
        if len(sub) < 5:
            raise RuntimeError(f"Trop peu de lignes valides ({len(sub)}).")

        seed = cfg.get("seed", SEED)
        np.random.seed(seed)
        tf.random.set_seed(seed)

        X = sub[input_cols].values.astype(np.float64)
        y = sub[output_col].values.astype(np.float64).reshape(-1, 1)

        # ON_OFF_NORM mask
        on_off_norm = cfg.get("on_off_norm", [True] * len(input_cols))
        if len(on_off_norm) != len(input_cols):
            on_off_norm = [True] * len(input_cols)
        on_off_mask = np.array(on_off_norm, dtype=bool)

        # Z-score normalize
        x_mean = np.zeros(X.shape[1])
        x_std = np.ones(X.shape[1])
        if on_off_mask.any():
            x_mean[on_off_mask] = X[:, on_off_mask].mean(axis=0)
            x_std[on_off_mask] = X[:, on_off_mask].std(axis=0)
            x_std[x_std == 0] = 1.0
        y_mean = y.mean()
        y_std = y.std()
        if y_std == 0:
            y_std = 1.0

        X_norm = X.copy()
        X_norm[:, on_off_mask] = (X[:, on_off_mask] - x_mean[on_off_mask]) / x_std[on_off_mask]
        y_norm = (y - y_mean) / y_std

        # Train/valid split
        test_size = cfg.get("test_size", 0.0)
        if test_size > 0:
            from sklearn.model_selection import train_test_split
            X_train, X_val, y_train, y_val = train_test_split(
                X_norm, y_norm, test_size=test_size, random_state=seed
            )
        else:
            X_train, y_train = X_norm, y_norm
            X_val, y_val = X_norm, y_norm

        # Generate all combinations
        combos = _build_combinations(cfg)
        total_models = len(combos)
        max_epochs = cfg.get("max_epochs", 2050)
        use_batch_norm = cfg.get("use_batch_norm", False)
        output_dir = cfg.get("output_dir")

        # Prepare output dir
        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            logger.info("Output directory created/verified: %s", out_path.resolve())
        else:
            logger.warning("No output_dir specified — models will NOT be saved to disk!")

        task.progress.append({
            "type": "info",
            "message": f"Demarrage du grid search : {total_models} combinaisons",
            "total_models": total_models,
        })

        best_global_val_loss = float("inf")
        best_model_name = ""
        results_list = []

        for model_idx, combo in enumerate(combos):
            if task.cancelled:
                task.status = "cancelled"
                return

            run_name = combo["run_name"]

            task.progress.append({
                "type": "model_start",
                "model_index": model_idx,
                "total_models": total_models,
                "model_name": run_name,
            })

            # Build model
            nf = combo["neurons_factors"]
            activation = combo["activation"]
            dropout = combo["dropout"]
            initializer = "lecun_normal" if activation == "selu" else "he_normal"

            model = Sequential()
            model.add(Dropout(dropout, input_shape=(len(input_cols),)))
            for factor in nf:
                n_units = max(2, int(round(len(input_cols) * factor)))
                model.add(Dense(n_units, activation=activation, kernel_initializer=initializer))
                if use_batch_norm:
                    model.add(BatchNormalization())
                model.add(Dropout(dropout))
            model.add(Dense(1, activation="linear"))

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

            callbacks_list = [
                tf.keras.callbacks.EarlyStopping(
                    monitor="val_loss",
                    patience=patience,
                    restore_best_weights=True,
                    start_from_epoch=min_ep,
                ),
            ]

            # Progress callback
            class GridProgressCallback(tf.keras.callbacks.Callback):
                def on_epoch_end(cb_self, epoch, logs=None):
                    if task.cancelled:
                        cb_self.model.stop_training = True
                        return
                    logs = logs or {}
                    task.progress.append({
                        "type": "epoch",
                        "model_index": model_idx,
                        "total_models": total_models,
                        "model_name": run_name,
                        "epoch": epoch + 1,
                        "total_epochs": max_epochs,
                        "loss": float(logs.get("loss", 0)),
                        "val_loss": float(logs.get("val_loss", 0)),
                        "elapsed": time.time() - task.started_at,
                    })

            callbacks_list.append(GridProgressCallback())

            # Train
            history = model.fit(
                X_train, y_train,
                validation_data=(X_val, y_val),
                epochs=max_epochs,
                batch_size=combo["batch_size"],
                verbose=0,
                callbacks=callbacks_list,
            )

            if task.cancelled:
                task.status = "cancelled"
                return

            # Evaluate
            val_loss = float(model.evaluate(X_val, y_val, verbose=0)[0])
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
                "model_index": model_idx,
                "model_name": run_name,
                "val_loss": val_loss,
                "epochs_trained": epochs_trained,
                "best_val_loss": best_global_val_loss,
                "best_model_name": best_model_name,
            })

            # Save model to output_dir
            if output_dir:
                model_dir = Path(output_dir) / run_name
                logger.info("Saving model to %s", model_dir)
                model_dir.mkdir(parents=True, exist_ok=True)

                (model_dir / "NNarchitecture.json").write_text(
                    model.to_json(), encoding="utf-8"
                )
                model.save_weights(str(model_dir / "NNweights.weights.h5"))

                norm_json = json.dumps({
                    "muX": [x_mean.tolist()],
                    "SX": [x_std.tolist()],
                    "muY": [[float(y_mean)]],
                    "SY": [[float(y_std)]],
                }, indent=2)
                (model_dir / "NNnormCoefficients.json").write_text(
                    norm_json, encoding="utf-8"
                )

                train_cfg = json.dumps({
                    "run_name": run_name,
                    "input_cols": input_cols,
                    "output_col": output_col,
                    "epochs_requested": max_epochs,
                    "epochs_trained": epochs_trained,
                    "batch_size": combo["batch_size"],
                    "learning_rate": combo["learning_rate"],
                    "activation": combo["activation"],
                    "dropout": combo["dropout"],
                    "loss": combo["loss"],
                    "neurons_factors": combo["neurons_factors"],
                    "seed": seed,
                    "train_rows": len(X_train),
                    "val_rows": len(X_val),
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
                    "Model %d/%d saved: %s (4 files: NNarchitecture.json, NNweights.weights.h5, "
                    "NNnormCoefficients.json, training_config.json, training_metrics.json)",
                    model_idx + 1, total_models, model_dir,
                )
            else:
                logger.warning(
                    "Model %d/%d NOT saved (no output_dir): %s",
                    model_idx + 1, total_models, run_name,
                )

            logger.info(
                "Model %d/%d done: %s val_loss=%.6f epochs=%d",
                model_idx + 1, total_models, run_name, val_loss, epochs_trained,
            )

        # Done
        task.result = {
            "total_models": total_models,
            "best_model": best_model_name,
            "best_val_loss": best_global_val_loss,
            "output_dir": output_dir,
            "results": results_list,
        }
        task.status = "completed"
        logger.info(
            "Grid search completed: %d models, best=%s (%.6f)",
            total_models, best_model_name, best_global_val_loss,
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
        raise HTTPException(status_code=400, detail="Pas de DataFrame d'apprentissage.")

    combos = _build_combinations(body.model_dump())
    total = len(combos)

    task_id = uuid.uuid4().hex[:12]
    task = TrainingTask(
        task_id=task_id,
        session_id=body.session_id,
        config=body.model_dump(),
    )

    with _tasks_lock:
        _tasks[task_id] = task

    thread = threading.Thread(target=_training_worker, args=(task,), daemon=True)
    thread.start()

    logger.info(
        "Grid search started: task=%s session=%s combos=%d output_dir=%s max_epochs=%d",
        task_id, body.session_id, total, body.output_dir, body.max_epochs,
    )

    return TrainingStartResponse(
        task_id=task_id,
        session_id=body.session_id,
        status="pending",
        total_combinations=total,
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
