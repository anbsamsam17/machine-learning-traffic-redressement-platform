"""Training router — launch background training, SSE streaming, cancellation."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
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


# ---------------------------------------------------------------------------
# Task registry (in-memory)
# ---------------------------------------------------------------------------

class TrainingTask:
    """Tracks one background training run."""

    def __init__(self, task_id: str, session_id: str, config: dict[str, Any]) -> None:
        self.task_id = task_id
        self.session_id = session_id
        self.config = config
        self.status: str = "pending"  # pending | running | completed | failed | cancelled
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
    mode: str = "TV"  # TV | PL
    input_cols: list[str] = [
        "TMJAFCDTV", "TMJAFCDPL",
        "car_average_distance_km", "car_average_speed_kmh",
        "truck_min_average_distance_km", "truck_average_speed_kmh",
    ]
    output_col: str = "TxPenTVRef"
    hidden_layers: list[int] = [64, 32, 16]
    activations: list[str] = ["relu", "relu", "relu"]
    learning_rate: float = 0.001
    epochs: int = 200
    batch_size: int = 32
    dropout: float = 0.0
    validation_split: float = 0.2
    seed: int = 1750


class TrainingStartResponse(BaseModel):
    task_id: str
    session_id: str
    status: str


class TrainingStatusResponse(BaseModel):
    task_id: str
    status: str
    progress_pct: float
    current_epoch: int
    total_epochs: int
    loss: float | None = None
    val_loss: float | None = None
    error: str | None = None


class TrainingCancelResponse(BaseModel):
    task_id: str
    status: str


# ---------------------------------------------------------------------------
# Column name translation (learning DF names -> training script names)
# ---------------------------------------------------------------------------

_COL_RENAMES = {
    "TMJATV": "TMJAFCDTV",
    "TMJAPL": "TMJAFCDPL",
    "TxPen": "TxPenTVRef",
    "TxPenPL": "TxPenPLRef",
}


# ---------------------------------------------------------------------------
# Background training worker
# ---------------------------------------------------------------------------

def _training_worker(task: TrainingTask) -> None:
    """Runs in a separate thread — builds and trains a Keras model."""
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

    try:
        import tensorflow as tf
        from tensorflow.keras.models import Sequential
        from tensorflow.keras.layers import Dense, Dropout
        from tensorflow.keras.optimizers import Adam

        tf.config.threading.set_intra_op_parallelism_threads(4)
        tf.config.threading.set_inter_op_parallelism_threads(2)

        task.status = "running"
        cfg = task.config

        # -- Get learning DataFrame -------------------------------------------
        session = session_manager.get_session(task.session_id)
        if session is None:
            raise RuntimeError("Session expiree.")
        learning_df: pd.DataFrame | None = session.data.get("learning_df")
        if learning_df is None:
            raise RuntimeError("Pas de DataFrame d'apprentissage dans la session.")

        # Rename columns to match training scripts expectations
        df = learning_df.copy()
        for old_name, new_name in _COL_RENAMES.items():
            if old_name in df.columns and new_name not in df.columns:
                df[new_name] = df[old_name]

        input_cols: list[str] = cfg["input_cols"]
        output_col: str = cfg["output_col"]

        # Check columns exist
        missing = [c for c in input_cols + [output_col] if c not in df.columns]
        if missing:
            raise RuntimeError(f"Colonnes manquantes dans le DF: {missing}")

        # Build X, y — drop NaN rows
        sub = df[input_cols + [output_col]].dropna()
        if len(sub) < 10:
            raise RuntimeError(f"Trop peu de lignes valides ({len(sub)}) apres suppression des NaN.")

        np.random.seed(cfg["seed"])
        tf.random.set_seed(cfg["seed"])

        X = sub[input_cols].values.astype(np.float64)
        y = sub[output_col].values.astype(np.float64).reshape(-1, 1)

        # Z-score normalization
        x_mean = X.mean(axis=0)
        x_std = X.std(axis=0)
        x_std[x_std == 0] = 1.0
        y_mean = y.mean()
        y_std = y.std()
        if y_std == 0:
            y_std = 1.0

        X_norm = (X - x_mean) / x_std
        y_norm = (y - y_mean) / y_std

        # Train/test split
        from sklearn.model_selection import train_test_split
        X_train, X_val, y_train, y_val = train_test_split(
            X_norm, y_norm,
            test_size=cfg["validation_split"],
            random_state=cfg["seed"],
        )

        # Build model
        hidden_layers: list[int] = cfg["hidden_layers"]
        activations: list[str] = cfg["activations"]
        dropout: float = cfg["dropout"]

        model = Sequential()
        for i, (units, activation) in enumerate(zip(hidden_layers, activations)):
            if i == 0:
                model.add(Dense(units, activation=activation, input_shape=(len(input_cols),)))
            else:
                model.add(Dense(units, activation=activation))
            if dropout > 0:
                model.add(Dropout(dropout))
        model.add(Dense(1, activation="linear"))

        model.compile(
            optimizer=Adam(learning_rate=cfg["learning_rate"]),
            loss="mse",
        )

        # Custom callback for progress tracking
        total_epochs: int = cfg["epochs"]

        class ProgressCallback(tf.keras.callbacks.Callback):
            def on_epoch_end(self, epoch: int, logs: dict | None = None) -> None:
                if task.cancelled:
                    self.model.stop_training = True
                    return
                logs = logs or {}
                entry = {
                    "epoch": epoch + 1,
                    "total_epochs": total_epochs,
                    "loss": float(logs.get("loss", 0)),
                    "val_loss": float(logs.get("val_loss", 0)),
                    "timestamp": time.time(),
                }
                task.progress.append(entry)

        # Timeout callback
        settings = get_settings()
        max_seconds = settings.MAX_TRAINING_MINUTES * 60

        class TimeoutCallback(tf.keras.callbacks.Callback):
            def on_epoch_end(self, epoch: int, logs: dict | None = None) -> None:
                elapsed = time.time() - task.started_at
                if elapsed > max_seconds:
                    logger.warning("Training timeout after %d s", int(elapsed))
                    self.model.stop_training = True

        # Train
        model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=total_epochs,
            batch_size=cfg["batch_size"],
            verbose=0,
            callbacks=[ProgressCallback(), TimeoutCallback()],
        )

        if task.cancelled:
            task.status = "cancelled"
            return

        # Evaluate
        val_loss = model.evaluate(X_val, y_val, verbose=0)

        # Store results in session
        model_json = model.to_json()
        weights_tmp = tempfile.NamedTemporaryFile(suffix=".weights.h5", delete=False)
        model.save_weights(weights_tmp.name)
        with open(weights_tmp.name, "rb") as wf:
            weights_bytes = wf.read()
        Path(weights_tmp.name).unlink(missing_ok=True)

        norm_params = {
            "x_mean": x_mean.tolist(),
            "x_std": x_std.tolist(),
            "y_mean": float(y_mean),
            "y_std": float(y_std),
            "input_cols": input_cols,
            "output_col": output_col,
        }

        task.result = {
            "val_loss": float(val_loss),
            "train_rows": len(X_train),
            "val_rows": len(X_val),
            "total_rows": len(sub),
            "epochs_completed": len(task.progress),
        }

        session_manager.store_data(task.session_id, "trained_model_json", model_json)
        session_manager.store_data(task.session_id, "trained_weights", weights_bytes)
        session_manager.store_data(task.session_id, "norm_params", norm_params)
        session_manager.store_data(task.session_id, "training_result", task.result)

        task.status = "completed"
        logger.info("Training completed: task=%s val_loss=%.6f", task.task_id, val_loss)

    except Exception as exc:
        task.status = "failed"
        task.error = str(exc)
        logger.exception("Training failed: task=%s", task.task_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/start", response_model=TrainingStartResponse)
async def start_training(body: TrainingConfig) -> TrainingStartResponse:
    """Launch a background training task."""
    session = session_manager.get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

    if session.data.get("learning_df") is None:
        raise HTTPException(
            status_code=400,
            detail="Pas de DataFrame d'apprentissage. Validez le mapping d'abord.",
        )

    task_id = uuid.uuid4().hex[:12]
    task = TrainingTask(
        task_id=task_id,
        session_id=body.session_id,
        config=body.model_dump(exclude={"session_id"}),
    )

    with _tasks_lock:
        _tasks[task_id] = task

    thread = threading.Thread(target=_training_worker, args=(task,), daemon=True)
    thread.start()

    logger.info("Training started: task=%s session=%s", task_id, body.session_id)

    return TrainingStartResponse(
        task_id=task_id,
        session_id=body.session_id,
        status="pending",
    )


@router.get("/stream/{task_id}")
async def stream_training(task_id: str) -> StreamingResponse:
    """SSE endpoint — streams training progress as Server-Sent Events."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trouvee.")

    async def event_generator():
        last_idx = 0
        while True:
            # Send any new progress entries
            current_progress = task.progress[last_idx:]
            for entry in current_progress:
                data = json.dumps(entry)
                yield f"data: {data}\n\n"
                last_idx += 1

            # Check terminal states
            if task.status in ("completed", "failed", "cancelled"):
                final = {
                    "type": "final",
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
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status/{task_id}", response_model=TrainingStatusResponse)
async def training_status(task_id: str) -> TrainingStatusResponse:
    """Poll current training status (alternative to SSE)."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trouvee.")

    last = task.progress[-1] if task.progress else {}
    total_epochs = task.config.get("epochs", 1)
    current_epoch = last.get("epoch", 0)

    return TrainingStatusResponse(
        task_id=task_id,
        status=task.status,
        progress_pct=round(current_epoch / total_epochs * 100, 1) if total_epochs else 0,
        current_epoch=current_epoch,
        total_epochs=total_epochs,
        loss=last.get("loss"),
        val_loss=last.get("val_loss"),
        error=task.error,
    )


@router.post("/cancel/{task_id}", response_model=TrainingCancelResponse)
async def cancel_training(task_id: str) -> TrainingCancelResponse:
    """Request cancellation of a running training task."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trouvee.")

    task.cancel()
    logger.info("Training cancel requested: task=%s", task_id)

    return TrainingCancelResponse(task_id=task_id, status="cancelling")
