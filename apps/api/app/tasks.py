"""Celery tasks — long-running ML training."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

# TF env vars must be set before any TF import
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

from celery import Task

from .celery_app import celery_app

logger = logging.getLogger(__name__)


class TrainingTask(Task):
    """Custom task base with typed state updates."""

    name = "app.tasks.train_model_task"

    def on_failure(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        logger.error("Training task %s failed: %s", task_id, exc)

    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        logger.info("Training task %s completed successfully", task_id)


@celery_app.task(bind=True, base=TrainingTask, max_retries=0)
def train_model_task(self: TrainingTask, session_id: str, config: dict) -> dict:
    """Run a full grid-search training pipeline as a background Celery task.

    Progress is reported via ``self.update_state`` so the API can poll status.
    """
    self.update_state(state="PROGRESS", meta={"step": "init", "progress": 0, "message": "Initialisation"})

    try:
        from .services.ml.training_pipeline import run_training_pipeline

        def on_progress(step: str, progress: float, message: str, extra: dict | None = None) -> None:
            meta: dict[str, Any] = {"step": step, "progress": progress, "message": message}
            if extra:
                meta.update(extra)
            self.update_state(state="PROGRESS", meta=meta)

        self.update_state(state="PROGRESS", meta={"step": "loading", "progress": 5, "message": "Chargement des donnees"})

        result = run_training_pipeline(
            session_id=session_id,
            config=config,
            progress_callback=on_progress,
        )

        self.update_state(state="PROGRESS", meta={"step": "complete", "progress": 100, "message": "Entrainement termine"})

        return {
            "status": "success",
            "session_id": session_id,
            "best_model": result.get("best_model"),
            "metrics": result.get("metrics"),
            "output_dir": result.get("output_dir"),
            "duration_seconds": result.get("duration_seconds"),
        }

    except Exception as exc:
        logger.exception("Training task failed for session %s", session_id)
        self.update_state(
            state="FAILURE",
            meta={"step": "error", "progress": 0, "message": str(exc)},
        )
        raise
