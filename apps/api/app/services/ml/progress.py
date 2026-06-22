"""Keras callback for streaming training progress.

Provides an in-memory callback that invokes a user-supplied callable
on every epoch end, instead of writing to a JSONL file on disk.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

# Ensure GPU is disabled before any TF import
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

from tensorflow import keras  # noqa: E402

logger = logging.getLogger(__name__)


class ProgressPayload:
    """Simple namespace for progress data sent to the callback."""

    __slots__ = (
        "run_name",
        "epoch",
        "total_epochs",
        "model_idx",
        "total_models",
        "loss",
        "val_loss",
        "timestamp",
    )

    def __init__(
        self,
        run_name: str,
        epoch: int,
        total_epochs: int,
        model_idx: int,
        total_models: int,
        loss: float,
        val_loss: float | None,
        timestamp: str,
    ):
        self.run_name = run_name
        self.epoch = epoch
        self.total_epochs = total_epochs
        self.model_idx = model_idx
        self.total_models = total_models
        self.loss = loss
        self.val_loss = val_loss
        self.timestamp = timestamp

    def to_dict(self) -> dict[str, Any]:
        return {s: getattr(self, s) for s in self.__slots__}


class ProgressCallback(Protocol):
    """Callable signature accepted by the training pipeline."""

    def __call__(self, payload: ProgressPayload) -> None: ...


class TrainingProgressCallback(keras.callbacks.Callback):
    """Keras callback that forwards per-epoch stats to a ``ProgressCallback``."""

    def __init__(
        self,
        callback: Callable[[ProgressPayload], None],
        run_name: str,
        total_epochs: int,
        total_models: int = 1,
        model_idx: int = 1,
    ):
        super().__init__()
        self._cb = callback
        self._run_name = run_name
        self._total_epochs = total_epochs
        self._total_models = total_models
        self._model_idx = model_idx

    def on_epoch_end(self, epoch: int, logs: dict | None = None) -> None:
        logs = logs or {}
        payload = ProgressPayload(
            run_name=self._run_name,
            epoch=epoch + 1,
            total_epochs=self._total_epochs,
            model_idx=self._model_idx,
            total_models=self._total_models,
            loss=float(logs.get("loss", 0)),
            val_loss=float(logs["val_loss"]) if "val_loss" in logs else None,
            timestamp=datetime.now().isoformat(),
        )
        try:
            self._cb(payload)
        except Exception as exc:
            logger.warning(
                "Progress callback failed at epoch %d: %s",
                epoch + 1,
                exc,
            )
